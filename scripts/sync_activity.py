"""Continuously publish aggregate Codex time; keep raw event timestamps local."""

import argparse
import base64
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import subprocess

from import_history import read_sessions, summarize_sessions, TZ


def merge_sessions(previous, current):
    result = {sid: set(points) for sid, points in previous.items()}
    for sid, points in current.items():
        result.setdefault(sid, set()).update(points)
    return result


def atomic_json(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def build_snapshot(sessions, source_files, skipped, today):
    data = summarize_sessions(sessions, today + timedelta(days=1), source_files, skipped)
    if not data['days']:
        raise ValueError('No activity found; existing public statistics will be preserved.')
    data.pop('snapshot_at')
    data.pop('cutoff_exclusive')
    data.update(schema_version=2, coverage_start=min(data['days']), coverage_end=today.isoformat(),
                last_event_at=datetime.fromtimestamp(max(max(s) for s in sessions.values() if s), timezone.utc).isoformat())
    return data


def gh_api(endpoint, payload=None):
    command = ['/usr/bin/gh', 'api', endpoint]
    if payload is not None:
        command += ['--method', 'PUT', '--input', '-']
    result = subprocess.run(command, input=json.dumps(payload) if payload is not None else None,
                            text=True, capture_output=True, timeout=60)
    if result.returncode:
        if payload is None and 'HTTP 404' in result.stderr:
            return None
        raise RuntimeError('GitHub API request failed; local data retained for the next retry.')
    return json.loads(result.stdout)


def publish(repo, snapshot):
    endpoint = f'repos/{repo}/contents/data/codex-activity.json'
    for attempt in range(3):
        remote = gh_api(endpoint)
        if remote:
            old = json.loads(base64.b64decode(remote['content']))
            if old == snapshot:
                return False
            # A second collector with less history must not silently erase the archive.
            for day, values in old.get('days', {}).items():
                if values['estimated_ai_seconds'] > snapshot['days'].get(day, {}).get('estimated_ai_seconds', -1):
                    raise ValueError('Remote history contains activity absent locally; refusing to overwrite it.')
        content = base64.b64encode((json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n').encode()).decode()
        payload = {'message': 'chore: sync local Codex activity', 'content': content}
        if remote:
            payload['sha'] = remote['sha']
        try:
            gh_api(endpoint, payload)
            return True
        except RuntimeError:
            if attempt == 2:
                raise
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-dir', type=Path, required=True)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--output', type=Path, help='Write aggregate output locally instead of publishing.')
    args = parser.parse_args()
    args.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (args.state_dir / 'sync.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Another sync is active; skipping.')
            return
        cache_path = args.state_dir / 'events.json'
        previous = json.loads(cache_path.read_text()) if cache_path.exists() else {}
        current, count, skipped = read_sessions(args.codex_dir)
        sessions = merge_sessions(previous.get('sessions', {}), current)
        snapshot = build_snapshot(sessions, max(count, previous.get('source_files', 0)), skipped, datetime.now(TZ).date())
        # Preserve deduplicated timestamps even if old rollout files are later archived or removed.
        atomic_json(cache_path, {'source_files': snapshot['source_files'],
                                 'sessions': {sid: sorted(points) for sid, points in sessions.items()}})
        atomic_json(args.state_dir / 'latest-summary.json', snapshot)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            atomic_json(args.output, snapshot)
            changed = True
        else:
            changed = publish(args.repo, snapshot)
        print(json.dumps({'published_or_exported': changed, 'coverage_end': snapshot['coverage_end'],
                          'days': len(snapshot['days']), 'source_files': snapshot['source_files']}))


if __name__ == '__main__':
    main()
