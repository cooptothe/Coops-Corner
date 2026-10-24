#!/usr/bin/env bash
# Run manually as corneradmin. No purchases, reset, or refund.
set -euo pipefail
umask 077
exchange_fix=0
if [ "${1:-}" = --exchange-lay-fix ] && [ "$#" -eq 1 ]; then
  exchange_fix=1
elif [ "$#" -ne 0 ]; then
  echo "Usage: bash deploy/repair-collection.sh [--exchange-lay-fix]"; exit 1
fi
cd /srv/corner/app
exec 9>/srv/corner/config/collection-repair.lock
flock -n 9 || { echo "Another repair is running."; exit 1; }
.venv-api/bin/python -m pipelines.collection_health || [ "$?" -eq 10 ]
sudo systemctl stop corner-collection.service
.venv-api/bin/python - <<'PY'
import sqlite3,time
from corner.collection_activation import STATE
with sqlite3.connect(STATE.resolve().as_uri()+'?mode=ro',uri=True) as db:
    rows=db.execute("SELECT started FROM attempts WHERE state='unknown' UNION ALL SELECT started FROM quota_inventory WHERE state='unknown'").fetchall()
if len(rows)==1:
    delay=125-(time.time()-rows[0][0])
    if delay>125: raise SystemExit('Unexpected request timestamp; stopped.')
    if delay>0:
        print('Waiting for the uncertain request to age safely before reconciliation.',flush=True)
        time.sleep(delay)
PY
# Existing recovery refuses multiple unknowns, insufficient evidence, changed
# credentials, expired cycles, pool overruns and protected-reserve violations.
# Owner confirmed this key is used exclusively by this collector.
.venv-api/bin/python -m pipelines.collection_recover --accept-single-request-quota-delta
if [ "$exchange_fix" -eq 1 ]; then
  .venv-api/bin/python -m pipelines.collection_exchange_repair --apply
fi
sudo install -o root -g root -m 644 /srv/corner/collection/activation/approval.json /etc/corner/collection-activation.json
sudo systemctl start corner-collection.service
sleep 8
systemctl is-active corner-collection.service
.venv-api/bin/python -m pipelines.collection_health || [ "$?" -eq 10 ]
sudo journalctl -u corner-collection.service -n 12 --no-pager
echo "Worker restarted. Check the states above: ready/publication_pending means running; after_hours means the schedule is closed; publication_failed/backoff requires database review."
