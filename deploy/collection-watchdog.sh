#!/usr/bin/env bash
# Root systemd entry point. Never pulls code or changes approved release.
set -euo pipefail
cd /srv/corner/app
systemctl is-active --quiet corner-collection.service || exit 0
code=0
runuser -u corneradmin -- .venv-api/bin/python -m pipelines.collection_health || code=$?
[ "$code" -eq 10 ] || exit "$code"
# Refuse unattended recovery across a code deployment; operator batch must approve it.
runuser -u corneradmin -- .venv-api/bin/python -c 'import json,subprocess; from corner.collection_activation import APPROVAL; assert json.loads(APPROVAL.read_text())["release_commit"] == subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()'
mkdir -p /var/lib/corner-collection-recovery
stamp=/var/lib/corner-collection-recovery/attempts
now=$(date +%s)
touch "$stamp"
recent=$(awk -v cutoff="$((now-3600))" '$1>cutoff{n++} END{print n+0}' "$stamp")
[ "$recent" -lt 3 ] || { echo "Automatic recovery limit reached; run manual repair and review evidence."; exit 1; }
echo "$now" >> "$stamp"
exec 9>/srv/corner/config/collection-repair.lock
flock -n 9 || exit 0
systemctl stop corner-collection.service
runuser -u corneradmin -- .venv-api/bin/python -m pipelines.collection_recover --accept-single-request-quota-delta
install -o root -g root -m 644 /srv/corner/collection/activation/approval.json /etc/corner/collection-activation.json
systemctl start corner-collection.service
echo "Bounded recovery completed; normal worker publication resumes."
