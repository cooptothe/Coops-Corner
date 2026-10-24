"""Inspect quarantines; release only verified automatic exchange-lay mismatches.

No HTTP requests, accounting changes, historical replay, or quote re-dating.
"""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from corner.collection_policy import EXCHANGE, SPORTS, Job
from corner.collection_quota import LiveGovernor
from corner.credit_governor import Governor, Refused
from corner.featured_markets import normalize_featured_payload


def eligible(db, row):
    if row['code'] != 'market_mismatch':
        return False
    try:
        detail = json.loads(row['detail'])
        job = Job('main', detail['sport'], 'exchange', EXCHANGE, ('h2h','spreads','totals'))
        job.validate()
        if detail['kind'] != 'main' or detail.get('event_id') or job.key != row['job_key'] or detail['http_status'] != 200:
            return False
        payload = detail['payload']
        if not isinstance(payload, list) or not payload:
            return False
        if not any(m.get('key') == 'h2h_lay' for e in payload for b in e.get('bookmakers',[]) for m in b.get('markets',[])):
            return False
        attempt = db.execute('SELECT * FROM attempts WHERE token=? AND job_key=?', (row['token'],job.key)).fetchone()
        if not attempt or attempt['state'] != 'settled' or attempt['actual'] != detail['actual'] or not 0 <= attempt['actual'] <= attempt['reserved']:
            return False
        evidence = [json.loads(r[0]) for r in db.execute("SELECT detail FROM quota_audit WHERE action='odds-response'")]
        if not any(e.get('token') == row['token'] and e.get('charge_verified') is True and e.get('actual') == attempt['actual'] and e.get('http_status') == 200 for e in evidence):
            return False
        captured = datetime.fromtimestamp(row['created'],timezone.utc)
        # Validate on a disposable copy at the original timestamp. Never publish
        # these old quotes to the actual ledger or change their capture times.
        with closing(sqlite3.connect(':memory:')) as scratch:
            scratch.row_factory = sqlite3.Row
            for table in ('snapshots','clv_scopes'):
                scratch.execute(db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()[0])
            validator = Governor.__new__(Governor)
            validator._publish(scratch,job,payload,captured)
        snapshot = normalize_featured_payload(json.dumps(payload).encode(),received_at=captured)
        return bool(snapshot.quotes)
    except (ValueError, TypeError, KeyError, AttributeError, sqlite3.Error):
        return False


def describe(db,row):
    detail=json.loads(row['detail'])
    result={'kind':detail.get('kind'),'sport':detail.get('sport'),'code':row['code'],
            'settled_charge':detail.get('actual')}
    sports=set(SPORTS)
    sports.update(r[0] for r in db.execute('SELECT DISTINCT sport FROM live_captures'))
    for sport in sports:
        for kind in ('main','live'):
            for group in ('standard','exchange'):
                if Job(kind,sport,group,(),()).key==row['job_key']:
                    result.update(kind=kind,sport=sport,group=group)
    audits=[(r[0],json.loads(r[1])) for r in db.execute("SELECT action,detail FROM quota_audit WHERE action IN ('request-failed','odds-response') AND json_extract(detail,'$.token')=?",(row['token'],))]
    for action,item in audits:
        if action=='request-failed':
            result.update(phase=item.get('phase'),error_type=item.get('error_type'))
            if not result['kind']:result.update(kind=item.get('kind'),sport=item.get('sport'))
        else:
            result.update(http_status=item.get('http_status'),charge_verified=item.get('charge_verified'),quota_check_failed=bool(item.get('reason')))
    return result


def repair(path, *, apply=False, now=None):
    now = now or datetime.now(timezone.utc)
    path = Path(path).resolve(strict=True)
    with closing(sqlite3.connect(path.as_uri()+('?mode=rw' if apply else '?mode=ro'),uri=True,isolation_level=None,timeout=10)) as db:
        db.row_factory = sqlite3.Row
        # Eligibility checks run against one consistent read transaction.
        db.execute('BEGIN')
        rows = db.execute('SELECT * FROM collection_quarantine ORDER BY created').fetchall()
        candidates = [r for r in rows if eligible(db,r)]
        db.execute('COMMIT')
        released = 0
        if apply:
            db.execute('BEGIN IMMEDIATE')
            try:
                guard = LiveGovernor.__new__(LiveGovernor)
                guard._offline(db,now)
                if db.execute("SELECT 1 FROM attempts WHERE state='unknown' UNION ALL SELECT 1 FROM quota_inventory WHERE state='unknown'").fetchone():
                    raise Refused('Reconcile uncertain requests before exchange repair')
                db.execute('CREATE TABLE IF NOT EXISTS exchange_quarantine_archive(job_key TEXT,token TEXT,created REAL,code TEXT,detail TEXT,released REAL,PRIMARY KEY(job_key,token))')
                for row in candidates:
                    current = db.execute('SELECT * FROM collection_quarantine WHERE job_key=?',(row['job_key'],)).fetchone()
                    if current is None or tuple(current) != tuple(row):
                        raise Refused('Quarantine changed during review')
                    db.execute('INSERT OR IGNORE INTO exchange_quarantine_archive VALUES(?,?,?,?,?,?)',tuple(row)+(now.timestamp(),))
                    db.execute('DELETE FROM collection_quarantine WHERE job_key=? AND token=?',(row['job_key'],row['token']))
                    db.execute("UPDATE jobs SET state='idle',last_error='' WHERE key=?",(row['job_key'],))
                    guard._audit(db,now,'exchange-lay-repair','Automatic h2h_lay companion validated; original quarantine archived',{'job_key':row['job_key'],'token':row['token']})
                    released += 1
                db.execute('COMMIT')
            except BaseException:
                db.execute('ROLLBACK')
                raise
        return {'result':'exchange_repair_applied' if apply else 'exchange_repair_preview',
                'provider_calls':0,'eligible_scopes':len(candidates),'released_scopes':released,
                'quarantines_by_code':dict(Counter(r['code'] for r in rows)),
                'remaining_scopes':[describe(db,r) for r in rows if not apply or r not in candidates]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state',default='/srv/corner/config/collection-live.sqlite3')
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if args.apply:
        from corner.collection_maintenance import maintenance_lock
        with maintenance_lock(exclusive=True,timeout=60):
            print(json.dumps(repair(args.state,apply=True)))
    else:
        print(json.dumps(repair(args.state)))


if __name__=='__main__':main()
