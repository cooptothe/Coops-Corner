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



def repair_missing_settled_charge(g, now, quota, *, accept_single_delta=False):
    """Restore one legacy NULL settlement using an exclusive-key verified total.

    Preserve the reservation, request, payloads and previous NULL in the audit.
    Never modify an already recorded charge or distribute unexplained drift.
    """
    with g.transaction() as db:
        g._offline(db, now)
        binding = g._binding(db, now)
        rows = db.execute("SELECT * FROM attempts WHERE state='settled' AND actual IS NULL").fetchall()
        if not rows:
            return {}
        if not accept_single_delta or len(rows) != 1:
            raise Refused('One missing settled charge and exclusive-key acceptance required')
        if db.execute("SELECT 1 FROM attempts WHERE state!='settled' UNION ALL SELECT 1 FROM quota_inventory WHERE state!='settled' OR actual IS NULL").fetchone():
            raise Refused('All other requests must have verified settled costs')
        row = rows[0]
        used, remaining = quota['provider_used'], quota['provider_remaining']
        from corner.collection_policy import TOTAL, PROTECTED, POOLS
        if (type(used) is not int or type(remaining) is not int or used < binding['used']
                or remaining <= PROTECTED or used < 0 or used+remaining != TOTAL):
            raise Refused('Fresh forward quota and protected reserve required')
        if row['cycle_id'] != binding['cycle_id'] or now.timestamp()-row['started'] < 125:
            raise Refused('Missing settlement must be old and in the current cycle')
        before = g.accounted(db, binding['cycle_id'])
        actual = used - (sum(before.values()) - row['reserved'])
        if not 0 <= actual <= row['reserved']:
            raise Refused('Verified total does not identify a bounded missing settlement')
        for raw, in db.execute("SELECT detail FROM quota_audit WHERE action='odds-response' AND json_extract(detail,'$.token')=?", (row['token'],)):
            known = json.loads(raw).get('actual')
            if known is not None and known != actual:
                raise Refused('Saved response charge contradicts the proposed settlement')
        after = dict(before)
        after[row['pool']] += actual-row['reserved']
        if sum(after.values()) != used or any(p not in POOLS or v>g.pool_limits(db,binding['cycle_id'])[p] for p,v in after.items()):
            raise Refused('Restored settlement must match quota and every pool limit')
        db.execute("UPDATE attempts SET actual=? WHERE token=? AND state='settled' AND actual IS NULL", (actual,row['token']))
        g._audit(db,now,'settled-charge-restored','Exclusive-key fresh provider total identifies the sole missing settlement',
                 {'token':row['token'],'cycle':row['cycle_id'],'pool':row['pool'],
                  'previous_actual':None,'reserved':row['reserved'],'actual':actual,
                  'provider_used':used,'accounted_before':sum(before.values()),
                  'basis':'operator_accepted_provider_total_delta'})
        return {row['token']:actual}


def reconcile_known_failure(g, now, quota, *, accept_single_delta=False):
    repaired = repair_missing_settled_charge(g,now,quota,accept_single_delta=accept_single_delta)
    binding = g._binding(g.db, now)
    unknown = g.db.execute("SELECT * FROM attempts WHERE state='unknown'").fetchall()
    inventory = g.db.execute("SELECT * FROM quota_inventory WHERE state!='settled'").fetchall()
    if len(unknown)+len(inventory) > 1:
        raise Refused('More than one uncertain request requires explicit operator evidence')
    settlements = {}
    inventory_settlements = {}
    if inventory:
        row = inventory[0]
        if (row['state'] != 'unknown' or not accept_single_delta
                or now.timestamp()-row['started'] < 125 or row['cycle_id'] != binding['cycle_id']):
            raise Refused('One old unknown inventory request and exclusive-key acceptance required')
        known = sum(json.loads(binding['offsets']).values())
        for table in ('attempts', 'quota_inventory'):
            known += g.db.execute("SELECT coalesce(sum(actual),0) FROM "+table+
                                  " WHERE cycle_id=? AND state='settled'", (binding['cycle_id'],)).fetchone()[0]
        # Discovery is zero-charge. A fresh exclusive-key total equal to all
        # settled costs proves no charge; never allocate unexplained drift.
        if quota['provider_used'] != known or row['actual'] not in (None, 0):
            raise Refused('Inventory recovery requires an unchanged verified quota total')
        inventory_settlements[row['token']] = 0
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
                settlements, inventory_settlements, 'Stopped-worker recovery; exclusive-key fresh total confirms all settled costs and at most one uncertain request')
    g.resume(now, 'Resume healthy scopes only; quarantine remains enforced')
    from corner.collection_retry import release_zero_charge_recoveries
    release_zero_charge_recoveries(g,now)
    return {**repaired, **settlements, **inventory_settlements}


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
            retry_review=json.loads(g.db.execute("SELECT detail FROM quota_audit WHERE action='reconciled-retry-review' ORDER BY id DESC LIMIT 1").fetchone()[0])['released']
            print(json.dumps({'result':'recovery_prepared','provider_used':quota['provider_used'],
                              'settled_requests':len(settlements),'recovered_charge':sum(settlements.values()),
                              'retry_scopes_released':len(retry_review),
                              'zero_charge_scopes_released':sum(r['actual']==0 for r in retry_review),
                              'preserved_charges_on_released_scopes':sum(r['actual'] for r in retry_review),
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
