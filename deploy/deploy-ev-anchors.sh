#!/usr/bin/env bash
# Server-only reference policy update; no collection cadence or budget changes.
set -euo pipefail
umask 077
cd /srv/corner/app
.venv-api/bin/python -m unittest tests.test_reference_weights tests.test_all_book_references tests.test_reference_selection tests.test_soccer_reference_policy tests.test_additional_markets tests.test_live_products tests.test_devig_methods
sudo systemctl stop corner-collection-recovery.timer corner-live-odds.timer corner-live-odds.service corner-collection.service
sudo systemctl restart corner-staging-accounts corner-staging-api
ready=0
for attempt in $(seq 1 60); do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8765/api/v1/health || true)"
  if [ "$code" = 401 ]; then ready=1; break; fi
  sleep 1
done
if [ "$ready" -ne 1 ]; then
  sudo journalctl -u corner-staging-api -n 15 --no-pager
  echo 'API did not become ready; collection remains stopped for review.'
  exit 1
fi
bash deploy/repair-collection.sh
sudo systemctl enable --now corner-collection-recovery.timer corner-live-odds.timer
sudo systemctl start corner-live-odds.service
systemctl is-active corner-staging-accounts corner-staging-api corner-collection.service corner-collection-recovery.timer corner-live-odds.timer
.venv-api/bin/python - <<'PY'
import json
from corner.reference_weights import normalized_reference_weights, WEIGHT_VERSION
def weights(books, props=False):
    return {b:str(w) for b,w in normalized_reference_weights(books,'basketball_nba',player_props=props).items()}
print(json.dumps({'reference_weight_version':WEIGHT_VERSION,
    'main_matrix':weights(['pinnacle','novig','prophetx','polymarket_us','kalshi','betonlineag','draftkings','fanduel']),
    'props_matrix':weights(['fanduel','novig','prophetx','kalshi','pinnacle','draftkings'],True),
    'props_without_novig':weights(['fanduel','pinnacle','draftkings'],True),
    'budget_policy_unchanged':True}))
PY
git log -1 --oneline
echo 'Positive EV anchors deployed. Reload the browser.'
