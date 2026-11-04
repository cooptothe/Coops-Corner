"""Explicit owner-approved full-quota allocation; offline, no odds requests."""
import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from dotenv import dotenv_values
from corner.collection_activation import STATE, ROOT, APPROVAL
from corner.collection_maintenance import maintenance_lock
from corner.collection_policy import BUDGET_VERSION, POOLS, TOTAL, PROTECTED
from corner.collection_quota import LiveGovernor, key_identity
from corner.credit_governor import Refused
from pipelines import collection_onboarding as onboarding

OLD_POOLS={'main':7900000,'props':5000000,'metadata':500000,'history':100000}

def upgrade(g,now,quota,identity):
    with g.transaction() as db:
        g._offline(db,now)
        row=db.execute('SELECT b.*,p.version,p.limits_json,p.total,p.protected FROM quota_bindings b JOIN cycles c ON c.id=b.cycle_id JOIN quota_policy p ON p.cycle_id=b.cycle_id WHERE c.starts<=? AND c.ends>?',(now.timestamp(),now.timestamp())).fetchone()
        if not row or row['key_hash']!=identity:raise Refused('Current binding and unchanged credential required')
        if db.execute("SELECT 1 FROM attempts WHERE state!='settled' OR actual IS NULL UNION ALL SELECT 1 FROM quota_inventory WHERE state!='settled' OR actual IS NULL").fetchone():raise Refused('Resolve uncertain requests before policy upgrade')
        prior=json.loads(row['limits_json'])
        used=quota['provider_used'];remaining=quota['provider_remaining']
        amounts=g.accounted(db,row['cycle_id'])
        if (type(used) is not int or type(remaining) is not int or used<row['used'] or used+remaining!=TOTAL or remaining<=0 or sum(amounts.values())!=used
            or any(type(v) is not int or v<0 for v in amounts.values())):
            raise Refused('Fresh quota must match preserved accounting; free discovery/history allocations must have no spend')
        if row['version']==BUDGET_VERSION:
            g.pool_limits(db,row['cycle_id'])
            return row['cycle_id']
        valid_old=(row['version']=='pregame-lab-history-100k-v1' and prior==OLD_POOLS and row['protected']==1500000)
        valid_full=(row['version']=='full-quota-main-props-live-v2' and prior=={'main':7500000,'props':7400000,'metadata':100000,'history':0} and row['protected']==0)
        if not (valid_old or valid_full) or row['total']!=TOTAL:
            raise Refused('Reviewed prior policy required')
        other=amounts.get('metadata',0)+amounts.get('history',0)
        main=min(max(POOLS['main'],amounts.get('main',0)),TOTAL-other-amounts.get('props',0))
        limits={'main':main,'props':TOTAL-other-main,'metadata':amounts.get('metadata',0),'history':amounts.get('history',0)}
        db.execute('UPDATE quota_policy SET version=?,limits_json=?,protected=? WHERE cycle_id=?',(BUDGET_VERSION,json.dumps(limits,sort_keys=True),PROTECTED,row['cycle_id']))
        g._audit(db,now,'full-budget-policy-approved','Owner requested all usable quota by Nov 20; no post-deadline holdback',{'cycle':row['cycle_id'],'old_limits':prior,'new_limits':limits,'old_protected':row['protected'],'new_protected':PROTECTED,'verified_used':used})
        return row['cycle_id']

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--use-full-quota',action='store_true',required=True)
    parser.parse_args();os.umask(0o077);g=None
    try:
        if os.name!='posix' or os.getcwd()!=str(ROOT):raise Refused('VPS application directory required')
        state=subprocess.run(['systemctl','is-active','--quiet','corner-collection.service'],timeout=10)
        if state.returncode not in (3,4):raise Refused('Stopped worker required')
        onboarding.private_file(onboarding.CONFIG);onboarding.private_file(onboarding.STAGING)
        values=dotenv_values(onboarding.CONFIG)
        if values.get('CORNER_COLLECTION_ENABLED')!='1' or dotenv_values(onboarding.STAGING).get('ODDS_API_KEY'):raise Refused('Private collector and key-free staging required')
        info=APPROVAL.lstat()
        import stat
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022 or json.loads(APPROVAL.read_text()).get('approved') is not True:raise Refused('Prior root-controlled approval required')
        with maintenance_lock(exclusive=True):
            quota=onboarding.verify_key(values['ODDS_API_KEY']);now=datetime.now(timezone.utc)
            g=LiveGovernor(STATE);cycle=upgrade(g,now,quota,key_identity(values['ODDS_API_KEY']))
            print(json.dumps(dict(result='full_quota_policy_ready',cycle_id=cycle,pools=g.pool_limits(g.db,cycle),protected_reserve=PROTECTED,paid_odds_calls=0,accounting_preserved=True)))
        return 0
    except Exception as error:
        print(json.dumps(dict(result='refused',reason=str(error) if isinstance(error,Refused) else 'Budget upgrade preflight failed',error_type=type(error).__name__,paid_odds_calls=0)))
        return 1
    finally:
        if g:g.close()
if __name__=='__main__':raise SystemExit(main())
