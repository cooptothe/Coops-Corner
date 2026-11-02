#!/usr/bin/env bash
# Run as corneradmin after pulling the reviewed release with collection stopped.
set -euo pipefail
umask 077
cd /srv/corner/app
.venv-api/bin/python -m unittest tests.test_indexed_quote_lookup tests.test_database_catalog tests.test_performance_paths tests.test_feed_speed
sudo systemctl stop corner-staging-api
sudo -u postgres psql -X -p 5432 -d corner_staging -v ON_ERROR_STOP=1 \
  -f db/migrations/017_corner_indexed_trusted_quote_stream.sql
sudo -u postgres .venv-api/bin/python - <<'PY'
import os,sys,unittest
os.environ['CORNER_TEST_DATABASE']='1'
sys.path.insert(0,'tests')
import config
config.DB_CONFIG={'host':'/var/run/postgresql','port':5432,'dbname':'corner_staging','user':'postgres'}
suite=unittest.defaultTestLoader.loadTestsFromName('tests.test_indexed_quote_postgres')
result=unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
PY
timeout 30s .venv-api/bin/python -m pipelines.main_feed_profile
pnpm --dir web test
# Idempotent if the previously authorized full-budget policy is already deployed.
.venv-api/bin/python -m pipelines.collection_budget_upgrade --use-full-quota

stamp=$(date -u +%Y%m%dT%H%M%SZ)
previous="/srv/corner/backups/web-before-quote-timeout-$stamp"
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
echo 'Indexed quote lookup deployed. Quote timing above verifies the restricted main-feed reader.'
git log -1 --oneline
