#!/usr/bin/env bash
# Deploy matching feed API and frontend contracts; retain existing credit policy.
set -euo pipefail
umask 077
cd /srv/corner/app
.venv-api/bin/python -m unittest tests.test_feed_speed tests.test_lab_reliability tests.test_lab_research_board tests.test_lab_catalog tests.test_trends_service tests.test_feed_quote_bundles tests.test_product_api tests.test_database_catalog tests.test_performance_paths tests.test_live_products tests.test_live_pacing tests.test_live_odds tests.test_collection_runner tests.test_collection_adapters tests.test_reference_weights tests.test_all_book_references tests.test_novig_prop_reference
(cd web && pnpm test)
sudo systemctl stop corner-collection-recovery.timer corner-live-odds.timer corner-live-odds.service corner-collection.service
# One-time offline indexes; leave every retained record and charge intact.
.venv-api/bin/python -m pipelines.feed_indexes
# The new API is compatible with the previous frontend. Bring it up first.
sudo systemctl restart corner-staging-accounts corner-staging-api
api_ready=0
for attempt in $(seq 1 90); do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8765/api/v1/health || true)"
  if [ "$code" = 401 ]; then api_ready=1; break; fi
  sleep 1
done
if [ "$api_ready" -ne 1 ]; then
  sudo systemctl status corner-staging-api --no-pager -l
  echo 'API startup did not complete; collection remains stopped for review.'
  exit 1
fi
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
previous="/srv/corner/backups/web-before-feed-loading-$stamp"
failed="/srv/corner/backups/web-failed-feed-loading-$stamp"
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


# Apply the tournament alias repair too when upgrading from an earlier release.
bash deploy/repair-competition-publication.sh
sudo systemctl enable --now corner-collection-recovery.timer corner-live-odds.timer
queued=0
for attempt in 1 2 3; do
  if sudo systemctl start corner-live-odds.service; then queued=1; break; fi
  sleep 2
done
curl --fail --silent --show-error --retry 10 --retry-connrefused --retry-delay 2 https://coopscorner.tech/login >/dev/null
systemctl is-active corner-staging-web corner-staging-api corner-collection.service corner-collection-recovery.timer corner-live-odds.timer
if [ "$queued" -ne 1 ]; then
  sudo journalctl -u corner-live-odds.service -n 8 --no-pager
  echo 'Web fix deployed; live scheduler queue needs review.'
  exit 1
fi
git log -1 --oneline
echo 'Progressive feed loading, shared snapshot calculations and budget-paced live collection deployed. Reload the browser.'
.venv-api/bin/python -m pipelines.live_odds_status --wait-seconds 60

sudo systemctl show corner-staging-api -p MemoryCurrent

# Verify Lab inventory without buying odds or fetching ESPN.
timeout 15s .venv-api/bin/python -m pipelines.lab_status || echo "Optional Lab count did not complete; feed services remain running."
