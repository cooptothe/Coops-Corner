#!/usr/bin/env bash
# Run after stopping collection, reconciling on the previous release, and pulling.
set -euo pipefail
umask 077
cd /srv/corner/app
df -h /
.venv-api/bin/python - <<'PY'
import shutil
if shutil.disk_usage('/srv/corner').free < 2*1024**3:
    raise SystemExit('Less than 2 GiB free: preserve ledger and free workspace storage before accelerating collection.')
PY
.venv-api/bin/python -m unittest \
 tests.test_deadline_collection tests.test_full_budget_policy \
 tests.test_collection_worker tests.test_collection_runner \
 tests.test_collection_live tests.test_collection_recovery \
 tests.test_collection_adapters tests.test_all_book_collection \
 tests.test_collection_cadence tests.test_november_cadence \
 tests.test_optimized_cadence tests.test_live_pacing tests.test_live_odds \
 tests.test_collection_setup tests.test_collection_onboarding \
 tests.test_collection_rollover tests.test_collection_maintenance \
 tests.test_collection_standard tests.test_collection_smoke \
 tests.test_provider_cadence_budget
.venv-api/bin/python -m pipelines.collection_budget_upgrade --use-full-quota
sudo systemctl restart corner-staging-api
ready=0
for attempt in $(seq 1 90); do
 code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 http://127.0.0.1:8765/api/v1/health || true)
 if [ "$code" = 401 ]; then ready=1; break; fi
 sleep 1
done
[ "$ready" -eq 1 ] || { sudo journalctl -u corner-staging-api -n 25 --no-pager; exit 1; }
bash deploy/repair-collection.sh
sudo systemctl start corner-collection-recovery.timer corner-live-odds.timer
if ! sudo systemctl start corner-live-odds.service; then
 sudo journalctl -u corner-live-odds.service -n 10 --no-pager
 echo 'Live queue failed; pregame collector remains running. Share output.'
fi
.venv-api/bin/python -m pipelines.collection_deadline_status
systemctl is-active corner-collection.service corner-collection-recovery.timer corner-live-odds.timer
echo 'Deadline pacing deployed: Nov 20 midnight Central. Original quota cycle and all accounting preserved.'
git log -1 --oneline
