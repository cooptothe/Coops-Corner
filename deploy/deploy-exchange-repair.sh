#!/usr/bin/env bash
# Backend-only release. Keep the web server and member accounts running.
set -euo pipefail
umask 077
cd /srv/corner/app
.venv-api/bin/python -m unittest   tests.test_zero_charge_retry tests.test_exchange_companions tests.test_collection_live   tests.test_collection_runner tests.test_collection_recovery   tests.test_all_book_collection tests.test_prop_exchange_policy

sudo systemctl stop corner-collection-recovery.timer
sudo systemctl stop corner-live-odds.timer corner-live-odds.service
bash deploy/repair-collection.sh --exchange-lay-fix
sudo systemctl enable --now corner-collection-recovery.timer corner-live-odds.timer
queued=0
for attempt in 1 2 3; do
  if sudo systemctl start corner-live-odds.service; then queued=1; break; fi
  sleep 2
done

systemctl is-active corner-collection.service corner-collection-recovery.timer corner-live-odds.timer
live_code=0
.venv-api/bin/python -m pipelines.live_odds_status --wait-seconds 75 || live_code=$?
.venv-api/bin/python -m pipelines.collection_exchange_repair
.venv-api/bin/python -m pipelines.collection_book_coverage
sudo journalctl -u corner-collection.service -n 12 --no-pager
git log -1 --oneline
if [ "$queued" -ne 1 ] || [ "$live_code" -ne 0 ]; then
  sudo journalctl -u corner-live-odds.service -n 8 --no-pager
  echo 'Worker restarted; live coverage is incomplete. Share the diagnostic output above.'
  exit 1
fi
echo 'Exchange repair deployed. Inspect returned-book coverage above; absent provider markets are not invented.'
