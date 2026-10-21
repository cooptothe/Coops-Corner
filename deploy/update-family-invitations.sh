#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /srv/corner/app
.venv-api/bin/python -m unittest tests.test_family_membership tests.test_friend_membership tests.test_invitation_welcome tests.test_beta_access tests.test_trial_enforcement tests.test_accounts tests.test_billing_offer tests.test_beta_invoices tests.test_beta_billing
# Existing tested deployment rebuilds web and renews the commit-specific
# collector approval, preserving all charges, captures and quarantines.
bash deploy/update-expanded-books.sh
sudo install -o root -g root -m 644 deploy/backup/billing_checkpoint.py /usr/local/lib/corner-backup/billing_checkpoint.py
.venv-api/bin/python - <<'PY'
from dotenv import load_dotenv
from pathlib import Path
from corner.tracker_store import TrackerStore
from pipelines.family_invitations import prepare
load_dotenv('/srv/corner/config/staging.env',override=True)
from pipelines.accounts import DB_PATH
assert DB_PATH.is_file()
store=TrackerStore(DB_PATH)
try:
    records=prepare(store,Path('/srv/corner/config/brother-invitations.json'))
finally:store.close()
for number,record in enumerate(records,1):
    print(f"Brother {number} private link: https://coopscorner.tech/invite#{record['token']}")
print('Share one link privately with each brother. They choose their usernames at signup.')
print('Redeem within seven days. Membership: permanently free, standard and live when available; no beta/friend place consumed.')
PY
