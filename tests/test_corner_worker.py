"""Bounded execution worker tests on disposable PostgreSQL and non-owner roles."""
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta, datetime, timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import psycopg2
from psycopg2 import sql

import test_corner_work as fixtures
import test_corner_reconciliation as discovery
from corner import worker as worker, work as w, reconciliation as r, qualifications as q


@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE') == '1' and os.getenv('CORNER_TEST_CONCURRENCY') == '1',
                     'opt-in disposable worker database')
class WorkerTests(fixtures.WorkDatabase, unittest.TestCase):
    select = fixtures.WorkTests.select
    evaluate = fixtures.WorkTests.evaluate
    qualify = fixtures.WorkTests.qualify
    register = fixtures.WorkTests.register
    capture = fixtures.WorkTests.capture
    command = fixtures.WorkTests.command
    record = fixtures.WorkTests.record
    app = fixtures.WorkTests.app
    opened = fixtures.WorkTests.opened
    sql_error = fixtures.WorkTests.sql_error
    enqueue = fixtures.WorkTests.enqueue
    claim = fixtures.WorkTests.claim
    prepare = fixtures.WorkTests.prepare
    execution = fixtures.WorkTests.execution
    expire = fixtures.WorkTests.expire
    routed = discovery.ReconciliationTests.routed
    item = discovery.ReconciliationTests.item

    def setUp(self):
        fixtures.WorkTests.setUp(self)
        self.settings = worker.WorkerSettings('worker-a', self.authority, timedelta(seconds=60),
                                              timedelta(seconds=1), 2, timedelta(seconds=10))
        self.conn.commit()

    def runtime_connect(self):
        conn = self.connect()
        with conn.cursor() as cur:
            cur.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(self.roles['worker'])))
        conn.commit()
        return conn

    def run_request(self, request, **kwargs):
        self.conn.commit()
        return worker.run_once(self.runtime_connect, settings=kwargs.pop('settings', self.settings),
                               request_id=request['id'], **kwargs)

    def discover(self, kind, identity):
        report = r.sweep(self.conn, obligation=kind, **({'channel_id': self.channel['id']} if kind != 'occurrence' else {}))
        request_id = self.item(report, identity)['request_id']
        self.conn.commit()
        return {'id': request_id}

    def lifecycle_request(self, kind, evidence=None):
        from corner import lifecycle_store as ls
        evidence = evidence or {'evaluation': self.evaluation, 'qualification': self.judgment,
                               'assessment': self.assessment, 'generation_activation': self.activation}[kind]
        from corner import evaluations as ev
        return w.enqueue(self.conn, kind='apply_lifecycle', namespace=self.authority.identifier, key=str(uuid4()),
                         sources={'condition_id': self.condition['id'], 'generation_id': self.generation['id'],
                                  ls._SOURCE_COLUMNS[kind]: evidence['id']}, intent_json=ev.canonical_json({'command_kind': kind}))

    def test_occurrence_worker_completes_and_reconciliation_observes_it(self):
        judgment = self.qualify(self.evaluation)
        request = self.discover('occurrence', judgment['id'])
        result = self.run_request(request)
        self.assertEqual('completed', result['status'])
        report = r.sweep(self.conn, obligation='occurrence')
        self.assertEqual('fulfilled', self.item(report, judgment['id'])['status'])
        self.assertEqual('idle', self.run_request(request)['status'])

    def test_qualification_worker_uses_pinned_policy_and_reconciliation_fulfills(self):
        route, evaluation = self.routed()
        request = self.discover('qualification', route['id'])
        result = self.run_request(request)
        self.assertEqual('completed', result['status'])
        frozen = w.load_prepared(self.conn, request_id=request['id'])['command_snapshot']
        self.assertEqual('0.01', frozen['payload']['policy']['minimum_ev_ratio'])
        self.assertEqual(evaluation['engine_evaluation_id'], frozen['payload']['engine_evaluation_id'])
        report = r.sweep(self.conn, obligation='qualification', channel_id=self.channel['id'])
        self.assertEqual('fulfilled', self.item(report, route['id'])['status'])

    def test_not_qualified_and_not_qualifiable_are_successful_completion(self):
        negative_gen = self.register(replace(self.configuration, qualification_policy=q.MinimumEVPolicy('test-policy', Decimal('.99'))))
        for gen, time, expected in ((negative_gen, None, 'not_qualified'),
                                    (self.generation, self.time + timedelta(days=1), 'not_qualifiable')):
            route, _ = self.routed(generation=gen, evaluated_at=time)
            request = self.discover('qualification', route['id'])
            result = self.run_request(request)
            self.assertEqual('completed', result['status'])
            with self.conn.cursor() as cur:
                cur.execute('SELECT decision_kind FROM corner.qualification_decisions WHERE id=%s',
                            (result['execution']['qualification_decision_id'],))
                self.assertEqual(expected, cur.fetchone()[0])

    def test_activation_and_duplicate_lifecycle_outcomes_complete(self):
        request = self.discover('activation', self.condition['id'])
        result = self.run_request(request)
        self.assertEqual('completed', result['status'])
        self.assertEqual('fulfilled', self.item(r.sweep(self.conn, obligation='activation', channel_id=self.channel['id']),
                                               self.condition['id'])['status'])
        first = self.lifecycle_request('evaluation')
        self.assertEqual('completed', self.run_request(first)['status'])
        duplicate = self.lifecycle_request('evaluation')
        result = self.run_request(duplicate)
        with self.conn.cursor() as cur:
            cur.execute('SELECT application_outcome FROM corner.lifecycle_applications WHERE id=%s',
                        (result['execution']['lifecycle_application_id'],))
            self.assertEqual('already_reflected', cur.fetchone()[0])

    def test_uninitialized_condition_waits_then_explicit_resume_completes(self):
        request = self.lifecycle_request('evaluation')
        result = self.run_request(request)
        self.assertEqual(('waiting', 'condition_uninitialized'), (result['status'], result['reason']))
        self.assertIsNone(w.load_prepared(self.conn, request_id=request['id']))
        self.assertEqual('idle', self.run_request(request)['status'])
        activation = self.discover('activation', self.condition['id'])
        self.assertEqual('completed', self.run_request(activation)['status'])
        w.resume(self.conn, request_id=request['id'], expected_status='waiting', available_at=datetime.now(timezone.utc))
        self.assertEqual('completed', self.run_request(request)['status'])

    def test_missing_occurrence_waits_without_creating_it_as_side_effect(self):
        self.app('generation_activation')
        judgment = self.qualify(self.evaluation)
        request = self.lifecycle_request('qualification', judgment)
        result = self.run_request(request)
        self.assertEqual(('waiting', 'qualified_occurrence_missing'), (result['status'], result['reason']))
        occurrence = self.discover('occurrence', judgment['id'])
        self.assertEqual('completed', self.run_request(occurrence)['status'])
        w.resume(self.conn, request_id=request['id'], expected_status='waiting', available_at=datetime.now(timezone.utc))
        self.assertEqual('completed', self.run_request(request)['status'])

    def test_assessment_capture_is_not_claimed(self):
        for kind in ('assess',):
            request = self.enqueue(kind, sources={'condition_id': self.condition['id'], 'generation_id': self.generation['id'],
                                                  'qualification_decision_id': self.judgment['id']})
            self.assertEqual('idle', self.run_request(request)['status'])
            self.assertEqual('ready', self.execution(request)['status'])
            self.assertEqual(0, self.execution(request)['claim_count'])

    def test_process_crash_after_preparation_is_reclaimed_without_rebuilding(self):
        route, _ = self.routed()
        request = self.discover('qualification', route['id'])
        with patch.object(worker, '_complete', side_effect=SystemExit('simulated crash')):
            with self.assertRaises(SystemExit): self.run_request(request)
        prepared = w.load_prepared(self.conn, request_id=request['id'])
        self.assertIsNotNone(prepared)
        self.expire(request)
        with patch.object(worker, '_build', side_effect=AssertionError('no command regeneration')):
            result = self.run_request(request, settings=replace(self.settings, owner='worker-b'))
        self.assertEqual('completed', result['status'])
        self.assertEqual(prepared, w.load_prepared(self.conn, request_id=request['id']))

    def test_process_crash_after_claim_leaves_reclaimable_lease(self):
        request = self.enqueue()
        with patch.object(worker, '_prepare', side_effect=SystemExit('simulated crash')):
            with self.assertRaises(SystemExit): self.run_request(request)
        self.assertIsNone(w.load_prepared(self.conn, request_id=request['id']))
        self.expire(request)
        self.assertEqual('completed', self.run_request(request)['status'])
        self.assertEqual(2, self.execution(request)['claim_count'])

    def test_stale_preparation_token_cannot_write_or_record_failure(self):
        request = self.enqueue()
        replacement = {}
        original = worker._prepare
        def reclaimed(conn, lease, settings):
            self.expire(request)
            replacement.update(self.claim(request, owner='worker-b'))
            self.conn.commit()
            return original(conn, lease, settings)
        with patch.object(worker, '_prepare', side_effect=reclaimed):
            result = self.run_request(request)
        self.assertEqual('lease_lost', result['status'])
        self.assertEqual(replacement['lease_token'], self.execution(request)['lease_token'])
        self.assertIsNone(self.execution(request)['last_error_code'])
        self.assertIsNone(w.load_prepared(self.conn, request_id=request['id']))

    def test_stale_completion_cannot_publish_domain_result_or_failure(self):
        judgment = self.qualify(self.evaluation)
        request = self.discover('occurrence', judgment['id'])
        original = worker._complete
        def reclaimed(conn, lease, settings):
            self.expire(request)
            self.claim(request, owner='worker-b')
            self.conn.commit()
            return original(conn, lease, settings)
        with patch.object(worker, '_complete', side_effect=reclaimed):
            result = self.run_request(request)
        self.assertEqual('lease_lost', result['status'])
        self.assertIsNone(self.execution(request)['last_error_code'])
        with self.conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM corner.opportunity_occurrences WHERE qualification_decision_id=%s', (judgment['id'],))
            self.assertEqual(0, cur.fetchone()[0])

    def test_transient_database_failure_retries_same_preparation(self):
        request = self.enqueue()
        def transient(conn, document):
            with conn.cursor() as cur:
                cur.execute("DO $$ BEGIN RAISE EXCEPTION 'test transient' USING ERRCODE='40001'; END $$")
        with patch.object(w, '_dispatch', side_effect=transient):
            result = self.run_request(request)
        self.assertEqual('retryable', result['status'])
        frozen = w.load_prepared(self.conn, request_id=request['id'])
        self.assertEqual(1, self.execution(request)['retry_count'])
        with self.conn.cursor() as cur:
            cur.execute('UPDATE corner.work_executions SET available_at=clock_timestamp() WHERE work_request_id=%s', (request['id'],))
        with patch.object(worker, '_build', side_effect=AssertionError('no rebuild')):
            self.assertEqual('completed', self.run_request(request)['status'])
        self.assertEqual(frozen, w.load_prepared(self.conn, request_id=request['id']))

    def test_retry_budget_exhaustion_blocks(self):
        request = self.enqueue()
        with patch.object(w, '_dispatch', side_effect=psycopg2.OperationalError('simulated connection failure')):
            result = self.run_request(request, settings=replace(self.settings, max_retries=0))
        self.assertEqual(('blocked', 'retry_limit_reached'), (result['status'], result['reason']))

    def test_invalid_immutable_intent_blocks_without_fabricated_policy(self):
        request = self.enqueue('qualify')  # no pinned generation/policy
        result = self.run_request(request)
        self.assertEqual(('blocked', 'invalid_command_or_evidence'), (result['status'], result['reason']))
        self.assertIsNone(w.load_prepared(self.conn, request_id=request['id']))

    def test_unsupported_implementation_blocks_frozen_command(self):
        request = self.enqueue()
        with patch.object(worker, '_complete', side_effect=SystemExit()):
            with self.assertRaises(SystemExit): self.run_request(request)
        frozen = w.load_prepared(self.conn, request_id=request['id'])
        self.expire(request)
        with patch.object(w, 'OCCURRENCE_REVISION', 'unavailable-build'):
            result = self.run_request(request)
        self.assertEqual(('blocked', 'implementation_unavailable'), (result['status'], result['reason']))
        self.assertEqual(frozen, w.load_prepared(self.conn, request_id=request['id']))
        w.resume(self.conn, request_id=request['id'], expected_status='blocked', available_at=datetime.now(timezone.utc))
        with patch.object(worker, '_build', side_effect=AssertionError('no reprepare on resume')):
            self.assertEqual('completed', self.run_request(request)['status'])
        self.assertEqual(frozen, w.load_prepared(self.conn, request_id=request['id']))

    def test_wrong_frozen_policy_is_blocked_not_rewritten(self):
        route, evaluation = self.routed()
        request = self.discover('qualification', route['id'])
        lease = self.claim(request)
        frozen = w.prepare(self.conn, request_id=request['id'], owner=lease['lease_owner'], token=lease['lease_token'],
                           authority=self.authority, domain_key='wrong-policy',
                           command=q.QualificationCommand(evaluation['engine_evaluation_id'],
                           q.MinimumEVPolicy('test-policy', Decimal('.99')), self.time))
        self.expire(request)
        result = self.run_request(request)
        self.assertEqual('blocked', result['status'])
        self.assertEqual(frozen, w.load_prepared(self.conn, request_id=request['id']))

    def test_ignored_activation_is_completed_work_without_becoming_applied(self):
        from corner import channels as ch
        self.app('generation_activation')
        second = self.register()
        ch.activate_generation(self.conn, authority=self.authority, activation_key='second',
                               command=ch.ActivationCommand(self.channel['id'], second['id'], self.generation['id'], self.time))
        third = self.register()
        activation = ch.activate_generation(self.conn, authority=self.authority, activation_key='third',
                                            command=ch.ActivationCommand(self.channel['id'], third['id'], second['id'], self.time))
        request = w.enqueue(self.conn, kind='apply_lifecycle', namespace=self.authority.identifier, key='out-of-order',
            sources={'condition_id': self.condition['id'], 'generation_id': third['id'], 'channel_generation_activation_id': activation['id']},
            intent_json='{"command_kind":"generation_activation"}')
        result = self.run_request(request)
        self.assertEqual('completed', result['status'])
        with self.conn.cursor() as cur:
            cur.execute('SELECT application_outcome FROM corner.lifecycle_applications WHERE id=%s',
                        (result['execution']['lifecycle_application_id'],))
            self.assertEqual('ignored', cur.fetchone()[0])

    def test_stale_worker_error_cannot_replace_new_owners_metadata(self):
        request = self.enqueue()
        def old_failure(conn, lease, settings):
            self.expire(request)
            self.claim(request, owner='worker-b')
            self.conn.commit()
            raise ValueError('old worker fails after reclaim')
        with patch.object(worker, '_complete', side_effect=old_failure):
            self.assertEqual('lease_lost', self.run_request(request)['status'])
        self.assertEqual('worker-b', self.execution(request)['lease_owner'])
        self.assertIsNone(self.execution(request)['last_error_code'])

    def test_domain_insert_and_failed_completion_roll_back_before_failure_record(self):
        judgment = self.qualify(self.evaluation)
        request = self.discover('occurrence', judgment['id'])
        with patch.object(w, '_result_matches', side_effect=w.WorkValidationError('injected result verification failure')):
            self.assertEqual('blocked', self.run_request(request)['status'])
        with self.conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM corner.opportunity_occurrences WHERE qualification_decision_id=%s', (judgment['id'],))
            self.assertEqual(0, cur.fetchone()[0])
        self.assertEqual('invalid_command_or_evidence', self.execution(request)['last_error_code'])

    def test_lost_completion_ack_is_recovered_without_dispatching_twice(self):
        request = self.enqueue()
        self.conn.commit()
        calls = {'connections': 0}
        class LostAck:
            def __init__(proxy, conn): proxy.conn = conn
            def __getattr__(proxy, key): return getattr(proxy.conn, key)
            def commit(proxy):
                proxy.conn.commit()
                raise psycopg2.OperationalError('lost commit acknowledgement')
        def factory():
            calls['connections'] += 1
            conn = self.runtime_connect()
            return LostAck(conn) if calls['connections'] == 3 else conn
        original = w._dispatch
        with patch.object(w, '_dispatch', wraps=original) as dispatch:
            result = worker.run_once(factory, settings=self.settings, request_id=request['id'])
        self.assertEqual('completed', result['status'])
        self.assertEqual(1, dispatch.call_count)
        self.assertIsNone(self.execution(request)['last_error_code'])

    def test_concurrent_workers_only_one_claims_the_request(self):
        request = self.enqueue()
        self.conn.commit()
        barrier = threading.Barrier(2)
        def run(owner):
            barrier.wait(timeout=10)
            return worker.run_once(self.runtime_connect, settings=replace(self.settings, owner=owner), request_id=request['id'])
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, ('worker-a', 'worker-b')))
        self.assertEqual({'completed', 'idle'}, {result['status'] for result in results})
        self.assertEqual(1, self.execution(request)['claim_count'])

    def test_completion_lock_remains_valid_past_lease_expiry(self):
        request = self.enqueue()
        self.conn.commit()
        original = w._dispatch
        def slow(conn, document):
            with conn.cursor() as cur:
                cur.execute("UPDATE corner.work_executions SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE work_request_id=%s", (request['id'],))
            # Another real connection must skip the protected row.
            other = self.runtime_connect()
            try:
                self.assertIsNone(w.claim(other, owner='worker-b', lease_for=timedelta(seconds=60), request_id=request['id']))
                other.commit()
            finally: other.close()
            return original(conn, document)
        with patch.object(w, '_dispatch', side_effect=slow):
            self.assertEqual('completed', self.run_request(request)['status'])

    def test_no_current_quote_capture_or_engine_evaluation(self):
        route, _ = self.routed()
        request = self.discover('qualification', route['id'])
        with (patch('corner.assessments.capture_assessment', side_effect=AssertionError('no capture')),
              patch('corner.ev_selection.select_ev_snapshot', side_effect=AssertionError('no selection')),
              patch('corner.ev.evaluate_ev', side_effect=AssertionError('no EV recomputation'))):
            self.assertEqual('completed', self.run_request(request)['status'])
