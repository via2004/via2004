"""Install the local aggregate-only collector as a user systemd timer."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess


def quoted(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--codex-dir', type=Path, required=True)
    args = parser.parse_args()
    root = Path.home() / '.local/share/codex-activity-sync'
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    source = Path(__file__).resolve().parent
    for name in ('sync_activity.py', 'import_history.py'):
        shutil.copy2(source / name, root / name)
    units = Path.home() / '.config/systemd/user'
    units.mkdir(parents=True, exist_ok=True)
    service = '\n'.join([
        '[Unit]', 'Description=Sync aggregate Codex activity to GitHub', '',
        '[Service]', 'Type=oneshot',
        'ExecStart=/usr/bin/python3 ' + quoted(root / 'sync_activity.py') +
        ' --codex-dir ' + quoted(args.codex_dir.resolve()) +
        ' --state-dir ' + quoted(root / 'state') + ' --repo ' + quoted(args.repo),
        f'Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{os.getuid()}/bus',
        'TimeoutStartSec=180', 'UMask=0077', 'Nice=10', '',
    ])
    timer = '\n'.join([
        '[Unit]', 'Description=Sync Codex activity every 15 minutes', '',
        '[Timer]', 'OnCalendar=*-*-* *:00/15:00', 'OnStartupSec=1min',
        'Persistent=true', 'RandomizedDelaySec=30', '',
        '[Install]', 'WantedBy=timers.target', '',
    ])
    (units / 'codex-activity-sync.service').write_text(service)
    (units / 'codex-activity-sync.timer').write_text(timer)
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', '--user', 'enable', '--now', 'codex-activity-sync.timer'], check=True)
    print('Installed local collector. Only aggregate daily statistics will be published.')


if __name__ == '__main__':
    main()
