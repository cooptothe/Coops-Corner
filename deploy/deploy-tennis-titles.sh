#!/usr/bin/env bash
set -euo pipefail
cd /srv/corner/app
.venv-api/bin/python -m unittest tests.test_database_catalog
sudo systemctl restart corner-staging-api
bash deploy/deploy-bet-displays.sh
