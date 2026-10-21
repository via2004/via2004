"""Create a public, aggregate-only activity estimate from local Codex logs.

No prompts, code, file paths, or session identifiers are exported.
The original logs and WakaTime ingestion state are never modified.
"""

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Shanghai')
MAX_GAP_SECONDS = 15 * 60


def merge_intervals(intervals):
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def summarize(root, cutoff):
    sessions = defaultdict(set)
    counts = defaultdict(int)
    files = list((root / 'sessions').rglob('*.jsonl'))
    files += list((root / 'archived_sessions').rglob('*.jsonl'))
    skipped = 0
    for path in files:
        session_id = None
        internal = False
        with path.open(errors='replace') as stream:
            for line in stream:
                try:
                    record = json.loads(line)
                    payload = record.get('payload') or {}
                    if record.get('type') == 'session_meta':
                        session_id = payload.get('id')
                        source = payload.get('source')
                        internal = isinstance(source, dict) and 'subagent' in source
                        continue
                    if not session_id or internal:
                        continue
                    kind = payload.get('type')
                    meaningful = (
                        record.get('type') == 'response_item' and
                        (kind in ('function_call', 'function_call_output', 'custom_tool_call', 'custom_tool_call_output') or
                         kind == 'message' and payload.get('role') in ('user', 'assistant'))
                    ) or (record.get('type') == 'event_msg' and kind in ('user_message', 'agent_message'))
                    if not meaningful:
                        continue
                    stamp = datetime.fromisoformat(record['timestamp'].replace('Z', '+00:00'))
                    if stamp.tzinfo is None:
                        continue
                    if stamp.astimezone(TZ).date() >= cutoff:
                        continue
                    sessions[session_id].add(stamp.timestamp())
                except (ValueError, KeyError, TypeError):
                    skipped += 1

    active_sessions = defaultdict(set)
    intervals = []
    for sid, stamps in sessions.items():
        points = sorted(stamps)
        for point in points:
            day = datetime.fromtimestamp(point, TZ).date().isoformat()
            counts[day] += 1
            active_sessions[day].add(sid)
        for a, b in zip(points, points[1:]):
            if 0 < b - a <= MAX_GAP_SECONDS:
                intervals.append((a, b))
    seconds = defaultdict(float)
    for start, end in merge_intervals(intervals):
        current = start
        while current < end:
            local = datetime.fromtimestamp(current, TZ)
            tomorrow = datetime.combine(local.date() + timedelta(days=1), datetime.min.time(), TZ).timestamp()
            stop = min(end, tomorrow)
            seconds[local.date().isoformat()] += stop - current
            current = stop
    days = {day: {'estimated_ai_seconds': round(seconds[day]),
                  'activity_events': counts[day],
                  'sessions': len(active_sessions[day])} for day in sorted(counts)}
    return {
        'schema_version': 1,
        'timezone': str(TZ),
        'snapshot_at': datetime.now(timezone.utc).isoformat(),
        'cutoff_exclusive': cutoff.isoformat(),
        'method': 'Local Codex activity estimate: merge every log fragment by session ID; deduplicate timestamps; connect adjacent activity within 15 minutes; union overlapping sessions. Excludes internal subagents. Not a precise work-time measurement.',
        'source_files': len(files),
        'unique_sessions': len(sessions),
        'unreadable_records': skipped,
        'days': days,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cutoff', type=datetime.fromisoformat,
                        default=datetime.now(TZ), help='Exclude this day and later; future days come from WakaTime.')
    args = parser.parse_args()
    data = summarize(args.codex_dir, args.cutoff.date())
    if not data['days']:
        raise SystemExit('No historical activity found; output not changed.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'days': len(data['days']), 'from': min(data['days']), 'to': max(data['days']),
                      'sessions': data['unique_sessions'], 'files': data['source_files'],
                      'approx_hours': round(sum(d['estimated_ai_seconds'] for d in data['days'].values()) / 3600, 1)}))


if __name__ == '__main__':
    main()
