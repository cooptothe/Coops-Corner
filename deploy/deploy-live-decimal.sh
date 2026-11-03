#!/usr/bin/env bash
# Run as corneradmin after pulling the reviewed release with collection stopped.
set -euo pipefail
umask 077
cd /srv/corner/app
.venv-api/bin/python -m unittest tests.test_live_products tests.test_live_odds
pnpm --dir web test

stamp=$(date -u +%Y%m%dT%H%M%SZ)
previous="/srv/corner/backups/web-before-live-decimal-$stamp"
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
bash deploy/repair-collection.sh
sudo systemctl start corner-collection-recovery.timer corner-live-odds.timer corner-live-odds.service
curl --fail --silent --show-error --max-time 15 -o /dev/null -w 'Public login: %{http_code}\n' https://coopscorner.tech/login
echo 'Live decimal serialization fix deployed. Reload open browser tabs to receive the updated formatter.'
git log -1 --oneline
