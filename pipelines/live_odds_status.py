"""Read-only live collection evidence. Never requests provider odds or resets state."""
from __future__ import annotations
from contextlib import closing
from datetime import datetime, timezone
import argparse
import time
import json
import sqlite3
from corner import live_odds
from corner.collection_activation import STATE
from corner.collection_policy import open_now

def status(path=STATE, now=None):
    now=now or datetime.now(timezone.utc)
    data=live_odds.feed(path,now)
    result={'configured':bool(live_odds.config()),'window_open':open_now(now),
        'cron_marker_fresh':live_odds.enabled(now),'state':data['state'],
        'live_games':len(data['events']),'active_markets':sum(e['active_market_count'] for e in data['events']),
        'live_credits_accounted':data.get('live_credits_accounted',0),
        'daily_credits_accounted':data.get('live_daily_credits_accounted',0),
        'monthly_subcap':live_odds.MONTHLY_CAP,'daily_subcap':live_odds.DAILY_CAP,
        'provider_calls_by_check':0,'captures':[],
        'collection_intervals_seconds':data.get('collection_intervals_seconds'),
        'live_pacing':data.get('live_pacing')}
    inventory={}
    cooldowns={}
    if path.is_file():
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='runner_inventory'").fetchone():
                row=db.execute('SELECT payload FROM runner_inventory WHERE id=1').fetchone()
                if row and row[0]:inventory=json.loads(row[0])
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='collection_retry_cooldowns'").fetchone():
                cooldowns=dict(db.execute('SELECT job_key,retry_after FROM collection_retry_cooldowns WHERE retry_after>?',(now.timestamp(),)))
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='live_captures'").fetchone()
            if exists:
                result['captures']=[{'sport':s,'group':g,'age_seconds':round(now.timestamp()-at,1),
                    'events':len(json.loads(raw))} for s,g,at,raw in db.execute('SELECT sport,book_group,captured,payload FROM live_captures ORDER BY sport,book_group')]
    result['fresh_capture_groups']=sum(0<=c['age_seconds']<=90 for c in result['captures'])
    planned=live_odds.jobs(now,inventory)
    fresh={(c['sport'],c['group']) for c in result['captures'] if 0<=c['age_seconds']<=90}
    result['expected_live_groups']=len(planned)
    result['missing_or_stale_groups']=[{'sport':j.sport,'group':j.group,**({'cooldown_until_utc':datetime.fromtimestamp(cooldowns[j.key],timezone.utc).isoformat()} if j.key in cooldowns else {})} for j in planned if (j.sport,j.group) not in fresh]
    result['collection_verified']=bool(planned and not result['missing_or_stale_groups'] and result['state']=='ready')
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wait-seconds',type=int,default=0,choices=range(0,91))
    args=parser.parse_args()
    deadline=time.monotonic()+args.wait_seconds
    while True:
        result=status()
        if (result['collection_verified'] or not result['window_open'] or
            not result['expected_live_groups'] or time.monotonic()>=deadline):break
        time.sleep(min(3,max(0,deadline-time.monotonic())))
    print(json.dumps(result,indent=2))
    if result['window_open'] and (not result['configured'] or not result['cron_marker_fresh'] or result['state'] in ('paused','live_budget_limit','live_budget_pacing')):
        print('Live scheduling is blocked: inspect configuration, cron freshness, collector state and budget caps.')
        return 1
    if result['expected_live_groups'] and not result['collection_verified']:
        print('Live collection is not yet verified: inspect the reported state and capture groups.')
        return 1
    if not result['expected_live_groups']:
        print('No eligible in-play scopes in the current window; fresh live odds are not proved by this check.')
    return 0

if __name__=='__main__':raise SystemExit(main())
