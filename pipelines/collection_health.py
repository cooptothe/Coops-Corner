"""Private local diagnosis; never requests odds or changes accounting."""
import json
import sqlite3
import sys
import time
from corner.collection_activation import STATE

def diagnose(db, now):
    paused = db.execute('SELECT paused FROM controls WHERE id=1').fetchone()[0]
    unknown = db.execute("SELECT started FROM attempts WHERE state='unknown'").fetchall()
    inventory_rows = db.execute("SELECT started,state FROM quota_inventory WHERE state!='settled'").fetchall()
    inventory = len(inventory_rows)
    pending = db.execute('SELECT count(*) FROM publication_outbox WHERE published_at IS NULL').fetchone()[0]
    isolated = 0
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='publication_failures'").fetchone():
        isolated = db.execute('SELECT count(*) FROM publication_failures WHERE quarantined=1').fetchone()[0]
    odds_candidate = len(unknown)==1 and not inventory and now-unknown[0][0]>=125
    inventory_candidate = (not unknown and inventory==1 and inventory_rows[0][1]=='unknown'
                           and now-inventory_rows[0][0]>=125)
    repairable = bool(paused and (odds_candidate or inventory_candidate))
    return {'paused':bool(paused),'unknown_requests':len(unknown),'unresolved_inventory':inventory,
            'pending_publications':pending,'isolated_publications':isolated,
            'bounded_recovery_candidate':repairable,'paid_odds_calls':0}

def main():
    with sqlite3.connect(STATE.resolve().as_uri()+'?mode=ro',uri=True,timeout=5) as db:
        result=diagnose(db,time.time())
    print(json.dumps(result))
    return 10 if result['bounded_recovery_candidate'] else 0

if __name__=='__main__':
    sys.exit(main())
