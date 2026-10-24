#!/usr/bin/env bash
# Frontend-only quote loader release; renew the worker's exact release approval.
set -euo pipefail
umask 077
cd /srv/corner/app
(cd web && pnpm test)
sudo systemctl stop corner-collection-recovery.timer corner-live-odds.timer corner-live-odds.service corner-collection.service
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
previous="/srv/corner/backups/web-before-snapshot-quotes-$stamp"
failed="/srv/corner/backups/web-failed-snapshot-quotes-$stamp"
build_pending=0
web_stopped=0
restore_web() {
  result=$?
  trap - EXIT
  if [ "$build_pending" -eq 1 ]; then
    if [ -d web/.next ]; then mv web/.next "$failed"; fi
    if [ -d "$previous" ]; then mv "$previous" web/.next; fi
    sudo systemctl start corner-staging-web || true
    echo 'Web build failed; previous saved web build restored. Collection remains stopped for review.'
  fi
  if [ "$web_stopped" -eq 1 ]; then sudo systemctl start corner-staging-web || true; fi
  exit "$result"
}
trap restore_web EXIT

web_stopped=1
sudo systemctl stop corner-staging-web
if [ -d web/.next ]; then cp -a web/.next "$previous"; fi
build_pending=1
(cd web && pnpm build)
sudo systemctl start corner-staging-web
curl --fail --silent --show-error --retry 15 --retry-connrefused --retry-delay 2 \
  http://127.0.0.1:3000/login >/dev/null
build_pending=0
web_stopped=0


bash deploy/repair-collection.sh
sudo systemctl enable --now corner-collection-recovery.timer corner-live-odds.timer
queued=0
for attempt in 1 2 3; do
  if sudo systemctl start corner-live-odds.service; then queued=1; break; fi
  sleep 2
done
curl --fail --silent --show-error --retry 10 --retry-connrefused --retry-delay 2 https://coopscorner.tech/login >/dev/null
systemctl is-active corner-staging-web corner-collection.service corner-collection-recovery.timer corner-live-odds.timer
if [ "$queued" -ne 1 ]; then
  sudo journalctl -u corner-live-odds.service -n 8 --no-pager
  echo 'Web fix deployed; live scheduler queue needs review.'
  exit 1
fi
git log -1 --oneline
echo 'Large quote snapshot loader deployed. Reload the browser to load the new frontend.'
