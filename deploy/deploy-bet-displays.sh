#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /srv/corner/app
pnpm --dir web test

# Keep a working UI build available if compilation fails.
previous=$(mktemp -d /srv/corner/backups/web-bet-displays-XXXXXXXX)
sudo systemctl stop corner-staging-web
if [ -d web/.next ]; then mv web/.next "$previous/.next"; fi
if ! pnpm --dir web build; then
  if [ -d web/.next ]; then mv web/.next "$previous/failed-build"; fi
  if [ -d "$previous/.next" ]; then mv "$previous/.next" web/.next; fi
  sudo systemctl start corner-staging-web
  echo 'Build failed; previous frontend restored. Collection remains stopped.'
  exit 1
fi
sudo systemctl start corner-staging-web
ready=0
for attempt in $(seq 1 90); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 http://127.0.0.1:3000/login || true)
  if [ "$code" = 200 ]; then ready=1; break; fi
  sleep 1
done
[ "$ready" -eq 1 ] || { sudo journalctl -u corner-staging-web -n 25 --no-pager; exit 1; }

# Existing collector approval is release-specific, even for frontend changes.
bash deploy/repair-collection.sh
sudo systemctl start corner-collection-recovery.timer corner-live-odds.timer
if ! sudo systemctl start corner-live-odds.service; then
  sudo journalctl -u corner-live-odds.service -n 8 --no-pager
fi
curl --fail --silent --show-error --retry 4 --retry-delay 2 --max-time 15 \
  -o /dev/null -w 'Public login: %{http_code}\n' https://coopscorner.tech/login
echo 'Display routing deployed. Configure Account > One-click bet displays.'
git log -1 --oneline
