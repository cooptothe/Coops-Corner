#!/usr/bin/env bash
# Recover SQLite through its own journal protocol; never remove journal files.
set -euo pipefail
umask 077
cd /srv/corner/app
trends_timer_was_active=0
if systemctl is-active --quiet corner-trends.timer; then trends_timer_was_active=1; fi
for unit in corner-trends.timer corner-trends.service; do
  if systemctl cat "$unit" >/dev/null 2>&1; then sudo systemctl stop "$unit"; fi
done
sudo systemctl stop corner-staging-accounts
.venv-api/bin/python - <<'PY'
from contextlib import closing
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat

path=Path('/srv/corner/app/retained/lab-catalog.sqlite3')
info=path.lstat()
if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid():
    raise SystemExit('Owner-controlled regular Lab database required.')
if shutil.disk_usage(path.parent).free < 3*path.stat().st_size:
    raise SystemExit('More free space required before journal recovery.')
saved=Path('/srv/corner/backups')/('lab-before-recovery-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
saved.mkdir(mode=0o700)
for suffix in ('','-journal','-wal','-shm'):
    source=Path(str(path)+suffix)
    if source.exists():
        if source.is_symlink() or not source.is_file():raise SystemExit('Unexpected Lab sidecar type.')
        shutil.copy2(source,saved/source.name)
with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=rw',uri=True,timeout=15)) as db:
    # SQLite automatically rolls back a hot journal before this read.
    checks=[row[0] for row in db.execute('PRAGMA quick_check')]
    if checks!=['ok']:raise SystemExit('Lab integrity check failed; recovery copy preserved.')
    count=db.execute('SELECT count(*) FROM lab_catalog').fetchone()[0]
print(json.dumps({'result':'lab_integrity_ok','saved_lines':count,'recovery_copy':str(saved),'provider_calls':0}))
PY
sudo systemctl start corner-staging-accounts

if [ "$trends_timer_was_active" -eq 1 ]; then sudo systemctl start corner-trends.timer; fi
