"""Initialize the first funded ledger PAUSED; no odds requests or recurring activation."""
import argparse
from contextlib import closing
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re
import sqlite3
from corner.collection_policy import POOLS,TOTAL,PROTECTED,BUDGET_VERSION,parse
from corner.collection_quota import LiveGovernor,key_identity
from corner.collection_activation import STATE,RETAINED
from corner.collection_maintenance import maintenance_lock
from pipelines import collection_onboarding as onboarding
from pipelines.collection_live import writer
from pipelines.recovery_probe import write_private

class SetupError(ValueError):pass

def initialize(path,key,quota,now,commit):
    path=Path(path)
    if path.name!='collection-live.sqlite3' or path.exists() or path.is_symlink():
        raise SetupError('New dedicated live ledger required; never overwrite existing accounting.')
    start,end=onboarding.quota_window(now)
    if (quota.get('result')!='verified_disabled_setup' or quota.get('quota_total')!=TOTAL
        or quota.get('provider_used')!=0 or quota.get('provider_remaining')!=TOTAL
        or quota.get('last_request_charge')!=0 or quota.get('quota_cycle_start_utc')!=start
        or quota.get('next_quota_reset_utc')!=end
        or not 0<=(now-parse(quota['checked_at_utc'])).total_seconds()<60):
        raise SetupError('Fresh verified zero-usage quota required. Allocate nonzero prior usage separately.')
    if not re.fullmatch(r'[a-f0-9]{40}',commit):raise SetupError('Verified release commit required.')
    if sum(POOLS.values())+PROTECTED!=TOTAL:raise SetupError('Budget totals do not reconcile.')
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600);os.close(fd)
    g=None
    try:
        g=LiveGovernor(path)
        with g.transaction() as db:db.execute("UPDATE controls SET paused='Initial funded setup; recurring collector disabled; smoke approval pending' WHERE id=1")
        cycle='quota-'+now.astimezone(timezone.utc).strftime('%Y-%m')
        g.configure_cycle(cycle,parse(start),parse(end))
        g.bind(cycle,key_identity(key),0,TOTAL,{name:0 for name in POOLS},now,'Funded sports-list quota verification; no prior usage')
        with g.transaction() as db:
            g._audit(db,now,'commissioning-setup','Owner-approved initial paused binding',{'release_commit':commit,'budget_version':BUDGET_VERSION,'pools':POOLS,'protected':PROTECTED})
        if g.db.execute('PRAGMA integrity_check').fetchall()[0][0]!='ok':raise SetupError('Ledger integrity check failed.')
    finally:
        if g:g.close()
    return status(path)

def status(path=STATE):
    path=Path(path)
    if not path.is_file() or path.is_symlink():raise SetupError('Existing regular ledger required.')
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
        paused=db.execute('SELECT paused FROM controls WHERE id=1').fetchone()[0]
        policy=db.execute('SELECT version,limits_json,total,protected FROM quota_policy').fetchall()
        binding=db.execute('SELECT cycle_id,used FROM quota_bindings').fetchall()
        if integrity!='ok' or not paused or len(policy)!=1 or len(binding)!=1:
            raise SetupError('Initial ledger must be intact, bound once and paused.')
        version,limits,total,reserve=policy[0]
        if version!=BUDGET_VERSION or json.loads(limits)!=POOLS or total!=TOTAL or reserve!=PROTECTED:
            raise SetupError('Ledger budget policy differs; stop and review.')
        cycle=db.execute('SELECT starts,ends FROM cycles WHERE id=?',(binding[0][0],)).fetchone()
        paid=db.execute('SELECT count(*) FROM dispatches').fetchone()[0]
        unresolved=db.execute("SELECT count(*) FROM attempts WHERE state IN ('unknown','inflight')").fetchone()[0]
        return dict(result='commissioned_paused' if paid else 'initialized_paused',cycle_id=binding[0][0],
            quota_cycle_start_utc=datetime.fromtimestamp(cycle[0],timezone.utc).isoformat(),
            next_quota_reset_utc=datetime.fromtimestamp(cycle[1],timezone.utc).isoformat(),
            provider_used=binding[0][1],pools=json.loads(limits),protected_reserve=reserve,
            budget_version=version,paused=True,worker_started=False,paid_odds_calls=paid,unresolved_requests=unresolved,
            note='Ledger accounting only; consult smoke evidence for publication and freshness. Recurring activation is not proved by setup.')

def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--status',action='store_true')
    args=parser.parse_args();step='preflight'
    try:
        if args.status:
            print(json.dumps(status(),indent=2));return 0
        values=onboarding.preflight()
        if not values.get('ODDS_API_KEY'):raise SetupError('Complete private key onboarding first.')
        with maintenance_lock(exclusive=True):
            onboarding.preflight()
            step='restricted_writer_readonly_verification'
            connection=writer(values);connection.close()
            step='fresh_zero_credit_quota_verification'
            quota=onboarding.verify_key(values['ODDS_API_KEY'])
            import subprocess
            commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True,stderr=subprocess.DEVNULL,timeout=10).strip()
            step='initial_paused_ledger_binding'
            result=initialize(STATE,values['ODDS_API_KEY'],quota,datetime.now(timezone.utc),commit)
            step='private_setup_evidence'
            if any(path.is_symlink() for path in (RETAINED,RETAINED/'onboarding',RETAINED/'onboarding'/'paused-setup.json')):
                raise SetupError('Retained evidence symlink refused.')
            write_private(RETAINED/'onboarding'/'paused-setup.json',result)
        print(json.dumps(result,indent=2))
        print('Collector and checkout activation unchanged. Fresh encrypted checkpoint required; preserve any partial ledger on failure.')
        return 0
    except (Exception,KeyboardInterrupt):
        print(json.dumps({'result':'refused','step':step,'worker_started':False,'automatic_retry':False,
                          'action':'Preserve any existing ledger; do not delete, reinitialize or expose private config.'}))
        return 1
if __name__=='__main__':raise SystemExit(main())
