#!/usr/bin/env bash
# Interactive private code handling; no provider requests or payment activation.
set -euo pipefail
umask 077
cd /srv/corner/app
.venv-api/bin/python -m pipelines.invitation_admin \
  --db /srv/corner/config/staging-tracker.sqlite3 --operator wonya friends
sudo systemctl start corner-backup.service
echo 'Private friend links prepared. Share one link per intended friend; keep the output private.'
echo 'New named beta invitations now print the same branded experience with beta terms.'
