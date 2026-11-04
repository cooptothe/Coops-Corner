#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /srv/corner/app
.venv-api/bin/python -m unittest tests.test_storage_retention tests.test_deadline_collection tests.test_collection_runner tests.test_collection_recovery tests.test_collection_maintenance
sudo install -d -o root -g root -m 755 /usr/local/lib/corner-storage
sudo install -o root -g root -m 644 deploy/storage/corner_storage.py /usr/local/lib/corner-storage/corner_storage.py
sudo install -o root -g root -m 644 deploy/corner-storage.service deploy/corner-storage.timer /etc/systemd/system/
sudo install -d -m 755 /etc/systemd/system/corner-collection.service.d
printf '[Service]\nEnvironment=CORNER_STORAGE_TARGET_PERCENT=50\n' | sudo tee /etc/systemd/system/corner-collection.service.d/storage.conf >/dev/null
sudo systemctl daemon-reload
# Force the first pass, even if a previous maintenance pass freed some space.
sudo /usr/bin/python3 /usr/local/lib/corner-storage/corner_storage.py --apply --force --leave-collection-stopped
sudo systemctl enable --now corner-storage.timer
sudo systemctl start corner-staging-accounts corner-staging-api
ready=0
for attempt in $(seq 1 90); do
 code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 http://127.0.0.1:8765/api/v1/health || true)
 if [ "$code" = 401 ]; then ready=1; break; fi
 sleep 1
done
[ "$ready" -eq 1 ] || { sudo journalctl -u corner-staging-api -n 25 --no-pager; exit 1; }
bash deploy/repair-collection.sh
sudo systemctl start corner-collection-recovery.timer corner-live-odds.timer
df -h /
systemctl is-active corner-collection.service corner-storage.timer corner-collection-recovery.timer
.venv-api/bin/python -m pipelines.collection_health || [ "$?" -eq 10 ]
echo 'Cleanup complete. Completed backups, accounts, logged bets and quota accounting preserved.'
git log -1 --oneline
