#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /srv/corner/app
.venv-api/bin/python -m unittest tests.test_collection_health tests.test_collection_runner tests.test_competition_aliases
sudo systemctl stop corner-collection-recovery.timer corner-live-odds.timer corner-live-odds.service corner-collection.service
sudo -u postgres psql -X -p 5432 -d corner_staging -v ON_ERROR_STOP=1 < db/migrations/016_corner_competition_provider_aliases.sql
.venv-api/bin/python - <<'PY'
from contextlib import closing
import json
import sqlite3
import time
from dotenv import dotenv_values
from corner.collection_activation import STATE, RETAINED
from corner.collection_maintenance import maintenance_lock
from pipelines.collection_live import writer
from pipelines.collection_publication import MainPublisher
config=dotenv_values('/srv/corner/config/collection.env')
with maintenance_lock(exclusive=True,timeout=30), closing(sqlite3.connect(STATE)) as db:
    rows=db.execute("SELECT token,payload FROM publication_outbox WHERE published_at IS NULL AND token NOT IN (SELECT token FROM publication_failures WHERE quarantined=1) ORDER BY rowid LIMIT 20").fetchall()
    for token,payload in rows:
        record=json.loads(payload)
        try:
            MainPublisher(RETAINED,lambda:writer(config))(token,record)
        except Exception as error:
            print(json.dumps({'result':'publication_still_blocked','error_type':type(error).__name__,'sqlstate':getattr(error,'pgcode',None),'provider_calls':0}))
            raise SystemExit('Saved capture could not publish; state preserved for review.') from None
        # The normal worker still owns acknowledgement. Only its retry delay is
        # released after successful idempotent publication; charges are untouched.
        with db:
            db.execute('UPDATE publication_failures SET retry_at=0 WHERE token=? AND quarantined=0',(token,))
            db.execute('INSERT INTO quota_audit(at,action,evidence,detail) VALUES(?,?,?,?)',
                (time.time(),'publication-replay-verified','Retained capture replay succeeded after competition alias migration; accounting unchanged',json.dumps({'token':token,'sport':record['job']['sport']})))
    print(json.dumps({'saved_publications_verified':len(rows),'provider_calls':0,'accounting_changed':False}))
PY
# Fresh quota/HEAD approval through the existing guarded path; no accounting reset.
bash deploy/repair-collection.sh
sudo systemctl enable --now corner-collection-recovery.timer corner-live-odds.timer
sudo systemctl start corner-live-odds.service
echo 'Competition alias migration applied; saved publications retry without new odds purchases.'
systemctl is-active corner-collection.service corner-collection-recovery.timer corner-live-odds.timer
.venv-api/bin/python -m pipelines.collection_health
.venv-api/bin/python -m pipelines.collection_admin status --state /srv/corner/config/collection-live.sqlite3
sudo journalctl -u corner-collection.service -n 12 --no-pager
git log -1 --oneline
