"""Offline, audited billing setup/recovery. Never calls a provider or publishes."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
from getpass import getpass
import json
from pathlib import Path
import os
import sqlite3

from corner.collection_policy import parse
from corner.collection_quota import LiveGovernor, key_identity
from corner.collection_maintenance import maintenance_lock


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('init', 'status', 'pause', 'recover-lease', 'reconcile', 'resume'))
    parser.add_argument('--state', required=True)
    parser.add_argument('--request', help='Private JSON containing verified accounting/evidence, never secrets')
    parser.add_argument('--evidence', help='Short operator reference, no secrets')
    args = parser.parse_args()
    path = Path(args.state)
    if path.name != 'collection-live.sqlite3':
        parser.error('Explicit separate collection-live.sqlite3 path required')
    if args.command != 'init' and not path.is_file():
        parser.error('Live state absent; refusing to create it')
    if args.command == 'init' and path.exists():
        parser.error('State already exists; init cannot overwrite or reset it')
    g = None
    maintenance = ExitStack()
    try:
        if args.command == 'status':
            db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
            try:
                print(json.dumps({'paused': db.execute('SELECT paused FROM controls WHERE id=1').fetchone()[0],
                    'attempts': dict(db.execute('SELECT state,count(*) FROM attempts GROUP BY state')),
                    'inventory': dict(db.execute('SELECT state,count(*) FROM quota_inventory GROUP BY state')),
                    'billing': [dict(zip(('cycle', 'provider_used', 'checked_at'), row)) for row in db.execute('SELECT cycle_id,used,checked FROM quota_bindings')],
                    'audit_records': db.execute('SELECT count(*) FROM quota_audit').fetchone()[0]}, sort_keys=True))
            finally:
                db.close()
            return 0
        maintenance.enter_context(maintenance_lock(exclusive=True))
        request = json.loads(Path(args.request).read_text(encoding='utf-8')) if args.request else {}
        now = datetime.now(timezone.utc)
        if args.command == 'init':
            # Validate request structure before creating a new durable file.
            starts, ends = parse(request['cycle_start']), parse(request['cycle_end'])
            if not starts <= now < ends:
                raise ValueError('Current explicit billing period required')
            identity = key_identity(getpass('Funded provider key (not stored): '))
            g = LiveGovernor(path)
            g.configure_cycle(request['cycle_id'], starts, ends)
            g.bind(request['cycle_id'], identity, request['provider_used'], request['provider_remaining'],
                   request['offsets'], now, request['evidence'])
            with g.transaction() as db:
                db.execute("UPDATE controls SET paused='Initial binding; explicit reconciliation/resume required' WHERE id=1")
        else:
            g = LiveGovernor(path)
            if args.command == 'pause':
                with g.transaction() as db:
                    g._audit(db, now, 'pause', args.evidence, {})
                    db.execute("UPDATE controls SET paused='Operator pause; reconciliation required' WHERE id=1")
            elif args.command == 'recover-lease':
                # acquire refuses a still-active worker; expires ambiguous odds/
                # inventory attempts conservatively without changing their costs.
                owner = 'operator-recovery'
                if not g.acquire(owner, now):
                    raise ValueError('Worker lease still active')
                try:
                    with g.transaction() as db:
                        g._audit(db, now, 'recover-lease', args.evidence, {})
                        db.execute("UPDATE controls SET paused='Worker recovery; reconciliation required' WHERE id=1")
                finally:
                    g.release(owner)
            elif args.command == 'reconcile':
                g.reconcile(now, request['provider_used'], request['provider_remaining'], request['offsets'],
                            request.get('settlements', {}), request.get('inventory', {}), request['evidence'])
            elif args.command == 'resume':
                g.resume(now, args.evidence)
        print(json.dumps({'operation': args.command, 'result': 'recorded', 'provider_calls': 0,
                          'worker_started': False}, sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({'operation': args.command, 'result': 'refused', 'provider_calls': 0,
                          'action': 'Check request, ledger and operator evidence privately; no automatic refund/reset'}))
        return 1
    finally:
        if g:
            g.close()
        maintenance.close()


if __name__ == '__main__':
    raise SystemExit(main())
