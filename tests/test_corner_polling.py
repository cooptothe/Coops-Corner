"""Finite scheduler proofs and disposable-PostgreSQL, non-owner integration."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os
import threading
import time
import unittest
from unittest.mock import patch

import psycopg2
from psycopg2 import sql

from corner import polling as p, versioned_dispatch as d, versioned_reconciliation as r, work as w
import test_corner_worker as old
from test_corner_work import WorkDatabase


class Clock:
    def __init__(self): self.now = 0
    def __call__(self): return self.now
    def advance(self, value): self.now += value


def report(**counts):
    return {'counts': dict(dict.fromkeys(('newly_requested', 'invalid', 'blocked', 'pending', 'fulfilled'), 0), **counts),
            'items': [], 'next_cursor': None}


class FakeBackend:
    def __init__(self, clock):
        self.clock, self.visits, self.pages = clock, [], []
        self.outcomes, self.failures, self.cost = {}, set(), 0

    def discover(self, partition, state, limit):
        self.pages.append(partition)
        self.clock.advance(self.cost)
        if partition in self.failures: raise RuntimeError('infrastructure')
        return report(), 'ceiling'

    def execute(self, kind, state, claimed):
        self.visits.append(kind)
        self.clock.advance(self.cost)
        if kind in self.failures: raise RuntimeError('infrastructure')
        status = self.outcomes.get(kind, 'idle')
        if status != 'idle': claimed(status == 'lease_lost')
        return {'status': status}, None, None


class SchedulerTests(unittest.TestCase):
    def setup_poller(self, **kwargs):
        self.clock = Clock()
        self.backend = FakeBackend(self.clock)
        self.settings = p.PollSettings(jitter_fraction=0, **kwargs)
        self.stop = p.Stop(self.clock)
        self.poller = p.Poller(self.backend, settings=self.settings, stop=self.stop, clock=self.clock)

    def test_noisy_kind_cannot_starve_and_position_survives_cycles(self):
        self.setup_poller(attempts_per_cycle=1)
        self.backend.outcomes['evaluate'] = 'completed'
        for _ in range(15): self.poller.run_cycle()
        self.assertEqual(list(p.KINDS) * 3, self.backend.visits)

    def test_slow_discovery_cannot_starve_execution_or_other_partitions(self):
        self.setup_poller(cycle_seconds=1, revisit_seconds=.01)
        self.backend.cost = 2
        for _ in range(12): self.poller.run_cycle()
        self.assertEqual(list(p.KINDS) + ['apply_lifecycle'], self.backend.visits)
        self.assertEqual(list(p.DISCOVERY) * 2, [x.obligation for x in self.backend.pages])

    def test_each_partition_receives_one_page_per_visit(self):
        self.setup_poller()
        self.poller.run_cycle()
        self.assertEqual(3, len(self.backend.pages))
        self.assertEqual(5, len(self.backend.visits))
        self.poller.run_cycle()
        self.assertEqual(3, len(self.backend.pages))

    def test_infrastructure_backoff_is_per_route_and_does_not_skip_cursor(self):
        self.setup_poller()
        part = self.poller.partitions[0]
        state = self.poller.discovery[part]
        state.after, state.ceiling = 'prior', 'fixed'
        self.backend.failures.update((part, 'evaluate'))
        first = self.poller.run_cycle()
        self.assertEqual(2, first['counts']['infrastructure_errors'])
        self.assertEqual(('prior', 'fixed'), (state.after, state.ceiling))
        self.poller.run_cycle()
        self.assertEqual(1, self.backend.visits.count('evaluate'))
        self.assertEqual(2, self.backend.visits.count('assess'))

    def test_idle_backoff_is_capped_and_revisit_interrupts_it(self):
        self.setup_poller(revisit_seconds=100)
        delays = [self.poller.run_cycle()['sleep_seconds'] for _ in range(9)]
        self.assertEqual([.25, .5, 1, 2, 4, 5, 5, 5, 5], delays)
        self.poller.discovery[self.poller.partitions[0]].due = .125
        self.assertEqual(.125, self.poller.run_cycle()['sleep_seconds'])

    def test_productive_cycle_resets_backoff(self):
        self.setup_poller()
        for _ in range(4): self.poller.run_cycle()
        self.backend.outcomes['qualify'] = 'completed'
        self.assertEqual(.001, self.poller.run_cycle()['sleep_seconds'])
        self.backend.outcomes.clear()
        self.assertEqual(.25, self.poller.run_cycle()['sleep_seconds'])

    def test_stop_during_attempt_prevents_further_admission(self):
        self.setup_poller()
        original = self.backend.execute
        def stop_after(*args):
            result = original(*args)
            self.stop.request()
            return result
        self.backend.execute = stop_after
        result = self.poller.run_cycle()
        self.assertEqual(1, len(self.backend.visits))
        self.assertEqual(0, result['sleep_seconds'])

    def test_stopped_loop_does_not_touch_backend(self):
        self.setup_poller()
        self.stop.request()
        self.poller.run(max_cycles=10)
        self.assertEqual([], self.backend.visits + self.backend.pages)

    def test_sleep_is_interruptible_and_no_operation_is_open(self):
        self.setup_poller(idle_initial=5, idle_cap=5)
        sleeping = threading.Event()
        original_wait = self.stop.wait
        def waiting(seconds): sleeping.set(); return original_wait(seconds)
        self.stop.wait = waiting
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.poller.run, max_cycles=100)
            self.assertTrue(sleeping.wait(2))
            self.stop.request()
            future.result(timeout=2)
        self.assertEqual(1, self.poller.cycles)

    def test_counters_keep_discovery_and_execution_separate(self):
        self.setup_poller()
        self.backend.outcomes = dict(zip(p.KINDS, ('completed', 'blocked', 'waiting', 'retryable', 'lease_lost')))
        self.backend.discover = lambda *args: (report(newly_requested=1, blocked=2, invalid=3), None)
        counts = self.poller.run_cycle()['counts']
        for key in ('completed', 'blocked', 'waiting', 'retryable', 'lease_lost', 'reclaimed'):
            self.assertEqual(1, counts[key], key)
        self.assertEqual(5, counts['claimed'])
        self.assertEqual(3, counts['discovered'])
        self.assertEqual(6, counts['reconciliation_blocked'])
        self.assertEqual(9, counts['reconciliation_invalid'])

    def test_configuration_rejects_unbounded_or_invalid_limits(self):
        for kwargs in ({'page_size':1001}, {'attempts_per_cycle':0}, {'cycle_seconds':float('inf')},
                       {'idle_cap':.1}, {'jitter_fraction':2}, {'operation_seconds':0}, {'connect_timeout_seconds':0}):
            with self.assertRaises(ValueError): p.PollSettings(**kwargs)
        self.setup_poller()
        with self.assertRaises(ValueError): self.poller.run(max_cycles=None)

    def test_backend_shutdown_signal_is_shared_not_silently_replaced(self):
        self.setup_poller()
        self.backend.stop = self.stop
        poller = p.Poller(self.backend, settings=self.settings, clock=self.clock)
        self.assertIs(self.stop, poller.stop)
        with self.assertRaises(ValueError):
            p.Poller(self.backend, settings=self.settings, stop=p.Stop(self.clock))
        self.backend.settings = replace(self.settings, shutdown_grace=1)
        with self.assertRaises(ValueError): p.Poller(self.backend, settings=self.settings)

    def test_invalid_worker_outcome_does_not_advance_traversal(self):
        self.setup_poller(attempts_per_cycle=1)
        state = self.poller.execution[p.KINDS[0]]
        state.after, state.ceiling = 'prior', 'fixed'
        self.backend.execute = lambda *args: ({'status': 'discovered'}, 'next', 'fixed')
        report = self.poller.run_cycle()
        self.assertEqual(1, report['counts']['infrastructure_errors'])
        self.assertEqual(('prior', 'fixed'), (state.after, state.ceiling))


@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE') == '1' and os.getenv('CORNER_TEST_CONCURRENCY') == '1',
                     'disposable polling database')
class DatabasePollingTests(WorkDatabase, unittest.TestCase):
    # Reuse setup helpers, never inherit/re-run another class's tests.
    for _name in ('select', 'evaluate', 'qualify', 'register', 'capture', 'command', 'record', 'app', 'opened',
                  'sql_error', 'enqueue', 'claim', 'prepare', 'execution', 'expire', 'routed'):
        locals()[_name] = getattr(old.WorkerTests, _name)

    def setUp(self):
        old.WorkerTests.setUp(self)
        # Isolate mutable scheduling state from other committed test fixtures.
        with self.conn.cursor() as cur:
            cur.execute("""UPDATE corner.work_executions SET status='blocked',blocked_reason='test_isolation',waiting_reason=NULL,lease_owner=NULL,
                lease_token=NULL,lease_expires_at=NULL WHERE status<>'completed'""")
        self.conn.commit()
        self.stop = p.Stop()
        self.poll_settings = p.PollSettings(attempts_per_cycle=1)
        self.backend = self.make_backend()

    def connect_role(self, role, **kwargs):
        conn = psycopg2.connect(**dict(self.connection_config, **kwargs))
        with conn.cursor() as cur: cur.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(self.roles[role])))
        conn.commit()
        return conn

    def make_backend(self):
        return p.DatabaseBackend(discover_connect=lambda **kw: self.connect_role('worker', **kw),
            execute_connect=lambda **kw: self.connect_role('worker', **kw), worker_settings=self.settings,
            settings=self.poll_settings, stop=self.stop)

    def execute_one(self, kind='ensure_occurrence', state=None):
        self.conn.commit()
        claims = []
        result, after, ceiling = self.backend.execute(kind, state or p.Traversal(), claims.append)
        return result, claims, after, ceiling

    def test_nonowner_poll_completes_occurrence_and_discovery_observes_result(self):
        request = self.enqueue()
        result, claims, _, _ = self.execute_one()
        self.assertEqual('completed', result['status'], result)
        self.assertEqual([False], claims)
        self.assertEqual('completed', self.execution(request)['status'])
        report, _ = self.backend.discover(p.Partition('occurrence'), p.Traversal(), 1000)
        item = next(x for x in report['items'] if x['candidate_id'] == self.judgment['id'])
        self.assertEqual('fulfilled', item['status'])

    def test_waiting_blocked_and_future_work_not_claimed(self):
        requests = [self.enqueue() for _ in range(3)]
        with self.conn.cursor() as cur:
            for request, status in zip(requests, ('waiting', 'blocked', 'retryable')):
                cur.execute("""UPDATE corner.work_executions SET status=%s,
                    waiting_reason=%s,blocked_reason=%s,available_at=clock_timestamp()+interval '1 day' WHERE work_request_id=%s""",
                    (status, 'prerequisite' if status == 'waiting' else None, 'test_block' if status == 'blocked' else None, request['id']))
        result, claims, _, _ = self.execute_one()
        self.assertEqual('idle', result['status'])
        self.assertEqual([], claims)

    def test_crash_after_frozen_preparation_reclaims_exact_command(self):
        request = self.enqueue()
        lease = self.claim(request)
        frozen = self.prepare(request, lease)
        self.expire(request)
        result, claims, _, _ = self.execute_one()
        self.assertEqual([True], claims)
        self.assertEqual('completed', result['status'], result)
        self.assertEqual(frozen['id'], result['execution']['prepared_command_id'])

    def test_two_pollers_claim_once(self):
        request = self.enqueue(); self.conn.commit()
        barrier = threading.Barrier(2)
        def attempt():
            barrier.wait()
            claims = []
            result, _, _ = self.backend.execute('ensure_occurrence', p.Traversal(), claims.append)
            return result, claims
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: attempt(), range(2)))
        self.assertEqual(1, sum(len(claims) for _, claims in results))
        self.assertEqual('completed', self.execution(request)['status'])

    def test_stop_after_claim_leaves_reclaimable_lease_without_preparation(self):
        request = self.enqueue(); self.conn.commit()
        result = d.run_once(lambda: self.connect_role('worker'), settings=self.settings, request_id=request['id'],
            should_stop=self.stop.is_set, claim_observer=lambda _: self.stop.request())
        self.assertEqual('stopped', result['status'])
        with self.conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM corner.prepared_work_commands WHERE work_request_id=%s', (request['id'],))
            self.assertEqual(0, cur.fetchone()[0])
        self.assertEqual('leased', self.execution(request)['status'])
        self.expire(request); self.stop = p.Stop(); self.backend = self.make_backend()
        self.assertEqual('completed', self.execute_one()[0]['status'])

    def test_stop_during_completion_commits_atomic_result(self):
        request = self.enqueue(); self.conn.commit()
        original = d.complete
        def completing(*args, **kwargs):
            self.stop.request()
            return original(*args, **kwargs)
        with patch.object(d, 'complete', completing):
            result, _, _, _ = self.execute_one()
        self.assertEqual('completed', result['status'], result)
        self.assertEqual('completed', self.execution(request)['status'])

    def test_explicit_pass_ceiling_excludes_new_tail_then_wrap_finds_it(self):
        with self.conn.cursor() as cur:
            first = r.pass_ceiling(self.conn, obligation='occurrence')
        later = self.qualify(self.evaluation)
        self.conn.commit()
        report, fence = self.backend.discover(p.Partition('occurrence'), p.Traversal(ceiling=first), 1000)
        self.assertEqual(first, fence)
        self.assertNotIn(later['id'], [x['candidate_id'] for x in report['items']])
        self.assertIsNone(report['next_cursor'])
        wrapped, _ = self.backend.discover(p.Partition('occurrence'), p.Traversal(), 1000)
        self.assertIn(later['id'], [x['candidate_id'] for x in wrapped['items']])

    def test_late_commit_below_ceiling_is_seen_after_wrap(self):
        late = self.qualify(self.evaluation)  # uncommitted lower UUIDv7
        with self.connect() as other:
            from corner import qualifications as q
            from uuid import uuid4
            newer = q.record_qualification(other, authority=self.authority, qualification_key=str(uuid4()),
                command=q.QualificationCommand(self.evaluation['id'], q.MinimumEVPolicy('test', d.Decimal('0.01')), datetime.now(timezone.utc)))
        unseen, _ = self.backend.discover(p.Partition('occurrence'), p.Traversal(), 1000)
        self.assertNotIn(late['id'], [x['candidate_id'] for x in unseen['items']])
        self.conn.commit()
        seen, _ = self.backend.discover(p.Partition('occurrence'), p.Traversal(), 1000)
        self.assertIn(late['id'], [x['candidate_id'] for x in seen['items']])

    def test_operation_budget_cancels_sql_without_leaving_transaction(self):
        self.poll_settings = replace(self.poll_settings, operation_seconds=.15)
        self.settings = replace(self.settings, statement_timeout=timedelta(milliseconds=100))
        self.backend = self.make_backend()
        started = time.monotonic()
        with self.assertRaises(p.OperationAborted):
            with self.backend._operation(lambda **kw: self.connect_role('worker', **kw)) as connect:
                conn = connect()
                try:
                    with conn.cursor() as cur: cur.execute('SELECT pg_sleep(5)')
                except psycopg2.Error:
                    # An attempted recovery connection must also respect the
                    # total operation budget; no misleading failure metadata.
                    connect()
        self.assertLess(time.monotonic() - started, 3)

    def test_execution_pass_reaches_fixed_tail_before_wrapping(self):
        first, second = self.enqueue(), self.enqueue()
        result, claims, after, ceiling = self.execute_one()
        self.assertEqual('completed', result['status'])
        self.assertEqual(first['id'], after)
        self.assertEqual(second['id'], ceiling)
        later = self.enqueue()
        result, claims, after, fence = self.execute_one(state=p.Traversal(after=after, ceiling=ceiling))
        self.assertEqual(second['id'], result['request_id'])
        self.assertIsNone(after)
        self.assertEqual(ceiling, fence)
        self.assertEqual('ready', self.execution(later)['status'])
        self.assertEqual(later['id'], self.execute_one()[0]['request_id'])

    def test_shutdown_grace_cancels_completion_and_reclaim_reuses_preparation(self):
        judgment = self.qualify(self.evaluation)
        request = self.enqueue(sources={'qualification_decision_id': judgment['id']}); self.conn.commit()
        self.poll_settings = replace(self.poll_settings, shutdown_grace=.1)
        self.backend = self.make_backend()
        original = d.complete
        def interrupted(conn, **kwargs):
            result = original(conn, **kwargs)
            # Domain result and completion are still uncommitted here.
            self.stop.request()
            with conn.cursor() as cur: cur.execute('SELECT pg_sleep(5)')
            return result
        with patch.object(d, 'complete', interrupted):
            with self.assertRaises(p.OperationAborted): self.execute_one()
        state = self.execution(request)
        self.assertEqual('leased', state['status'])
        with self.conn.cursor() as cur:
            cur.execute('SELECT id FROM corner.prepared_work_commands WHERE work_request_id=%s', (request['id'],))
            frozen_id = str(cur.fetchone()[0])
            cur.execute('SELECT count(*) FROM corner.opportunity_occurrences WHERE qualification_decision_id=%s', (judgment['id'],))
            self.assertEqual(0, cur.fetchone()[0])
        self.expire(request)
        self.stop = p.Stop(); self.backend = self.make_backend()
        result, claims, _, _ = self.execute_one()
        self.assertEqual('completed', result['status'])
        self.assertEqual([True], claims)
        self.assertEqual(frozen_id, result['execution']['prepared_command_id'])
