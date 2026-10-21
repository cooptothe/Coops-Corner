"""Stopped-worker recovery: verified charges only; no paid odds calls or reset."""
from datetime import datetime, timezone
import argparse
import json
import os
import stat
import subprocess
from dotenv import dotenv_values
from corner.collection_activation import APPROVAL, STATE, RETAINED, ROOT
from corner.collection_quota import LiveGovernor, key_identity
from corner.collection_maintenance import maintenance_lock
from corner.credit_governor import Refused
from corner.collection_policy import parse, ALL_BOOKS, ALL_BOOKS_PROFILE, CADENCE_VERSION
from pipelines import collection_onboarding as onboarding
from pipelines.recovery_probe import write_private


def reconcile_known_failure(g, now, quota, *, accept_single_delta=False):
    binding = g._binding(g.db, now)
    unknown = g.db.execute("SELECT * FROM attempts WHERE state='unknown'").fetchall()
    if len(unknown) > 1 or g.db.execute("SELECT 1 FROM quota_inventory WHERE state!='settled'").fetchone():
        raise Refused('More than one uncertain request requires explicit operator evidence')
    settlements = {}
    if unknown:
        row = unknown[0]
        records = g.db.execute("SELECT at,detail FROM quota_audit WHERE action='odds-response' ORDER BY id DESC").fetchall()
        found = [(at,json.loads(detail)) for at,detail in records if json.loads(detail).get('token') == row['token']]
        verified = bool(found and not found[0][1].get('reason')
                        and quota['provider_used'] == binding['used']
                        and abs(binding['checked']-found[0][0]) <= .001)
        if not verified and (not accept_single_delta or now.timestamp()-row['started'] < 120):
            raise Refused('No verified response; explicit stopped-worker quota-delta acceptance required')
        if row['cycle_id'] != binding['cycle_id']:
            raise Refused('Uncertain request belongs to another quota cycle')
        at, detail = found[0] if verified else (None,{})
        known = sum(json.loads(binding['offsets']).values())
        known += g.db.execute("SELECT coalesce(sum(actual),0) FROM attempts WHERE cycle_id=? AND state='settled'", (binding['cycle_id'],)).fetchone()[0]
        known += g.db.execute("SELECT coalesce(sum(actual),0) FROM quota_inventory WHERE cycle_id=? AND state='settled'", (binding['cycle_id'],)).fetchone()[0]
        actual = detail.get('actual')
        if actual is None:
            actual = quota['provider_used']-known
        if type(actual) is not int or not 0 <= actual <= row['reserved'] or known+actual != quota['provider_used']:
            raise Refused('Verified totals do not identify a bounded charge')
        settlements[row['token']] = actual
        with g.transaction() as db:
            g.quarantine(db, row['job_key'], row['token'], now, 'recovered_snapshot_failure',
                         {'actual':actual,'response_audit_at':at,'scope_review_required':True,
                          'basis':'saved_verified_response' if verified else 'operator_accepted_provider_total_delta'})
    g.reconcile(now, quota['provider_used'], quota['provider_remaining'], json.loads(binding['offsets']),
                settlements, {}, 'Stopped-worker recovery; explicit operator acceptance of current provider usage, all settled costs and one quarantined request')
    g.resume(now, 'Resume healthy scopes only; quarantine remains enforced')
    return settlements


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--accept-single-request-quota-delta', action='store_true',
                        help='Operator confirms no other key consumer; accept fresh total minus all known charges for one old unknown request')
    parser.add_argument('--enable-all-books', action='store_true', help='Explicitly authorize all 16 books at the reviewed budgeted pregame cadence')
    args = parser.parse_args()
    g = None
    step = 'stopped_worker_preflight'
    try:
        if os.name != 'posix' or os.getcwd() != str(ROOT):
            raise Refused('VPS application directory required')
        state = subprocess.run(['systemctl','is-active','--quiet','corner-collection.service'],
                               stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
        if state.returncode not in (3,4):
            raise Refused('Stop the worker before recovery')
        onboarding.private_file(onboarding.CONFIG)
        onboarding.private_file(onboarding.STAGING)
        values = dotenv_values(onboarding.CONFIG)
        stage = dotenv_values(onboarding.STAGING)
        if values.get('CORNER_COLLECTION_ENABLED') != '1' or stage.get('ODDS_API_KEY'):
            raise Refused('Existing enabled private worker and key-free staging required')
        info = APPROVAL.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise Refused('Root-controlled prior activation required')
        approval = json.loads(APPROVAL.read_text())
        if approval.get('profile') not in ('standard-pregame-v1', ALL_BOOKS_PROFILE) or approval.get('approved') is not True:
            raise Refused('Reviewed standard profile required')
        with maintenance_lock(exclusive=True):
            g = LiveGovernor(STATE)
            if g._binding(g.db,datetime.now(timezone.utc))['key_hash'] != key_identity(values['ODDS_API_KEY']):
                raise Refused('Bound credential changed')
            step = 'fresh_quota_and_recovery'
            quota = onboarding.verify_key(values['ODDS_API_KEY'])
            now = datetime.now(timezone.utc)
            settlements = reconcile_known_failure(g, now, quota,
                                                  accept_single_delta=args.accept_single_request_quota_delta)
            approval.update(release_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True,
                            stderr=subprocess.DEVNULL,timeout=10).strip(),
                            quota_checked_at=quota['checked_at_utc'],provider_used=quota['provider_used'],
                            provider_remaining=quota['provider_remaining'])
            if args.enable_all_books or approval.get('profile') == ALL_BOOKS_PROFILE:
                approval.update(profile=ALL_BOOKS_PROFILE, requested_books=list(ALL_BOOKS), cadence_version=CADENCE_VERSION,
                                pending=['Live added-book coverage and throughput confirmation', 'Account-specific exchange fee context where applicable'])
            step = 'renew_root_approval_candidate'
            write_private(RETAINED/'activation'/'approval.json',approval)
            print(json.dumps({'result':'recovery_prepared','provider_used':quota['provider_used'],
                              'settled_requests':len(settlements),'recovered_charge':sum(settlements.values()),
                              'quarantined_scopes':g.db.execute('SELECT count(*) FROM collection_quarantine').fetchone()[0],
                              'paid_odds_calls':0,'worker_started':False}))
        return 0
    except (Exception,KeyboardInterrupt):
        if g:
            try:
                with g.transaction() as db:
                    db.execute("UPDATE controls SET paused='Recovery incomplete; preserve evidence for review' WHERE id=1")
                print(json.dumps({'unknown_requests':[dict(row) for row in g.db.execute("SELECT pool,reserved,started FROM attempts WHERE state='unknown'")],
                                  'recent_failures':[json.loads(row[0]) for row in g.db.execute("SELECT detail FROM quota_audit WHERE action='request-failed' ORDER BY id DESC LIMIT 3")]}))
            except Exception:
                pass
        print(json.dumps({'result':'refused','step':step,'paid_odds_calls':0,
                          'action':'No reset or refund. Need saved response charge evidence before resuming.'}))
        return 1
    finally:
        if g:
            g.close()


if __name__=='__main__':
    raise SystemExit(main())
