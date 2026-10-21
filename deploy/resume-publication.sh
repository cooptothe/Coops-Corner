#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /srv/corner/app
if systemctl is-active --quiet corner-collection.service; then
  echo "Stop collector before replaying saved publications."; exit 1
fi
.venv-api/bin/python -m unittest tests.test_duplicate_alternates tests.test_featured_markets tests.test_additional_markets tests.test_collection_runner tests.test_all_book_collection

# Replay the exact retained records through the restricted writer. Do not edit
# captures, acknowledge outbox items, change charges or call the odds provider.
.venv-api/bin/python - <<'PY'
import json
import sqlite3
from dotenv import dotenv_values
from corner.collection_activation import STATE, RETAINED
from corner.collection_maintenance import maintenance_lock
from pipelines.collection_live import writer
from pipelines.collection_publication import MainPublisher

config = dotenv_values('/srv/corner/config/collection.env')
with maintenance_lock(exclusive=True, timeout=60):
    with sqlite3.connect(STATE.resolve().as_uri()+'?mode=ro', uri=True) as db:
        rows = db.execute('SELECT token,payload FROM publication_outbox WHERE published_at IS NULL ORDER BY rowid').fetchall()
    publisher = MainPublisher(RETAINED, lambda: writer(config))
    for token, payload in rows:
        try:
            publisher(token, json.loads(payload))
        except Exception as error:
            message = str(error)
            for value in config.values():
                if value and len(value) >= 6: message = message.replace(value, '[redacted]')
            print(json.dumps({'result':'saved_publication_failed','error_type':type(error).__name__,
                              'sqlstate':getattr(error,'pgcode',None),'message':message[:1500]}))
            raise SystemExit(1)
    print(json.dumps({'result':'saved_publications_replayed','captures':len(rows),'provider_calls':0,
                      'acknowledgements_changed':False,'ledger_charges_changed':False}))
PY

.venv-api/bin/python -m pipelines.collection_recover --accept-single-request-quota-delta --enable-all-books
sudo install -o root -g root -m 644 /srv/corner/collection/activation/approval.json /etc/corner/collection-activation.json
sudo systemctl start corner-collection.service
systemctl is-active corner-collection.service
sleep 8
.venv-api/bin/python -m pipelines.collection_admin status --state /srv/corner/config/collection-live.sqlite3
sudo journalctl -u corner-collection.service -n 12 --no-pager
echo "Publication fix installed; inspect worker state above for successful publication and collection."
