"""Evaluate capture under expiring leases; real snapshots, roles and connections."""
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import test_corner_worker as fixtures
import test_corner_ev_selection as selection_tests
from test_corner_work import WorkDatabase
from corner import evaluation_capture as ec, ev_selection, evaluations as ev, lifecycle, reconciliation as r
from corner import worker, work as w


@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE') == '1' and os.getenv('CORNER_TEST_CONCURRENCY') == '1',
                     'opt-in disposable evaluate worker database')
class EvaluationWorkerTests(WorkDatabase, unittest.TestCase):
    select = fixtures.WorkerTests.select
    evaluate = fixtures.WorkerTests.evaluate
    qualify = fixtures.WorkerTests.qualify
    register = fixtures.WorkerTests.register
    capture = fixtures.WorkerTests.capture
    command = fixtures.WorkerTests.command
    record = fixtures.WorkerTests.record
    app = fixtures.WorkerTests.app
    opened = fixtures.WorkerTests.opened
    sql_error = fixtures.WorkerTests.sql_error
    runtime_connect = fixtures.WorkerTests.runtime_connect
    expire = fixtures.WorkerTests.expire
    execution = fixtures.WorkerTests.execution
    item = fixtures.WorkerTests.item
    append = selection_tests.EVSelectionTests.append

    def setUp(self):
        fixtures.WorkerTests.setUp(self)
        # Explicitly synthetic long ages; no production freshness claim.
        self.config = replace(self.config, target_max_age=timedelta(days=36500), reference_max_age=timedelta(days=36500))
        self.configuration = replace(self.configuration, engine_configuration=self.config)
        self.generation = self.register()
        self.validator_id = lifecycle.ImplementationIdentity('synthetic.market-validation', '1', 'synthetic-test-only')
        self.validator = ec.ValidationAdapter(self.validator_id, lambda conn, condition, at: self.validation)
        self.conn.commit()

    def request(self, *, intent=None):
        intent = intent if intent is not None else ec.request_intent(outcome_id=self.outcome_id,
                              sportsbook_id=self.book_id, validation_adapter=self.validator_id)
        result = w.enqueue(self.conn, kind='evaluate', namespace=self.authority.identifier, key=str(uuid4()),
                           sources={'condition_id': self.condition['id'], 'generation_id': self.generation['id']},
                           intent_json=ev.canonical_json(intent))
        self.conn.commit()
        return result

    def run_request(self, request, *, validator=True, settings=None):
        self.conn.commit()
        return worker.run_once(self.runtime_connect, settings=settings or self.settings, request_id=request['id'],
                               evaluation_validator=self.validator if validator is True else validator)

    def crash_after_capture(self, request):
        with patch.object(worker, '_complete', side_effect=SystemExit('crash before evaluation')):
            with self.assertRaises(SystemExit): self.run_request(request)
        return w.load_prepared(self.conn, request_id=request['id'])

    def test_capture_evaluates_and_preserves_assignment_for_reconciliation(self):
        request = self.request()
        result = self.run_request(request)
        self.assertEqual('completed', result['status'], result)
        prepared = w.load_prepared(self.conn, request_id=request['id'])
        payload = prepared['command_snapshot']['payload']
        self.assertEqual(self.target_id, payload['snapshot']['target_observation_id'])
        self.assertEqual(ec.FORMAT, payload['context']['selection']['selector']['format'])
        self.assertEqual(self.validation.phase_evidence, payload['snapshot']['phase_evidence'])
        report = r.sweep(self.conn, obligation='qualification', channel_id=self.channel['id'])
        self.assertEqual('newly_requested', self.item(report, request['id'])['status'])
        with self.conn.cursor() as cur:
            cur.execute('SELECT result_kind FROM corner.engine_evaluations WHERE id=%s', (result['execution']['engine_evaluation_id'],))
            self.assertEqual('evaluated', cur.fetchone()[0])

    def test_market_changes_after_preparation_do_not_recapture_on_reclaim(self):
        request = self.request()
        frozen = self.crash_after_capture(request)
        newer = self.append(self.target_id, price='1.05', observed_at=datetime.now(timezone.utc))
        self.expire(request)
        with patch.object(ev_selection, 'select_ev_snapshot', side_effect=AssertionError('no recapture')):
            result = self.run_request(request, validator=None, settings=replace(self.settings, owner='worker-b'))
        self.assertEqual('completed', result['status'], result)
        self.assertEqual(frozen, w.load_prepared(self.conn, request_id=request['id']))
        with self.conn.cursor() as cur:
            cur.execute('SELECT target_observation_id,command_snapshot FROM corner.engine_evaluations WHERE id=%s',
                        (result['execution']['engine_evaluation_id'],))
            target, command = cur.fetchone()
        self.assertEqual(self.target_id, target)
        self.assertNotEqual(newer, target)
        self.assertEqual(frozen['command_snapshot']['payload'], command)

    def test_lease_expires_during_selection_stale_worker_cannot_freeze(self):
        request = self.request()
        original = ev_selection.select_ev_snapshot
        def expires(conn, **kwargs):
            selected = original(conn, **kwargs)
            self.expire(request)
            self.conn.commit()
            return selected
        with patch.object(ev_selection, 'select_ev_snapshot', side_effect=expires):
            result = self.run_request(request)
        self.assertEqual('lease_lost', result['status'])
        self.assertIsNone(w.load_prepared(self.conn, request_id=request['id']))
        self.assertIsNone(self.execution(request)['last_error_code'])

    def test_reclaimer_captures_newer_evidence_while_old_selector_is_paused(self):
        request = self.request()
        captured, release = threading.Event(), threading.Event()
        original = ev_selection.select_ev_snapshot
        local = threading.local()
        def slow(conn, **kwargs):
            selected = original(conn, **kwargs)
            if getattr(local, 'old', False):
                captured.set()
                if not release.wait(timeout=15): raise AssertionError('replacement did not finish')
            return selected
        def old():
            local.old = True
            return worker.run_once(self.runtime_connect, settings=self.settings, request_id=request['id'], evaluation_validator=self.validator)
        with patch.object(ev_selection, 'select_ev_snapshot', side_effect=slow), ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(old)
            try:
                self.assertTrue(captured.wait(timeout=10))
                newer = self.append(self.target_id, price='2.50', observed_at=datetime.now(timezone.utc))
                self.expire(request)
                self.conn.commit()
                replacement = self.run_request(request, settings=replace(self.settings, owner='worker-b'))
                self.assertEqual('completed', replacement['status'], replacement)
            finally:
                release.set()
            old_result = future.result(timeout=10)
        # The old worker may observe B's completed result during read-only recovery.
        self.assertEqual('completed', old_result['status'])
        self.assertEqual(replacement['execution']['engine_evaluation_id'], old_result['execution']['engine_evaluation_id'])
        frozen = w.load_prepared(self.conn, request_id=request['id'])
        self.assertEqual(newer, frozen['command_snapshot']['payload']['snapshot']['target_observation_id'])
        self.assertIsNone(self.execution(request)['last_error_code'])

    def test_concurrent_same_token_preparers_reload_one_winning_command(self):
        request = self.request()
        lease = w.claim(self.conn, owner=self.settings.owner, lease_for=self.settings.lease_for, request_id=request['id'])
        self.conn.commit()
        barrier = threading.Barrier(2)
        original = ec.capture
        def both(conn, **kwargs):
            command = original(conn, **kwargs)
            barrier.wait(timeout=10)
            return command
        def prepare():
            worker._prepare_evaluation(self.runtime_connect, lease, self.settings, self.validator)
        with patch.object(ec, 'capture', side_effect=both), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(prepare) for _ in range(2)]
            for future in futures: future.result(timeout=15)
        frozen = w.load_prepared(self.conn, request_id=request['id'])
        self.assertIsNotNone(frozen)
        self.expire(request)
        with patch.object(ec, 'capture', side_effect=AssertionError('must reload winner')):
            self.assertEqual('completed', self.run_request(request, validator=None)['status'])
        self.assertEqual(frozen, w.load_prepared(self.conn, request_id=request['id']))

    def test_non_evaluable_is_successful_completion_not_worker_failure(self):
        self.generation = self.register(replace(self.configuration, engine_configuration=replace(self.config, target_max_age=timedelta(0))))
        request = self.request()
        result = self.run_request(request)
        self.assertEqual('completed', result['status'], result)
        with self.conn.cursor() as cur:
            cur.execute('SELECT result_kind,non_evaluation_reason FROM corner.engine_evaluations WHERE id=%s',
                        (result['execution']['engine_evaluation_id'],))
            self.assertEqual(('not_evaluable', 'stale_target'), cur.fetchone())

    def test_missing_adapter_waits_without_phase_default_or_preparation(self):
        request = self.request()
        result = self.run_request(request, validator=None)
        self.assertEqual(('waiting', 'evaluation_validation_unavailable'), (result['status'], result['reason']))
        self.assertIsNone(w.load_prepared(self.conn, request_id=request['id']))

    def test_missing_target_waits_without_fabricating_unavailable_observation(self):
        from corner.dispositions import DecisionAuthority, DispositionCommand, record_disposition
        request = self.request()
        record_disposition(self.conn, authority=DecisionAuthority('service', self.authority.identifier),
                           command=DispositionCommand(str(uuid4()), self.target_id, 'rejected', 'synthetic', datetime.now(timezone.utc)))
        self.conn.commit()
        result = self.run_request(request)
        self.assertEqual(('waiting', 'evaluation_target_missing'), (result['status'], result['reason']))
        self.assertIsNone(w.load_prepared(self.conn, request_id=request['id']))

    def test_unsupported_selector_intent_blocks_before_selection(self):
        intent = ec.request_intent(outcome_id=self.outcome_id, sportsbook_id=self.book_id, validation_adapter=self.validator_id)
        intent['selector']['format'] = 'future-format'
        request = self.request(intent=intent)
        with patch.object(ev_selection, 'select_ev_snapshot', side_effect=AssertionError('no selection')):
            self.assertEqual('blocked', self.run_request(request)['status'])

    def test_wrong_validator_revision_blocks(self):
        request = self.request()
        wrong = ec.ValidationAdapter(replace(self.validator_id, revision='other'), self.validator.validate)
        result = self.run_request(request, validator=wrong)
        self.assertEqual(('blocked', 'implementation_unavailable'), (result['status'], result['reason']))

    def test_malformed_frozen_selector_blocks_without_reselection(self):
        import copy
        request = self.request()
        frozen = self.crash_after_capture(request)
        self.expire(request)
        original = w._prepared
        def corrupt(cur, identity):
            row = original(cur, identity)
            if row and identity == request['id']:
                row = dict(row)
                doc = copy.deepcopy(row['command_snapshot'])
                doc['payload']['context']['selection']['selector']['format'] = 'unsupported'
                row.update(command_snapshot=doc, command_sha256=ev._digest(doc))
            return row
        with patch.object(w, '_prepared', side_effect=corrupt), patch.object(ec, 'capture', side_effect=AssertionError('no recapture')):
            result = self.run_request(request)
        self.assertEqual('blocked', result['status'])
        self.assertEqual(frozen, w.load_prepared(self.conn, request_id=request['id']))

    def test_frozen_engine_format_failure_never_recaptures(self):
        request = self.request()
        frozen = self.crash_after_capture(request)
        self.expire(request)
        with (patch.object(ev, 'deserialize_command', side_effect=ValueError('unsupported snapshot format')),
              patch.object(ec, 'capture', side_effect=AssertionError('no recapture'))):
            result = self.run_request(request)
        self.assertEqual('blocked', result['status'])
        self.assertEqual(frozen, w.load_prepared(self.conn, request_id=request['id']))

    def test_capture_connection_is_read_only(self):
        request = self.request()
        def tries_write(conn, condition, at):
            with conn.cursor() as cur:
                cur.execute('UPDATE corner.work_executions SET updated_at=clock_timestamp() WHERE work_request_id=%s', (request['id'],))
            return self.validation
        result = self.run_request(request, validator=ec.ValidationAdapter(self.validator_id, tries_write))
        self.assertEqual('blocked', result['status'])
        self.assertIsNone(w.load_prepared(self.conn, request_id=request['id']))

    def test_assess_stays_ready_and_unclaimed(self):
        request = w.enqueue(self.conn, kind='assess', namespace=self.authority.identifier, key=str(uuid4()),
                            sources={'qualification_decision_id': self.judgment['id']})
        self.assertEqual('idle', self.run_request(request)['status'])
        self.assertEqual(0, self.execution(request)['claim_count'])
