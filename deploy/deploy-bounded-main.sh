#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /srv/corner/app
.venv-api/bin/python -m unittest tests.test_incremental_main_reads tests.test_current_quote_scopes tests.test_indexed_quote_lookup tests.test_database_catalog tests.test_performance_paths tests.test_feed_speed tests.test_main_feed_profile
bash deploy/repair-collection.sh
sudo systemctl start corner-collection-recovery.timer
sudo systemctl stop corner-staging-api
if ! timeout 45s .venv-api/bin/python -m pipelines.main_feed_profile; then
  echo 'Quote timing failed; restoring services and keeping collection running. Share output.'
fi
sudo systemctl start corner-staging-api
ready=0
for attempt in $(seq 1 90); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 http://127.0.0.1:8765/api/v1/health || true)
  if [ "$code" = 401 ]; then ready=1; break; fi
  sleep 1
done
[ "$ready" -eq 1 ] || { sudo journalctl -u corner-staging-api -n 25 --no-pager; exit 1; }
sudo systemctl start corner-live-odds.timer corner-live-odds.service
if ! timeout 120s .venv-api/bin/python -m pipelines.main_feed_http_probe; then
  sudo journalctl -u corner-staging-api --since "3 minutes ago" -n 35 --no-pager
  echo 'Authenticated feed check failed. Share this output; collection remains running.'
fi
.venv-api/bin/python -m pipelines.collection_health
sudo journalctl -u corner-collection.service --since "2 minutes ago" -n 10 --no-pager
git log -1 --oneline
