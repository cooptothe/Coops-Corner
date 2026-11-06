#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /srv/corner/app
.venv-api/bin/python -m unittest \
 tests.test_beta_access tests.test_invitation_welcome tests.test_friend_membership \
 tests.test_family_membership tests.test_friend_codes tests.test_beta_codes \
 tests.test_beta_terms tests.test_beta_billing tests.test_beta_invoices tests.test_beta_receiving

sudo systemctl stop corner-staging-accounts
trap 'sudo systemctl start corner-staging-accounts' EXIT
.venv-api/bin/python deploy/make-invitations-permanent.py
sudo systemctl start corner-staging-accounts
trap - EXIT
bash deploy/deploy-bet-displays.sh
echo 'Existing unclaimed, non-revoked codes now have no expiry. Used/revoked codes remain closed.'
