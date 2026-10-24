"""Read-only returned-book and credit audit. Never imports credentials or calls a provider."""
import argparse
from contextlib import closing
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from corner.collection_policy import ALL_BOOKS, EXCHANGE, PROP_STANDARD, PROP_EXCHANGE, POOLS, TOTAL, PROTECTED


def iso(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat() if stamp is not None else None


def report(path, *, now=None, dashboard_used=None):
    now = now or datetime.now(timezone.utc)
    stamp = now.timestamp()
    path = Path(path)
    if not path.is_file(): raise ValueError('Existing collection ledger required')
    # mode=ro plus query_only: this cannot initialize, reset or repair collection.
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=5)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        observed = defaultdict(lambda: {'retained_scopes':0, 'fresh_scopes':0, 'latest_capture':None})
        def record(kind, book, captured, fresh, outcomes):
            if not outcomes: return
            row = observed[(kind, book)]
            row['retained_scopes'] += 1
            row['fresh_scopes'] += int(fresh)
            row['latest_capture'] = max(row['latest_capture'] or 0, captured)
        for row in db.execute('SELECT kind,book,source_at,captured_at,expires_at,starts_at,payload FROM snapshots'):
            payload = json.loads(row['payload'])
            fresh = row['expires_at'] > stamp and row['starts_at'] > stamp and -5 <= stamp-row['source_at'] < 1800 and -5 <= stamp-row['captured_at'] < 1800
            record(row['kind'],row['book'],row['captured_at'],fresh,payload.get('market',{}).get('outcomes'))
        if 'live_captures' in tables:
            for row in db.execute('SELECT captured,payload FROM live_captures'):
                for event in json.loads(row['payload']):
                    for book in event.get('bookmakers',[]):
                        for market in book.get('markets',[]):
                            text = market.get('last_update') or book.get('last_update')
                            try: source = datetime.fromisoformat(text.replace('Z','+00:00')).timestamp()
                            except (ValueError,TypeError,AttributeError): source = 0
                            fresh = -5 <= stamp-row['captured'] < 90 and -5 <= stamp-source < 90 and not market.get('suspended',False)
                            record('live',book['key'],row['captured'],fresh,market.get('outcomes'))
        cycle = db.execute('SELECT * FROM cycles WHERE starts<=? AND ends>? ORDER BY starts DESC LIMIT 1',(stamp,stamp)).fetchone()
        budget = {'pool_caps':POOLS,'protected_reserve':PROTECTED,'monthly_total':TOTAL}
        if cycle:
            binding = db.execute('SELECT used,checked FROM quota_bindings WHERE cycle_id=?',(cycle['id'],)).fetchone() if 'quota_bindings' in tables else None
            used = max(binding['used'] if binding else 0,dashboard_used or 0)
            unresolved = db.execute("SELECT count(*) FROM attempts WHERE cycle_id=? AND state!='settled'",(cycle['id'],)).fetchone()[0]
            spent = dict(db.execute('SELECT pool,coalesce(sum(coalesce(actual,reserved)),0) FROM attempts WHERE cycle_id=? GROUP BY pool',(cycle['id'],)))
            recent = db.execute("SELECT coalesce(sum(actual),0) FROM attempts WHERE cycle_id=? AND state='settled' AND finished>=?",(cycle['id'],stamp-86400)).fetchone()[0]
            projected = used + recent * max(0,cycle['ends']-stamp)/86400
            budget.update(cycle_id=cycle['id'],provider_used_known=used,quota_checked_at=iso(binding['checked']) if binding else None,
                provider_remaining_known=TOTAL-used,usable_above_reserve=max(0,TOTAL-used-PROTECTED),
                ledger_attempt_spend_including_reserved=spent,settled_credits_last_24h=recent,
                unresolved_requests=unresolved,next_reset_utc=iso(cycle['ends']),
                remaining_at_same_24h_burn_rate=None if unresolved or recent==0 else int(TOTAL-projected),
                rate_forecast_note='Scenario only: the previous 24h can include outages, missing markets and a different event slate; reserve/pool gates remain authoritative.')
        else: budget['cycle_status']='No current explicitly bound cycle; no activation performed'
        paused = db.execute('SELECT paused FROM controls WHERE id=1').fetchone()[0]
        pending = db.execute('SELECT count(*) FROM publication_outbox WHERE published_at IS NULL').fetchone()[0]
        quarantined = db.execute('SELECT count(*) FROM collection_quarantine').fetchone()[0] if 'collection_quarantine' in tables else 0
    allowed = {'main':set(ALL_BOOKS),'additional':set(ALL_BOOKS),'props':set(PROP_STANDARD+PROP_EXCHANGE),'live':set(ALL_BOOKS)}
    books=[]
    for book in ALL_BOOKS:
        scopes={}
        for kind in allowed:
            data=dict(observed[(kind,book)])
            data['latest_capture_utc']=iso(data.pop('latest_capture'))
            data['requested']=book in allowed[kind]
            data['status']='excluded_from_props' if not data['requested'] else 'fresh_returned_quotes' if data['fresh_scopes'] else 'retained_but_not_fresh' if data['retained_scopes'] else 'no_quotes_in_current_retained_store'
            scopes[kind]=data
        books.append({'book':book,'exchange':book in EXCHANGE,'scopes':scopes})
    return {'checked_at_utc':now.isoformat(),'provider_calls':0,'collector_modified':False,
        'requested_exchange_keys':{kind:sorted(values & set(EXCHANGE)) for kind,values in allowed.items()},
        'collector':{'paused':bool(paused),'pending_publications':pending,'quarantined_scopes':quarantined},
        'budget':budget,'books':books,
        'scope':'Current retained provider evidence only. Requested does not guarantee provider coverage or a positive-EV opportunity. No new odds fetched.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state',default='/srv/corner/config/collection-live.sqlite3')
    parser.add_argument('--dashboard-used',type=int)
    args=parser.parse_args()
    if args.dashboard_used is not None and not 0<=args.dashboard_used<=TOTAL:parser.error('Invalid quota total')
    data=report(args.state,dashboard_used=args.dashboard_used)
    print(json.dumps({k:v for k,v in data.items() if k!='books'},sort_keys=True))
    for book in data['books']: print(json.dumps(book,sort_keys=True))


if __name__=='__main__':main()
