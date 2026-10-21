#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /srv/corner/app
if systemctl is-active --quiet corner-collection.service; then
  echo "Stop collector before installing this release."; exit 1
fi
.venv-api/bin/python -m unittest tests.test_expanded_main_books tests.test_reference_weights tests.test_cash_prop_books tests.test_collection_worker tests.test_collection_cadence tests.test_collection_adapters tests.test_collection_runner tests.test_collection_live tests.test_collection_recovery tests.test_collection_maintenance tests.test_database_catalog tests.test_props_refresh
sudo systemctl stop corner-staging-web
(cd web && pnpm test && pnpm build)
.venv-api/bin/python - <<'PY'
from dotenv import dotenv_values, set_key
from pathlib import Path
from corner.collection_policy import STANDARD, PROP_STANDARD
from corner.prop_markets import SHARP_BOOKS, PROP_EXTRA_SHARPS
from api.database import DEFAULT_REFERENCES
p=Path('/srv/corner/config/staging.env')
v=dotenv_values(p)
assert not v.get('ODDS_API_KEY')
assert v.get('CORNER_REFRESH_DAILY_CAP')=='0'
assert v.get('CORNER_PRIVATE_BETA')=='1'
main=list(dict.fromkeys([b.strip() for b in v.get('CORNER_TOOLS_REFERENCE_BOOKS','').split(',') if b.strip()]+list(DEFAULT_REFERENCES)))
props=list(dict.fromkeys([b.strip() for b in v.get('CORNER_PROPS_REFERENCE_BOOKS',v.get('CORNER_TOOLS_REFERENCE_BOOKS','')).split(',') if b.strip()]+sorted(SHARP_BOOKS|PROP_EXTRA_SHARPS)))
set_key(str(p),'CORNER_TOOLS_REFERENCE_BOOKS',','.join(main))
set_key(str(p),'CORNER_PROPS_REFERENCE_BOOKS',','.join(props))
p.chmod(0o600)
assert len(STANDARD)==9 and len(PROP_STANDARD)==10
print('Main and props reference configuration updated; staging remains key-free.')
PY
# Wait only for a single interrupted request to become eligible for existing
# bounded recovery. No reset, refund, retry of paid odds or quarantine removal.
.venv-api/bin/python - <<'PY'
import sqlite3,time
from corner.collection_activation import STATE
with sqlite3.connect(STATE.resolve().as_uri()+'?mode=ro',uri=True) as db:
    rows=db.execute("SELECT started FROM attempts WHERE state='unknown'").fetchall()
if len(rows)>1:raise SystemExit('Multiple uncertain requests: preserve ledger and review.')
if rows:
    delay=max(0,125-(time.time()-rows[0][0]))
    if delay>125:raise SystemExit('Unexpected request timestamp; review required.')
    if delay:print('Waiting for interrupted request recovery window.',flush=True)
    time.sleep(delay)
PY
.venv-api/bin/python -m pipelines.collection_recover --accept-single-request-quota-delta
sudo install -o root -g root -m 644 /srv/corner/collection/activation/approval.json /etc/corner/collection-activation.json
sudo systemctl restart corner-staging-accounts corner-staging-api
sudo systemctl start corner-staging-web corner-collection
for port in 8765 8766 3000; do
  ready=0
  for attempt in $(seq 1 45); do
    if /usr/bin/python3 -c "import socket; socket.create_connection(('127.0.0.1',$port),timeout=2).close()" 2>/dev/null; then ready=1; break; fi
    sleep 1
  done
  [ "$ready" -eq 1 ] || { echo "Service readiness failed on $port"; exit 1; }
done
curl --fail --silent --show-error --retry 5 --retry-delay 2 https://coopscorner.tech/login >/dev/null
systemctl is-active corner-collection corner-staging-accounts corner-staging-api corner-staging-web
.venv-api/bin/python -m pipelines.collection_admin status --state /srv/corner/config/collection-live.sqlite3
sudo journalctl -u corner-collection.service -n 10 --no-pager
git log -1 --oneline
echo 'Expanded books deployed. Inspect worker publication status above; actual provider coverage varies by market.'
