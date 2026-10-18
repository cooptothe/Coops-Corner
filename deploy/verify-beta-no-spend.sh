#!/usr/bin/env bash
# No wallet transfer, paid odds, billing activation, collector installation, or reboot.
set -euo pipefail
umask 077
cd /srv/corner/app
mkdir -p retained/release-evidence

.venv-api/bin/python - <<'PY'
import json
from pathlib import Path
import subprocess
from dotenv import dotenv_values,load_dotenv

stage=dotenv_values('/srv/corner/config/staging.env')
assert stage.get('CORNER_PRIVATE_BETA')=='1','Private beta guard is not enabled'
assert stage.get('CORNER_REFRESH_DAILY_CAP')=='0','Manual refresh cap is not zero'
assert not stage.get('ODDS_API_KEY'),'Unexpected staging provider key; inspect privately'
collection=Path('/srv/corner/config/collection.env')
assert collection.exists(),'Dedicated disabled collector configuration is missing'
worker=dotenv_values(collection)
assert worker.get('CORNER_COLLECTION_ENABLED')=='0','Collector is not configured disabled'
assert not worker.get('ODDS_API_KEY'),'Worker has a provider key; inspect privately before continuing'
load_dotenv('/srv/corner/config/staging.env',override=True)
from corner.billing_config import checkout_config
assert checkout_config() is None,'Checkout is enabled; stop and review the no-spend stage'
from pipelines.tracker_clv import fetch_close
fetch_close('00000000-0000-4000-8000-000000000000','h2h')
listeners=subprocess.check_output(['ss','-H','-lnt'],text=True)
private_ports={3000,8765,8766,5432};seen=set()
for line in listeners.splitlines():
    local=line.split()[3]
    host,_,port=local.rpartition(':')
    if port.isdigit() and int(port) in private_ports:
        assert host in ('127.0.0.1','[::1]','::1'), 'An internal application port is publicly bound'
        seen.add(int(port))
assert seen==private_ports, 'An expected internal service port is missing'
print(json.dumps({'internal_ports_loopback_only':True,'staging_manual_spend_disabled':True,'collector_disabled':True,'provider_keys_absent':True,'checkout_disabled':True,'readonly_closing_query':'passed'}))
PY

while read -r corner_unit _; do
  case "$corner_unit" in
    corner*collect*.service)
      if systemctl is-active --quiet "$corner_unit"; then
        echo "Collector service is active; stopped no-spend acceptance." >&2
        exit 1
      fi
      ;;
  esac
done < <(systemctl list-unit-files --type=service --no-legend --no-pager)

.venv-api/bin/python -m unittest \
  tests.test_release_probe tests.test_beta_access tests.test_trial_enforcement \
  tests.test_billing_checkout tests.test_beta_invoices tests.test_beta_billing \
  tests.test_beta_receiving tests.test_beta_terms tests.test_billing_offer \
  tests.test_accounts tests.test_props_dfs_references tests.test_clv_coverage
.venv-api/bin/python -m pipelines.beta_rehearsal \
  --output retained/release-evidence/offline-acceptance.json
.venv-api/bin/python -m pipelines.release_probe \
  --base-url https://coopscorner.tech --samples 20 --concurrency 5 \
  --output retained/release-evidence/public-readiness.json

for corner_service in corner-staging-accounts corner-staging-api corner-staging-web corner-backup.timer; do
  systemctl is-active --quiet "$corner_service"
done
sudo systemctl start corner-backup.service
[ "$(systemctl show corner-backup.service --property=Result --value)" = success ]
[ "$(systemctl show corner-backup.service --property=ExecMainStatus --value)" = 0 ]
sudo /usr/bin/python3 /usr/local/lib/corner-backup/latest-billing-checkpoint.py

sudo install -o root -g root -m 644 deploy/corner-readiness.service deploy/corner-readiness.timer /etc/systemd/system/
sudo systemd-analyze verify /etc/systemd/system/corner-readiness.service /etc/systemd/system/corner-readiness.timer
sudo systemctl daemon-reload
sudo systemctl start corner-readiness.service
sudo systemctl enable --now corner-readiness.timer
systemctl is-active corner-readiness.timer corner-backup.timer
systemctl list-timers corner-readiness.timer corner-backup.timer --no-pager

echo 'No-spend staging acceptance passed. No paid collection, payable checkout, wallet transfers or reboot were enabled.'
echo 'Pending: funded receive tests, live provider/quota smoke, authenticated VPS load, physical mobile installation, and reboot/rollback.'
git log -1 --oneline
