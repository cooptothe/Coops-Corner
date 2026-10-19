#!/usr/bin/env bash
# Operator-authorized reboot only; rerun this same script after reconnecting.
set -euo pipefail
umask 077
cd /srv/corner/app
mkdir -p retained/release-evidence
corner_phase="$(.venv-api/bin/python -m pipelines.recovery_probe phase)"
case "$corner_phase" in
  prepare)
    .venv-api/bin/python -m unittest tests.test_recovery_probe tests.test_release_probe
    sudo systemctl start corner-backup.service
    test "$(systemctl show corner-backup.service --property=Result --value)" = success
    test "$(systemctl show corner-backup.service --property=ExecMainStatus --value)" = 0
    .venv-api/bin/python -m pipelines.recovery_probe artifact
    .venv-api/bin/python -m pipelines.recovery_probe prepare
    echo 'Checkpoint, isolated artifact recovery, and boot preflight passed.'
    echo 'Rebooting now. Reconnect, then rerun: bash deploy/verify-recovery-no-spend.sh'
    sudo systemctl reboot
    ;;
  reboot)
    echo 'Baseline exists but this host has not rebooted. Re-run prepare checks without replacing evidence.'
    .venv-api/bin/python - <<'PYCHECK'
import json
from pipelines.recovery_probe import BEFORE,state
before=json.loads(BEFORE.read_text(encoding='utf-8'))
current=state()
assert before['release_commit']==current['release_commit'],'Release changed; do not reboot with stale evidence'
assert before['private_fingerprints']==current['private_fingerprints'],'Configuration changed; review privately'
print('Current disabled configuration and release still match the baseline.')
PYCHECK
    sudo systemctl reboot
    ;;
  verify)
    corner_ready=0
    for corner_attempt in $(seq 1 60); do
      if .venv-api/bin/python -m pipelines.recovery_probe verify > retained/release-evidence/reboot-last-check.log 2>&1; then
        corner_ready=1
        break
      fi
      sleep 1
    done
    cat retained/release-evidence/reboot-last-check.log
    test "$corner_ready" -eq 1
    .venv-api/bin/python -m pipelines.release_probe --samples 20 --concurrency 5 \
      --output retained/release-evidence/public-after-reboot.json
    systemctl is-active corner-staging-accounts corner-staging-api corner-staging-web caddy postgresql corner-backup.timer corner-readiness.timer
    git log -1 --oneline
    echo 'Reboot continuity and HTTPS passed; collector and checkout remain disabled.'
    echo 'Web artifact recovery is separate from full prior-release/backend/database rollback, which remains unverified.'
    ;;
  *) echo 'Unknown recovery phase; stopped.' >&2; exit 1 ;;
esac
