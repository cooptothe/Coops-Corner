"""Health claims are read-only, version-aware and honest about telemetry gaps."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from corner import health as h, polling, channels, lifecycle_versions as ls
import test_corner_worker as fixtures
import test_corner_v2_assessments as v2
from test_corner_work import WorkDatabase


class HealthUnitTests(unittest.TestCase):
    def test_deadline_equality_respects_inclusive_vs_exclusive(self):
        at = datetime(2026, 9, 28, tzinfo=timezone.utc)
        quote = h.Deadline('target', 'x', at, True)
        approval = h.Deadline('approval', 'y', at, False)
        self.assertFalse(quote.passed(at))
        self.assertTrue(quote.passed(at + timedelta(microseconds=1)))
        self.assertTrue(approval.passed(at))

    def test_v2_decodes_authority_without_reusing_expired_adverse_rules(self):
        cap, at, judgment, policy = v2.synthetic()
        result = v2.pure.assess(cap, at, judgment, policy)
        result['authority']['deadlines'].append({'kind': 'rules', 'stream': 'test', 'record_id': 'old',
            'valid_from': at.isoformat(), 'valid_until': at.isoformat(), 'end_inclusive': False})
        row = dict(id='assessment', snapshot_format_version=h.a2.FORMAT, result_snapshot=result, assessed_at=at)
        deadlines = h.assessment_deadlines(row)
        self.assertTrue({'target', 'reference', 'phase'} <= {d.kind for d in deadlines})
        self.assertNotIn('old', [d.evidence_id for d in deadlines])

    def test_unknown_format_and_naive_deadlines_fail_validation(self):
        with self.assertRaises(h.HealthEvidenceError): h.assessment_deadlines({'snapshot_format_version': 'unknown', 'result_snapshot': {}})
        with self.assertRaises(h.HealthEvidenceError): h._instant('2026-09-28T10:00:00')

    def test_process_telemetry_is_explicitly_local_and_resets(self):
        part = polling.Partition('occurrence')
        poller = SimpleNamespace(clock=lambda: 100, totals={'reconciliation_invalid': 7},
            discovery={part: polling.Traversal(passes=3, last_visit=99, last_pass=90)})
        first = h.process_telemetry(poller, process_instance_id='process-a')
        self.assertEqual('ephemeral_process_local', first.retention)
        self.assertEqual(7, first.current_process_reconciliation_invalid_count)
        self.assertEqual(10, first.current_process_partition_visit_state[0].current_process_last_scan_completed_age_seconds)
        poller.totals = {'reconciliation_invalid': 0}; poller.discovery = {part: polling.Traversal()}
        second = h.process_telemetry(poller, process_instance_id='process-b')
        self.assertEqual(0, second.current_process_reconciliation_invalid_count)
        self.assertIsNone(second.current_process_partition_visit_state[0].current_process_last_visit_age_seconds)
        self.assertEqual(7, first.current_process_reconciliation_invalid_count)

    def test_thresholds_are_explicit_and_carry_action_not_repair(self):
        threshold = h.Threshold('blocked_count', 1, 10)
        self.assertEqual('normal', threshold.classify(0)[0])
        self.assertEqual('warning', threshold.classify(1)[0])
        self.assertEqual('critical', threshold.classify(10)[0])
        self.assertIn('do not automatically retry', threshold.classify(10)[1])
        with self.assertRaises(ValueError): h.Threshold('waiting_age', 1, 2)
        with self.assertRaises(ValueError): h.HealthLimits(max_conditions=0)


@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE') == '1' and os.getenv('CORNER_TEST_CONCURRENCY') == '1', 'disposable health database')
class HealthDatabaseTests(WorkDatabase, unittest.TestCase):
    for _name in ('select', 'evaluate', 'qualify', 'register', 'capture', 'command', 'record', 'app', 'opened',
                  'sql_error', 'enqueue', 'claim', 'prepare', 'execution', 'expire', 'routed'):
        locals()[_name] = getattr(fixtures.WorkerTests, _name)

    def setUp(self):
        fixtures.WorkerTests.setUp(self)

    def reader(self, **kwargs):
        conn = psycopg2.connect(**dict(self.connection_config, **kwargs))
        with conn.cursor() as cur: cur.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(self.roles['reader'])))
        conn.commit()
        return conn

    def health(self, **kwargs):
        self.conn.commit()
        return h.read_health(self.reader, **kwargs)

    def mine(self, snapshot):
        return next(c for c in snapshot.domain.conditions if c.condition_id == self.condition['id'])

    def test_queue_definitions_include_equality_and_exclude_future_retry(self):
        at = datetime.now(timezone.utc)
        requests = [self.enqueue() for _ in range(5)]
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            before = h.queue_health(cur, at, timedelta(minutes=5))
            for request, state in zip(requests[:4], ('waiting', 'blocked', 'retryable', 'retryable')):
                cur.execute('''UPDATE corner.work_executions SET status=%s,waiting_reason=%s,blocked_reason=%s,
                    available_at=%s,updated_at=%s WHERE work_request_id=%s''',
                    (state, 'test' if state == 'waiting' else None, 'test' if state == 'blocked' else None,
                     at + timedelta(days=1) if request == requests[3] else at, at, request['id']))
            self.claim(requests[4])
            cur.execute('UPDATE corner.work_executions SET lease_expires_at=%s WHERE work_request_id=%s', (at, requests[4]['id']))
            after = h.queue_health(cur, at, timedelta(minutes=5))
        self.assertEqual(before.waiting_count + 1, after.waiting_count)
        self.assertEqual(before.blocked_count + 1, after.blocked_count)
        self.assertEqual(before.due_retryable_count + 1, after.due_retryable_count)
        self.assertEqual(before.expired_lease_count + 1, after.expired_lease_count)
        self.assertIsNotNone(after.oldest_waiting_last_updated_at)

    def test_completion_window_is_open_start_closed_end(self):
        from corner import work
        at = datetime.now(timezone.utc)
        for offset in (-60, 0, 1):
            request = self.enqueue(); lease = self.claim(request); self.prepare(request, lease)
            work.complete(self.conn, request_id=request['id'], owner=lease['lease_owner'], token=lease['lease_token'])
            with self.conn.cursor() as cur:
                cur.execute('UPDATE corner.work_executions SET completed_at=%s WHERE work_request_id=%s',
                            (at + timedelta(seconds=offset), request['id']))
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            count = h.queue_health(cur, at, timedelta(seconds=60))
        self.assertEqual(1, count.completion_count)
        self.assertEqual(1/60, count.completion_throughput_per_second)

    def test_authoritative_activation_lag_survives_projection_deletion(self):
        self.app('generation_activation')
        previous = self.generation
        for _ in range(2):
            following = self.register()
            channels.activate_generation(self.conn, authority=self.authority, activation_key=str(uuid4()),
                command=channels.ActivationCommand(self.channel['id'], following['id'], previous['id'], self.time))
            previous = following
        before = self.mine(self.health())
        self.assertEqual(2, before.missing_activation_count)
        self.assertEqual(self.activation['id'], before.processed_activation_id)
        with self.conn.cursor() as cur:
            cur.execute('DELETE FROM corner.condition_processing_projections WHERE condition_id=%s', (self.condition['id'],))
            cur.execute('DELETE FROM corner.opportunities WHERE condition_id=%s', (self.condition['id'],))
        self.assertEqual(before, self.mine(self.health()))

    def test_uninitialized_condition_reports_first_required_activation(self):
        item = self.mine(self.health())
        self.assertIsNone(item.processed_activation_id)
        self.assertEqual(self.activation['id'], item.next_required_activation_id)
        self.assertEqual(1, item.missing_activation_count)

    def test_ignored_activation_receipt_does_not_fulfill_progress(self):
        self.app('generation_activation')
        previous = self.generation
        successors = []
        for _ in range(2):
            following = self.register()
            activation = channels.activate_generation(self.conn, authority=self.authority, activation_key=str(uuid4()),
                command=channels.ActivationCommand(self.channel['id'], following['id'], previous['id'], self.time))
            successors.append((following, activation))
            previous = following
        generation, activation = successors[-1]
        ignored = self.app('generation_activation', activation, generation=generation)
        self.assertEqual('ignored', ignored['application_outcome'])
        item = self.mine(self.health())
        self.assertEqual(ignored['id'], item.last_application_id)
        self.assertEqual(self.activation['id'], item.processed_activation_id)
        self.assertEqual(successors[0][1]['id'], item.next_required_activation_id)
        self.assertEqual(2, item.missing_activation_count)

    def test_snapshot_uses_utc_and_closes_its_reader_connection(self):
        connections = []
        def factory(**kwargs):
            conn = self.reader(**kwargs)
            with conn.cursor() as cur: cur.execute("SET TIME ZONE 'America/Chicago'")
            conn.commit()
            connections.append(conn)
            return conn
        snapshot = h.read_health(factory)
        self.assertEqual(timedelta(0), snapshot.database_wall_clock_at.utcoffset())
        self.assertEqual(timedelta(0), snapshot.queue.completion_interval_start.utcoffset())
        self.assertTrue(connections[0].closed)

    def test_invalid_connection_is_rejected_and_closed_without_reading_health(self):
        conn = self.reader()
        conn.autocommit = True
        with patch.object(h, 'queue_health', side_effect=AssertionError('must not read')):
            with self.assertRaises(ValueError): h.read_health(lambda **kwargs: conn)
        self.assertTrue(conn.closed)

    def test_accepted_basis_not_latest_persisted_assessment_and_no_projection_dependency(self):
        self.opened()
        newer = self.record(self.command(basis_assessment_id=self.assessment['id']), key='accepted')
        self.app('assessment', newer)
        obsolete = self.record(replace(self.command(), assessed_at=newer['assessed_at'] + timedelta(days=36501)), key='obsolete')
        self.app('assessment', obsolete)
        snapshot = self.health()
        item = self.mine(snapshot)
        self.assertEqual(newer['id'], item.accepted_assessment_id)
        self.assertIsNotNone(item.open_episode_id)
        at = datetime.fromisoformat(newer['result_snapshot']['target_deadline']) + timedelta(microseconds=1)
        with self.conn.cursor() as cur:
            cur.execute('DELETE FROM corner.condition_processing_projections WHERE condition_id=%s', (self.condition['id'],))
            cur.execute('DELETE FROM corner.opportunities WHERE condition_id=%s', (self.condition['id'],))
        self.conn.commit()
        conn = self.reader()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                domain = h._domain(cur, at, h.HealthLimits())
            current = next(c for c in domain.conditions if c.condition_id == self.condition['id'])
            self.assertTrue(current.overdue_deadlines)
            self.assertEqual(newer['id'], current.accepted_assessment_id)
        finally: conn.close()
        self.assertEqual('unsupported', snapshot.coverage.assessment_deadline_discovery)

    def test_reader_snapshot_cannot_write_or_take_writer_locks(self):
        self.opened(); self.conn.commit()
        original = h._domain
        def verified(cur, *args):
            cur.execute('SHOW transaction_read_only'); self.assertEqual('on', cur.fetchone()['transaction_read_only'])
            cur.execute('SELECT pg_current_xact_id_if_assigned() AS xid'); self.assertIsNone(cur.fetchone()['xid'])
            result = original(cur, *args)
            cur.execute('SELECT pg_current_xact_id_if_assigned() AS xid'); self.assertIsNone(cur.fetchone()['xid'])
            return result
        with patch.object(h, '_domain', verified): self.health()
        def forbidden(cur, *args):
            cur.execute("UPDATE corner.work_executions SET status=status")
        with patch.object(h, '_domain', forbidden):
            with self.assertRaises(psycopg2.Error) as error: self.health()
        self.assertIn(error.exception.pgcode, ('25006', '42501'))

    def test_corrupt_history_and_limit_do_not_return_partial_green_snapshot(self):
        self.opened(); self.conn.commit()
        with patch.object(ls, '_verify_receipt', side_effect=ValueError('digest mismatch')):
            with self.assertRaises(h.HealthEvidenceError): self.health()
        with self.assertRaises(h.HealthLimitExceeded):
            self.health(limits=h.HealthLimits(max_applications_per_condition=1))

    def test_expired_lease_is_observable_while_writer_holds_row_lock(self):
        request = self.enqueue(); self.claim(request); self.expire(request); self.conn.commit()
        before = self.health().queue.expired_lease_count
        with self.conn.cursor() as cur:
            cur.execute('SELECT 1 FROM corner.work_executions WHERE work_request_id=%s FOR UPDATE', (request['id'],))
        # Do not use self.health(), which commits the lock-owning fixture connection.
        snapshot = h.read_health(self.reader)
        self.assertEqual(before, snapshot.queue.expired_lease_count)
        self.assertGreaterEqual(before, 1)
        self.conn.rollback()

    def test_snapshot_does_not_mix_a_concurrently_committed_activation(self):
        self.app('generation_activation')
        following = self.register(); self.conn.commit()
        original = h.queue_health
        def activate_after_queue(cur, at, interval):
            result = original(cur, at, interval)
            with self.connect() as other:
                channels.activate_generation(other, authority=self.authority, activation_key=str(uuid4()),
                    command=channels.ActivationCommand(self.channel['id'], following['id'], self.generation['id'], self.time))
            return result
        with patch.object(h, 'queue_health', activate_after_queue):
            self.assertEqual(0, self.mine(self.health()).missing_activation_count)
        self.assertEqual(1, self.mine(self.health()).missing_activation_count)


@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE') == '1' and os.getenv('CORNER_TEST_CONCURRENCY') == '1', 'disposable v2 health database')
class V2HealthTests(WorkDatabase, unittest.TestCase):
    for _name in ('select', 'append', 'runtime_connect', 'expire', 'register', 'setUp', 'command', 'record', 'opened', 'app', 'withdrawal'):
        locals()[_name] = getattr(v2.V2AssessmentDatabaseTests, _name)
    reader = HealthDatabaseTests.reader

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with cls.connect() as conn:
            with conn.cursor() as cur:
                cur.execute((Path(__file__).resolve().parents[1]/'db/migrations/013_corner_v2_actionability_reasons.sql').read_text())

    def test_v2_authority_deadlines_and_negative_closure(self):
        assessment, receipt = self.opened(); self.conn.commit()
        first = h.read_health(self.reader)
        item = next(c for c in first.domain.conditions if c.condition_id == self.condition['id'])
        self.assertIsNotNone(item.open_episode_id)
        self.assertEqual(assessment['id'], item.accepted_assessment_id)
        deadlines = h.assessment_deadlines(assessment)
        self.assertIn('phase', {d.kind for d in deadlines})
        negative = self.record(self.command(assessment['id'], self.withdrawal()))
        self.app('assessment', negative['id']); self.conn.commit()
        last = h.read_health(self.reader)
        item = next(c for c in last.domain.conditions if c.condition_id == self.condition['id'])
        self.assertIsNone(item.open_episode_id)
        self.assertEqual((), item.overdue_deadlines)
