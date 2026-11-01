"""Explicit stopped-worker calendar quota rollover; no paid requests or resets."""
import argparse
import json
import os
import stat
import subprocess
from datetime import datetime, timezone
from dotenv import dotenv_values
from corner.collection_activation import APPROVAL, STATE, RETAINED, ROOT
from corner.collection_maintenance import maintenance_lock
from corner.collection_policy import POOLS, TOTAL, parse
from corner.collection_quota import LiveGovernor, key_identity
from corner.credit_governor import Refused
from pipelines import collection_onboarding as onboarding
from pipelines.recovery_probe import write_private


def bind_month(g, now, quota, identity):
    start, end = onboarding.quota_window(now)
    cycle = 'quota-' + now.strftime('%Y-%m')
    with g.transaction() as db:
        g._offline(db, now)
        prior = db.execute('SELECT b.*, c.ends FROM quota_bindings b JOIN cycles c ON c.id=b.cycle_id ORDER BY c.ends DESC LIMIT 1').fetchone()
        if not prior or prior['key_hash'] != identity or prior['ends'] > parse(start).timestamp():
            raise Refused('Expired prior binding with unchanged key required')
        if db.execute("SELECT 1 FROM attempts WHERE state!='settled' OR actual IS NULL UNION ALL SELECT 1 FROM quota_inventory WHERE state!='settled' OR actual IS NULL").fetchone():
            raise Refused('Resolve prior-cycle uncertain requests before rollover')
        if (quota['provider_used'] != 0 or quota['provider_remaining'] != TOTAL
                or quota['last_request_charge'] != 0
                or quota['quota_cycle_start_utc'] != start or quota['next_quota_reset_utc'] != end):
            raise Refused('Verified unused new monthly quota required; nonzero usage needs explicit allocation')
    g.configure_cycle(cycle, parse(start), parse(end))
    g.bind(cycle, identity, 0, TOTAL, {p:0 for p in POOLS}, now,
           'Operator-approved calendar rollover; zero-charge provider verification; old accounting retained')
    return cycle, start, end


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approve-current-month', action='store_true', required=True)
    parser.parse_args()
    os.umask(0o077)
    g=None
    try:
        if os.name!='posix' or os.getcwd()!=str(ROOT):
            raise Refused('VPS application directory required')
        result=subprocess.run(['systemctl','is-active','--quiet','corner-collection.service'], timeout=10)
        if result.returncode not in (3,4): raise Refused('Stop worker first')
        onboarding.private_file(onboarding.CONFIG)
        onboarding.private_file(onboarding.STAGING)
        values=dotenv_values(onboarding.CONFIG)
        if values.get('CORNER_COLLECTION_ENABLED')!='1' or dotenv_values(onboarding.STAGING).get('ODDS_API_KEY'):
            raise Refused('Enabled private collector and key-free staging required')
        info=APPROVAL.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:
            raise Refused('Root-controlled prior approval required')
        approval=json.loads(APPROVAL.read_text())
        if approval.get('approved') is not True: raise Refused('Prior approval required')
        with maintenance_lock(exclusive=True):
            quota=onboarding.verify_key(values['ODDS_API_KEY'])
            now=datetime.now(timezone.utc)
            g=LiveGovernor(STATE)
            cycle,start,end=bind_month(g,now,quota,key_identity(values['ODDS_API_KEY']))
            approval.update(cycle_id=cycle,cycle_start=start,cycle_end=end,
                release_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
                quota_checked_at=quota['checked_at_utc'],provider_used=0,provider_remaining=TOTAL)
            write_private(RETAINED/'activation'/'approval.json',approval)
            print(json.dumps(dict(result='new_cycle_bound_paused',cycle_id=cycle,
                provider_used=0,paid_odds_calls=0,old_accounting_preserved=True)))
        return 0
    except Exception as error:
        print(json.dumps(dict(result='refused',error_type=type(error).__name__,
            reason=str(error) if isinstance(error,Refused) else 'Rollover preflight failed; preserve ledger',paid_odds_calls=0)))
        return 1
    finally:
        if g: g.close()

if __name__=='__main__': raise SystemExit(main())
