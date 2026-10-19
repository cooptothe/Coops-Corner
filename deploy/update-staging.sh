#!/usr/bin/env bash
# Run after fast-forwarding /srv/corner/app to this release. No collector activation.
set -euo pipefail
umask 077
cd /srv/corner/app

.venv-api/bin/python -m unittest \
  tests.test_friend_codes tests.test_friend_membership tests.test_beta_access tests.test_beta_terms tests.test_trial_enforcement tests.test_billing_offer tests.test_beta_billing tests.test_beta_invoices tests.test_member_load tests.test_large_tool_pages tests.test_manual_markets tests.test_alternate_props tests.test_release_probe tests.test_props_dfs_references tests.test_prop_markets tests.test_one_sided_props tests.test_automatic_prop_margin tests.test_assumed_margin_props tests.test_props_refresh \
  tests.test_clv tests.test_tracker_service tests.test_clv_coverage tests.test_tracker_store \
  tests.test_lab_research_board tests.test_trends_service tests.test_trends_worker tests.test_prop_trends \
  tests.test_additional_markets tests.test_featured_markets \
  tests.test_featured_middles tests.test_featured_promos tests.test_product_api \
  tests.test_database_catalog tests.test_collection_worker tests.test_collection_runner \
  tests.test_collection_adapters tests.test_collection_live tests.test_refresh_service

# Add friend-rate evidence before the account schema is migrated.
test -f /usr/local/lib/corner-backup/billing_checkpoint.py
sudo install -o root -g root -m 644 deploy/backup/billing_checkpoint.py /usr/local/lib/corner-backup/billing_checkpoint.py

cd web
pnpm install --frozen-lockfile
pnpm test

corner_saved_build="/srv/corner/backups/web-before-additional-$(date -u +%Y%m%dT%H%M%SZ)"
if [ -d .next ]; then
  cp -a .next "$corner_saved_build"
fi
corner_build_complete=0
corner_web_stopped=0
corner_backend_stopped=0
corner_restore_web() {
  corner_exit=$?
  trap - EXIT
  if [ "$corner_exit" -ne 0 ]; then
    if [ "$corner_web_stopped" -eq 1 ] && [ "$corner_build_complete" -eq 0 ] && [ -d "$corner_saved_build" ]; then
      # Only this exact checkout's generated build is moved; preserve failed output for inspection.
      if [ -d /srv/corner/app/web/.next ]; then
        mv /srv/corner/app/web/.next "${corner_saved_build}-failed"
      fi
      cp -a "$corner_saved_build" /srv/corner/app/web/.next
    fi
    if [ "$corner_web_stopped" -eq 1 ]; then
      sudo systemctl start corner-staging-web || true
    fi
    if [ "$corner_backend_stopped" -eq 1 ]; then
      sudo systemctl start corner-staging-accounts corner-staging-api || true
    fi
    echo 'Deployment failed; no collection or billing activation changed.' >&2
  fi
  exit "$corner_exit"
}
trap corner_restore_web EXIT
sudo systemctl stop corner-staging-web
corner_web_stopped=1
pnpm build
corner_build_complete=1
cd /srv/corner/app
corner_backend_stopped=1
sudo systemctl stop corner-staging-accounts corner-staging-api
.venv-api/bin/python -m pipelines.beta_admin --db /srv/corner/config/staging-tracker.sqlite3 status
sudo systemctl restart corner-staging-accounts corner-staging-api corner-staging-web

for corner_service in corner-staging-accounts corner-staging-api corner-staging-web; do
  systemctl is-active --quiet "$corner_service"
done
for corner_port in 8766 8765; do
  corner_path=/api/refresh/v1/auth/me
  if [ "$corner_port" = 8765 ]; then corner_path=/api/v1/health; fi
  corner_ready=0
  for corner_attempt in $(seq 1 30); do
    corner_code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${corner_port}${corner_path}" || true)"
    if [ "$corner_code" = 401 ]; then corner_ready=1; break; fi
    sleep 1
  done
  [ "$corner_ready" -eq 1 ] || { echo "Readiness failed on ${corner_port}" >&2; exit 1; }
done
curl --fail --silent --show-error --retry 15 --retry-delay 1 --retry-connrefused \
  http://127.0.0.1:3000/login >/dev/null
curl --fail --silent --show-error --retry 10 --retry-delay 2 --retry-connrefused \
  https://coopscorner.tech/login >/dev/null
cd /srv/corner/app
.venv-api/bin/python -c 'from corner.additional_markets import ADDITIONAL_MARKETS; print("Installed markets:", ", ".join(ADDITIONAL_MARKETS))'
git log -1 --oneline
echo 'Beta release update deployed. Live collection and billing activation unchanged.'
trap - EXIT
