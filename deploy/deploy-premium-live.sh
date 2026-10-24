#!/usr/bin/env bash
# Run as corneradmin after a clean fast-forward pull. No secrets printed.
set -euo pipefail
umask 077
cd /srv/corner/app

# Tests precede any web stop. Existing site stays available if these fail.
.venv-api/bin/python -m unittest \
  tests.test_live_odds tests.test_live_products tests.test_live_game_status tests.test_collection_adapters \
  tests.test_collection_runner tests.test_collection_live \
  tests.test_collection_recovery tests.test_collection_health \
  tests.test_collection_maintenance tests.test_scheduled_only \
  tests.test_product_api tests.test_prop_decimal_output tests.test_devig_methods \
  tests.test_performance_paths tests.test_market_compression tests.test_prop_exchange_policy tests.test_all_book_collection tests.test_exchange_companions tests.test_zero_charge_retry
.venv-api/bin/python -c 'import httpx; from pipelines.live_odds_client import client'
(cd web && pnpm test)

sudo install -d -o corneradmin -g corneradmin -m 700 /srv/corner/config/live-queue
.venv-api/bin/python - <<'PY'
import json
import os
from pathlib import Path
import secrets
from dotenv import load_dotenv
load_dotenv('/srv/corner/config/staging.env',override=True)
from pipelines.accounts import AuthContext
from pipelines.collection_publication import MainPublisher
from corner.live_odds import CONFIG
user=AuthContext().store.user_by_key('wonya')
if not user or user['username'].casefold()!='wonya':
    raise SystemExit('The wonya account must exist before premium live activation.')
existing=json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
if existing and existing.get('premium_username')!='wonya':
    raise SystemExit('Unexpected live configuration; stopped.')
old_token=existing.get('cron_token')
body={'enabled':True,'premium_username':'wonya',
      'cron_token':old_token if isinstance(old_token,str) and len(old_token)>=40 else secrets.token_urlsafe(48)}
MainPublisher._atomic(CONFIG,(json.dumps(body)+'\n').encode())
os.chmod(CONFIG,0o600)
print('wonya-only Premium configured. Live uses existing main pool: 500,000/month and 20,000/day maximum. No provider calls made by configuration.')
PY

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
previous="/srv/corner/backups/web-before-premium-live-$stamp"
failed="/srv/corner/backups/web-failed-premium-live-$stamp"
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

sudo install -d -o root -g root -m 755 /etc/systemd/system/corner-staging-api.service.d
printf '[Service]\nReadWritePaths=/srv/corner/config/live-queue\n' |
  sudo tee /etc/systemd/system/corner-staging-api.service.d/live-queue.conf >/dev/null
sudo install -o root -g root -m 644 \
  deploy/corner-live-odds.service deploy/corner-live-odds.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart corner-staging-accounts corner-staging-api

api_ready=0
for attempt in $(seq 1 30); do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8765/api/v1/health || true)"
  if [ "$code" = 401 ]; then api_ready=1; break; fi
  sleep 1
done
[ "$api_ready" -eq 1 ] || { echo 'Tools API readiness failed.'; exit 1; }

# Same key, same worker, same main pool and protected reserve. Never reset ledger.
bash deploy/repair-collection.sh
sudo systemctl enable --now corner-collection-recovery.timer corner-live-odds.timer
live_queued=0
for attempt in 1 2 3; do
  if sudo systemctl start corner-live-odds.service; then live_queued=1; break; fi
  echo "Live scheduler not ready; bounded local queue retry $attempt/3."
  sleep 2
done
[ "$live_queued" -eq 1 ] || {
  sudo journalctl -u corner-live-odds.service -n 12 --no-pager
  echo 'Live queue failed; pregame collection remains running. No ledger reset performed.'
  exit 1
}

curl --fail --silent --show-error --retry 10 --retry-connrefused --retry-delay 2 \
  https://coopscorner.tech/login >/dev/null
code="$(curl -s -o /dev/null -w '%{http_code}' https://coopscorner.tech/api/v1/live-stoppages)"
[ "$code" = 401 ] || { echo 'Anonymous live route check failed.'; exit 1; }
systemctl is-active corner-staging-web corner-staging-api corner-collection.service \
  corner-collection-recovery.timer corner-live-odds.timer
sudo journalctl -u corner-live-odds.service -n 4 --no-pager
.venv-api/bin/python -m pipelines.live_odds_status --wait-seconds 75

git log -1 --oneline
echo 'Shared feed layouts and premium live collection deployed. Sign in as wonya and turn Live on in EV, Arbitrage, or Middles. Market-status and live-price coverage still require observation on the real provider.'
