from datetime import date, datetime
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from history import archive_days, combined_days, history_svg
from import_history import summarize, TZ
from sync_activity import merge_sessions, build_snapshot


class HistoryTests(unittest.TestCase):
    def test_persistent_cache_keeps_archived_fragments_and_deduplicates(self):
        previous = {'thread': [1792454400, 1792454700]}
        current = {'thread': {1792454700, 1792455000}, 'other': {1792454600, 1792454900}}
        merged = merge_sessions(previous, current)
        self.assertEqual(len(merged['thread']), 3)
        result = build_snapshot(merged, 4, 0, date(2026, 11, 2))
        self.assertEqual(sum(d['estimated_ai_seconds'] for d in result['days'].values()), 600)
        self.assertEqual(merge_sessions(merged, {}), merged)
        self.assertNotIn('thread', json.dumps(result))

    def test_continuous_local_history_is_authoritative_without_service_overlap(self):
        local = {'schema_version': 2, 'days': {'2026-11-01': {'estimated_ai_seconds': 7786}}}
        service = {'2026-11-01': {'ai_seconds': 226}, '2026-11-02': {'ai_seconds': 900}}
        self.assertEqual(combined_days(local, service), {'2026-11-01': 7786})

    def test_fragments_deduplicate_and_parallel_activity_does_not_double_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / 'sessions'
            folder.mkdir()
            def log(name, sid, stamps, source='vscode'):
                records = [{'type': 'session_meta', 'payload': {'id': sid, 'source': source}}]
                records += [{'type': 'response_item', 'timestamp': stamp,
                             'payload': {'type': 'message', 'role': 'assistant'}} for stamp in stamps]
                (folder / name).write_text('\n'.join(json.dumps(row) for row in records))
            log('a.jsonl', 'one', ['2026-10-20T15:55:00Z', '2026-10-20T16:05:00Z'])
            log('b.jsonl', 'one', ['2026-10-20T16:05:00Z', '2026-10-20T16:10:00Z'])
            log('c.jsonl', 'two', ['2026-10-20T16:03:00Z', '2026-10-20T16:08:00Z'])
            log('internal.jsonl', 'internal', ['2026-10-20T15:45:00Z', '2026-10-20T16:00:00Z'], {'subagent': {}})
            log('today.jsonl', 'today', ['2026-10-22T00:00:00Z', '2026-10-22T00:10:00Z'])
            data = summarize(root, date(2026, 10, 22))
            self.assertEqual(data['unique_sessions'], 2)
            self.assertEqual(data['days']['2026-10-20']['estimated_ai_seconds'], 300)
            self.assertEqual(data['days']['2026-10-21']['estimated_ai_seconds'], 600)
            self.assertEqual(sum(x['activity_events'] for x in data['days'].values()), 5)

    def test_daily_archive_retains_old_days_and_replaces_instead_of_adding(self):
        old = {'2026-01-01': {'ai_seconds': 100}, '2026-10-21': {'ai_seconds': 200}}
        rows = [{'range': {'date': '2026-10-21'}, 'grand_total': {'ai_additions': 8},
                 'categories': [{'name': 'AI Coding', 'total_seconds': 300}]}]
        archived = archive_days(old, rows)
        self.assertEqual(archived['2026-01-01']['ai_seconds'], 100)
        self.assertEqual(archived['2026-10-21']['ai_seconds'], 300)
        self.assertEqual(archive_days(archived, rows), archived)

    def test_baseline_and_service_periods_never_overlap(self):
        baseline = {'cutoff_exclusive': '2026-10-22', 'unique_sessions': 2,
                    'days': {'2026-10-21': {'estimated_ai_seconds': 3600, 'activity_events': 4}}}
        daily = {'2026-10-21': {'ai_seconds': 9999}, '2026-10-22': {'ai_seconds': 600}}
        self.assertEqual(sum(combined_days(baseline, daily).values()), 4200)
        svg = history_svg(baseline, daily, datetime(2026, 10, 22, tzinfo=TZ))
        ET.fromstring(svg)
        self.assertIn('2026-10', svg)


if __name__ == '__main__':
    unittest.main()
