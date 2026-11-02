#!/usr/bin/env bash
# Run as corneradmin after pulling the reviewed release with collection stopped.
set -euo pipefail
umask 077
cd /srv/corner/app
.venv-api/bin/python -m unittest tests.test_current_quote_scopes tests.test_indexed_quote_lookup tests.test_database_catalog tests.test_performance_paths tests.test_feed_speed tests.test_main_feed_profile
# Restore verified collection first; frontend profiling must not leave it stopped.
bash deploy/repair-collection.sh
sudo systemctl start corner-collection-recovery.timer
sudo systemctl stop corner-staging-api
if ! timeout 30s .venv-api/bin/python -m pipelines.main_feed_profile; then
  echo 'Main query still needs review; continuing to restore application services.'
fi
pnpm --dir web test

stamp=$(date -u +%Y%m%dT%H%M%SZ)
previous="/srv/corner/backups/web-before-scoped-feed-$stamp"
mkdir -p "$previous"
sudo systemctl stop corner-staging-web
if [ -d web/.next ]; then mv web/.next "$previous/.next"; fi
if ! pnpm --dir web build; then
  if [ -d web/.next ]; then mv web/.next "$previous/failed-build"; fi
  if [ -d "$previous/.next" ]; then mv "$previous/.next" web/.next; fi
  sudo systemctl start corner-staging-web
  echo 'Build failed; previous frontend restored. Collection remains stopped.'
  exit 1
fi
sudo systemctl restart corner-staging-api corner-staging-accounts
sudo systemctl start corner-staging-web
ready=0
for attempt in $(seq 1 90); do
  api=$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 http://127.0.0.1:8765/api/v1/health || true)
  web=$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 http://127.0.0.1:3000/login || true)
  if [ "$api" = 401 ] && [ "$web" = 200 ]; then ready=1; break; fi
  sleep 1
done
[ "$ready" -eq 1 ] || { echo 'Application startup incomplete; share service logs.'; exit 1; }
sudo systemctl start corner-collection-recovery.timer corner-live-odds.timer corner-live-odds.service
curl --fail --silent --show-error --max-time 15 -o /dev/null -w 'Public login: %{http_code}\n' https://coopscorner.tech/login
echo 'Current-scope quote reader deployed. Review query timing and fresh publication evidence above.'
sudo journalctl -u corner-collection.service --since "2 minutes ago" -n 12 --no-pager
.venv-api/bin/python -m pipelines.collection_health
git log -1 --oneline
