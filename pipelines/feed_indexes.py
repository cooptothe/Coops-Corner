"""Offline query indexes for large retained stores. No deletions or provider IO."""
import json
import os
import sqlite3
import subprocess
import shutil
from contextlib import closing
from corner.collection_activation import STATE,ROOT
from corner.collection_maintenance import maintenance_lock

INDEXES=(
    ('collection_pending_outbox', 'CREATE INDEX IF NOT EXISTS collection_pending_outbox ON publication_outbox(published_at) WHERE published_at IS NULL'),
    ('collection_props_close_lookup', 'CREATE INDEX IF NOT EXISTS collection_props_close_lookup ON clv_scopes(kind,event_id,market,captured_at)'),
)

def install(db):
    for name,sql in INDEXES:
        print(json.dumps({'creating_index':name}),flush=True)
        db.execute(sql)
    db.commit()

def main():
    os.umask(0o077)
    if os.name!='posix' or os.getcwd()!=str(ROOT) or not STATE.is_file():
        raise SystemExit('Run on the VPS from the application directory with the existing ledger.')
    state=subprocess.run(['systemctl','is-active','--quiet','corner-collection.service'],timeout=10)
    if state.returncode not in (3,4):raise SystemExit('Stop collection before creating offline indexes.')
    with maintenance_lock(exclusive=True,timeout=30):
        with closing(sqlite3.connect(STATE,timeout=30)) as db:
            existing={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='index'")}
            if any(name not in existing for name,_ in INDEXES):
                required=max(5*1024**3,STATE.stat().st_size//2)
                if shutil.disk_usage(STATE.parent).free < required:
                    raise SystemExit('Insufficient working space for offline indexes; no records changed.')
            install(db)
    print(json.dumps({'result':'feed_indexes_ready','provider_calls':0,'records_deleted':0}))

if __name__=='__main__':main()
