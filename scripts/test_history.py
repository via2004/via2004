from datetime import date, datetime
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from history import archive_days, combined_days, history_svg
from import_history import summarize, TZ


class HistoryTests(unittest.TestCase):
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
