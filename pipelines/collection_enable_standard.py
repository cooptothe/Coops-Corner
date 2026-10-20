"""Prepare an explicitly authorized standard-only scheduled launch; never starts services."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
from dotenv import set_key
from corner.collection_activation import STATE, RETAINED
from corner.collection_maintenance import maintenance_lock
from corner.collection_quota import LiveGovernor, key_identity
from corner.collection_policy import parse
from corner.credit_governor import Refused
from pipelines import collection_smoke as smoke
from pipelines import collection_onboarding as onboarding
from pipelines.recovery_probe import write_private


def prepare(g, values, quota, now, commit, smoke_result):
    if (smoke_result.get('result') != 'smoke_passed'
            or smoke_result.get('replay_counts_unchanged') is not True
            or smoke_result.get('fresh_quotes_visible') is not True
            or not smoke_result.get('restricted_reader_quotes')):
        raise Refused('Completed real publication smoke required')
    binding = g._binding(g.db, now)
    if binding['key_hash'] != key_identity(values['ODDS_API_KEY']):
        raise Refused('Credential differs from the bound cycle')
    if not 0 <= (now-parse(quota['checked_at_utc'])).total_seconds() < 60 or quota['last_request_charge'] != 0:
        raise Refused('Fresh zero-charge provider quota required')
    if g.db.execute('SELECT 1 FROM publication_outbox WHERE published_at IS NULL').fetchone():
        raise Refused('Publish pending captures before scheduled activation')
    offsets = json.loads(binding['offsets'])
    # Exact current costs only; never silently allocate external use or erase unknown requests.
    g.reconcile(now, quota['provider_used'], quota['provider_remaining'], offsets, {}, {},
                'Owner-authorized standard worker launch; fresh provider sports quota')
    g.resume(now, 'Start standard-pregame-v1; fast classification and full-slate throughput remain unverified')
    cycle = g.db.execute('SELECT starts,ends FROM cycles WHERE id=?', (binding['cycle_id'],)).fetchone()
    evidence = {
        'live_driver_reviewed': 'Restricted standard profile; durable reservations and dispatch guards; regression suite',
        'writer_role_reviewed': 'Dedicated writer startup privilege checks and successful VPS ingestion',
        'writer_staging_smoke_test': 'smoke/result.json: actual captured odds, restricted reader and idempotent replay',
        'quota_reconciliation_tested': 'Fresh sports-list headers match durable accounting exactly; no external allocation',
        'pause_and_recovery_tested': 'Offline VPS worker/lock/outbox recovery passed; restored ledger forced paused',
        'offserver_backup_restore_tested': 'Owner PC decryption and isolated ledger/PostgreSQL restore passed Oct 20; post-smoke encrypted checkpoint retained',
        'log_secret_redaction_checked': 'Provider URLs and exception bodies suppressed; safe commissioning output verified',
    }
    return dict(approved=True, profile='standard-pregame-v1', release_commit=commit,
                cycle_id=binding['cycle_id'],
                cycle_start=datetime.fromtimestamp(cycle[0], timezone.utc).isoformat(),
                cycle_end=datetime.fromtimestamp(cycle[1], timezone.utc).isoformat(),
                quota_checked_at=quota['checked_at_utc'], provider_used=quota['provider_used'],
                provider_remaining=quota['provider_remaining'], evidence=evidence,
                pending=['Fast-book classification', 'Full-slate throughput measurement'])


def main():
    os.umask(0o077)
    g = None
    step = 'disabled_preflight'
    try:
        values = smoke.preflight()
        with maintenance_lock(exclusive=True):
            values = smoke.preflight()
            result_path = RETAINED/'smoke'/'result.json'
            onboarding.private_file(result_path)
            smoke_result = json.loads(result_path.read_text())
            # Owner-provided post-purchase checkpoint, verified without decrypting on the server.
            archive = Path('/srv/corner/backups/automated/checkpoint-20261020T163713Z-ebbb8370.tar.gz.gpg')
            if archive.is_symlink() or hashlib.sha256(archive.read_bytes()).hexdigest() != '271badd9a8d042ba226b93af74823194b7eaa893cd2103aa2e4b9ce74d39e309':
                raise Refused('Verified post-smoke checkpoint absent or changed')
            step = 'writer_and_reader'
            conn = smoke.writer(values)
            conn.close()
            smoke.reader_check()
            step = 'fresh_quota_and_resume'
            quota = onboarding.verify_key(values['ODDS_API_KEY'])
            g = LiveGovernor(STATE)
            commit = subprocess.check_output(['git','rev-parse','HEAD'], text=True,
                                             stderr=subprocess.DEVNULL, timeout=10).strip()
            approval = prepare(g, values, quota, datetime.now(timezone.utc), commit, smoke_result)
            step = 'private_launch_configuration'
            pending = RETAINED/'activation'/'approval.json'
            if any(p.is_symlink() for p in (pending, pending.parent)):
                raise Refused('Approval path symlink refused')
            write_private(pending, approval)
            set_key(str(onboarding.STAGING), 'CORNER_COLLECTION_DB', str(STATE))
            set_key(str(onboarding.CONFIG), 'CORNER_COLLECTION_ENABLED', '1')
            print(json.dumps({'result':'standard_launch_prepared', 'profile':approval['profile'],
                              'provider_used':quota['provider_used'], 'paid_odds_calls':0,
                              'worker_started':False, 'checkout_changed':False}))
        return 0
    except (Exception, KeyboardInterrupt):
        if g:
            try:
                with g.transaction() as db:
                    db.execute("UPDATE controls SET paused='Standard launch preparation failed; operator review required' WHERE id=1")
            except Exception:
                pass
        print(json.dumps({'result':'refused','step':step,'worker_started':False,
                          'action':'Preserve accounting; do not reset the ledger or permit.'}))
        return 1
    finally:
        if g:
            g.close()


if __name__ == '__main__':
    raise SystemExit(main())
