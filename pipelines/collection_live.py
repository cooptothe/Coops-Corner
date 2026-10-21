"""Disabled-by-default scheduled worker. All funded activation gates are mandatory."""
import argparse
from datetime import datetime, timezone
import json
import os
import signal
import time

import psycopg2

from corner.collection_activation import activation, STATE, RETAINED
from corner.collection_policy import parse, ALL_BOOKS_PROFILE
from corner.collection_quota import LiveGovernor, key_identity
from corner.credit_governor import Refused
from corner.collection_maintenance import maintenance_lock, MaintenanceBusy
from pipelines.collection_provider import Provider
from pipelines.collection_publication import MainPublisher
from pipelines.collection_runner import Runner


def clock():
    return datetime.now(timezone.utc)


def writer(config=None):
    """No default config, owner fallback, role creation, or credential logging."""
    config = os.environ if config is None else config
    conn = psycopg2.connect(
        host=config['CORNER_COLLECTION_DB_HOST'],
        port=config['CORNER_COLLECTION_DB_PORT'],
        dbname=config['CORNER_COLLECTION_DB_NAME'],
        user=config['CORNER_COLLECTION_DB_USER'],
        password=config['CORNER_COLLECTION_DB_PASSWORD'],
        connect_timeout=5, options='-c statement_timeout=15000 -c lock_timeout=5000')
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT current_database(),current_user')
            if cur.fetchone() != ('corner_staging', 'corner_collection_writer'):
                raise Refused('Unexpected worker database identity')
            cur.execute("SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user")
            if any(cur.fetchone()):
                raise Refused('Writer has elevated role attributes')
            cur.execute("SELECT pg_has_role(current_user,'corner_owner','MEMBER'),has_schema_privilege(current_user,'corner','CREATE'),has_table_privilege(current_user,'corner.odds_observations','DELETE')")
            if any(cur.fetchone()):
                raise Refused('Writer has owner, DDL or ledger deletion privilege')
            cur.execute("SELECT 1 FROM corner.quote_states WHERE code='active'")
            if cur.fetchone() is None:
                raise Refused('Active quote state is not provisioned')
        conn.rollback()
        return conn
    except BaseException:
        conn.close()
        raise


class LiveProvider(Provider):
    def __init__(self, governor, owner, **kwargs):
        self.should_stop = kwargs.pop('should_stop', lambda: False)
        super().__init__(**kwargs)
        self.g = governor
        self.owner = owner
        self.identity = key_identity(self.key)

    def gate(self):
        if self.should_stop():
            raise Refused('Worker shutdown requested')
        now = super().gate()
        activation(now)
        return now

    def discover(self):
        inventory = super().discover()
        if activation(self.clock()).get('profile') in ('standard-pregame-v1', ALL_BOOKS_PROFILE):
            upcoming = {event['sport_key'] for event in inventory['events']}
            inventory['active_sport_keys'] = [key for key in inventory['active_sport_keys'] if key in upcoming]
        return inventory

    def odds(self, governor, job, token, owner):
        if activation(self.clock()).get('profile') == 'standard-pregame-v1' and job.group != 'standard':
            raise Refused('Standard activation cannot dispatch fast-book jobs')
        return super().odds(governor, job, token, owner)

    def _get(self, path, params):
        now = self.gate()
        if not self.g.acquire(self.owner, now):
            raise Refused('Another worker holds the lease')
        inventory = path == '/' or path.endswith('/events')
        token = self.g.authorize(self.owner, now, self.identity, inventory=inventory)
        try:
            status, data, headers = super()._get(path, params)
        except Exception:
            if inventory:
                self.g.inventory_unknown(token, self.owner, self.clock())
            raise
        if inventory:
            self.g.inventory_finish(token, self.owner, self.clock(), headers, status)
        return status, data, headers


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Validate startup gates without HTTP or worker writes')
    args = parser.parse_args()
    g = provider = runner = None
    entered_loop = False
    stop = [False]
    try:
        approval = activation(clock(), startup=True)
        if not STATE.is_file():
            raise Refused('Explicit offline billing-cycle binding must precede startup')
        # Do not create or migrate the state while merely checking startup.
        if args.check:
            print(json.dumps({'activation_evidence': 'accepted', 'live_collection_started': False,
                              'remaining_checks': 'Bound ledger and writer are checked at actual startup'}))
            return 0
        with maintenance_lock(should_stop=lambda: stop[0]):
            approval = activation(clock(), startup=True)
            g = LiveGovernor(STATE)
            with g.transaction() as db:
                binding = g._binding(db, clock())
                if binding['cycle_id'] != approval['cycle_id'] or binding['key_hash'] != key_identity(os.environ['ODDS_API_KEY']):
                    raise Refused('Approval and bound credential/billing cycle disagree')
                if binding['used'] != approval['provider_used'] or not 0 <= clock().timestamp() - binding['checked'] < 300:
                    raise Refused('Fresh ledger reconciliation must match activation quota approval')
                cycle = db.execute('SELECT starts,ends FROM cycles WHERE id=?', (binding['cycle_id'],)).fetchone()
                if tuple(cycle) != (parse(approval['cycle_start']).timestamp(), parse(approval['cycle_end']).timestamp()):
                    raise Refused('Approved billing dates differ from durable ledger')
            conn = writer()
            conn.close()
            runner = Runner(g, None, None, publisher=MainPublisher(RETAINED, writer), clock=clock,
                            should_stop=lambda: stop[0], additional=True,
                            job_filter=(lambda job: job.group == 'standard') if approval.get('profile') == 'standard-pregame-v1' else None)
            provider = LiveProvider(g, runner.owner, key=os.environ['ODDS_API_KEY'], enabled=True,
                                    exchange_verified=approval.get('profile') == 'full-v1',
                                    budgeted_pregame=approval.get('profile') == ALL_BOOKS_PROFILE, clock=clock, should_stop=lambda: stop[0])
            runner.discover = provider.discover
            runner.transport = provider.odds
        def stopping(*args):
            stop[0] = True
        signal.signal(signal.SIGTERM, stopping)
        signal.signal(signal.SIGINT, stopping)
        entered_loop = True
        while not stop[0]:
            activation(clock())
            try:
                with maintenance_lock(timeout=0, should_stop=lambda: stop[0]):
                    result = runner.tick()
            except MaintenanceBusy:
                result = {'state': 'backup_maintenance', 'executed': 0}
            print(json.dumps(result, sort_keys=True), flush=True)
            # Shutdown intent prohibits any subsequent HTTP after the current call.
            for _ in range(10):
                if stop[0]:
                    break
                time.sleep(.1)
        return 0
    except Exception:
        # No exception repr/traceback: DB and HTTP errors may expose credentials.
        print(json.dumps({'state': 'blocked', 'worker_entered_loop': entered_loop,
                          'action': 'Review activation gates and offline operator status'}), flush=True)
        return 1
    finally:
        if provider:
            provider.close()
        if g:
            try:
                if runner:
                    with maintenance_lock(timeout=0):
                        g.release(runner.owner)
            except (Refused, MaintenanceBusy):
                pass  # Inflight reservations remain held until conservative recovery.
            g.close()


if __name__ == '__main__':
    raise SystemExit(main())
