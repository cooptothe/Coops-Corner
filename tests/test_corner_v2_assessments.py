"""Synthetic approval proofs only; no production source is authorized here."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from psycopg2.extras import RealDictCursor

from corner import actionability_v2 as pure, assessments_v2 as api, assessment_worker_v2 as worker2
from corner import analytics_versions as analytics, capture_authority as auth, channels, evaluations as codec
from corner import evaluation_capture_v2 as capture, lifecycle, lifecycle_versions as store, work
from corner import worker, lifecycle_store as legacy_store
import test_corner_v2_capture as fixture
import test_corner_conditional_ev as math
import test_corner_lifecycle_store as legacy_fixture
from test_corner_work import WorkDatabase


def synthetic(data=None):
    data = data or fixture.fixtures()
    command, binding, authority_policy, catalog = data
    at = command.snapshot.evaluated_at
    row = math.row_for(command)
    quotes = {q.observation_id: q for q in command.snapshot.quotes}
    target = quotes[command.snapshot.target_observation_id]
    refs = tuple(quotes[oid] for r in row['result_snapshot']['reference_estimates'] for oid in r['observation_ids'])
    key = lifecycle.ConditionKey('positive_ev', target.sportsbook_id, target.outcome_id, 'synthetic-channel')
    fact = lifecycle.EvaluationFact(lifecycle.EvaluationOrder(at, row['id']), key, analytics.ENGINE,
        'config', binding['event_id'], 'evaluated', target, refs)
    q = lifecycle.QualificationFact(str(uuid4()), str(uuid4()), fact, analytics.QUALIFIER, 'policy', 'qualified')
    policy = lifecycle.ActionabilityPolicy(pure.IMPLEMENTATION, timedelta(minutes=1), timedelta(minutes=1))
    expected = (target,) + refs
    books = sorted({r.sportsbook_id for r in expected})
    bundle = fixture.source(catalog).capture(at)
    cap = dict(capture_format_version=pure.CAPTURE_FORMAT, implementation=asdict(pure.IMPLEMENTATION),
        snapshot_captured_at=codec._encode(at), canonical_binding=binding, historical_basis=pure.historical_basis(row),
        expected_observations=codec._encode([asdict(r) for r in expected]), authority_policy=authority_policy, catalog=bundle,
        assertion_ids={'phase': str(uuid4()), **{b: str(uuid4()) for b in books}},
        bindings=dict(generation_id=q.generation_id, qualification_id=q.id, watermark_evaluated_at=codec._encode(at),
                      watermark_id=row['id'], basis_assessment_id=None),
        streams=[dict(stream_role='target' if r == target else 'reference', outcome_id=r.outcome_id,
            sportsbook_id=r.sportsbook_id, selection_kind='selected_trusted_observation', quote=codec._encode(asdict(r))) for r in expected])
    cap['inventories'] = api._inventories(auth.unpack(bundle), authority_policy, binding, books, at)
    return cap, at, q, policy


class V2AssessmentPolicyTests(unittest.TestCase):
    def test_positive_freezes_historical_basis_and_fresh_resolutions(self):
        result = pure.assess(*synthetic())
        self.assertTrue(result['actionable'])
        self.assertEqual(analytics.v2.BASIS, result['historical_basis']['calculation_basis'])
        self.assertEqual([], result['reasons'])
        self.assertTrue(result['authority']['deadlines'])

    def test_current_agreement_is_not_historical_agreement(self):
        cap, at, q, policy = synthetic()
        catalog = auth.unpack(cap['catalog'])
        for record in (r for r in catalog['records'] if r['scope']['kind'] == 'settlement'):
            fixture.change_content(record, {'conditioning_contract': {'overtime': 'excluded'}})
            fixture.reapprove(cap['authority_policy'], catalog, record)
        cap['catalog'] = auth.envelope(catalog)
        cap['inventories'] = api._inventories(catalog, cap['authority_policy'], cap['canonical_binding'],
            sorted({r['sportsbook_id'] for r in cap['expected_observations']}), at)
        result = pure.assess(cap, at, q, policy)
        self.assertEqual(['analytical_conditioning_changed'], result['reasons'])

    def test_current_books_disagree_has_distinct_reason(self):
        cap, at, q, policy = synthetic()
        catalog = auth.unpack(cap['catalog'])
        record = catalog['records'][1]
        # Records are canonical-sorted; explicitly choose a settlement record.
        record = next(r for r in catalog['records'] if r['scope']['kind'] == 'settlement')
        fixture.change_content(record, {'conditioning_contract': {'overtime': 'excluded'}})
        fixture.reapprove(cap['authority_policy'], catalog, record)
        cap['catalog'] = auth.envelope(catalog)
        cap['inventories'] = api._inventories(catalog, cap['authority_policy'], cap['canonical_binding'],
            sorted({r['sportsbook_id'] for r in cap['expected_observations']}), at)
        self.assertEqual(['current_settlement_incompatible'], pure.assess(cap, at, q, policy)['reasons'])

    def test_withdrawal_is_verified_negative_not_capture_error(self):
        data = fixture.fixtures(); at = data[0].snapshot.evaluated_at
        data[3]['withdrawals'].append(dict(id=str(uuid4()), approval_id=data[3]['approvals'][0]['id'],
            recorded_at=codec._encode(at), effective_at=codec._encode(at), reason='synthetic withdrawal'))
        self.assertEqual(['approval_withdrawn'], pure.assess(*synthetic(data))['reasons'])

    def test_approval_expiry_uses_assessed_at_exclusively(self):
        data = fixture.fixtures(); at = data[0].snapshot.evaluated_at
        artifact = data[3]['approvals'][0]
        artifact['effective_until'] = codec._encode(at + timedelta(seconds=5))
        data[2]['phase_approval_references'][0]['sha256'] = auth.digest(artifact)
        cap, _, q, policy = synthetic(data)
        self.assertTrue(pure.assess(cap, at + timedelta(seconds=4), q, policy)['actionable'])
        for seconds in (5, 6):
            self.assertIn('approval_expired_or_not_applicable', pure.assess(cap, at + timedelta(seconds=seconds), q, policy)['reasons'])

    def test_live_unknown_and_expired_phase_are_negative(self):
        for status in ('explicit_live', 'unknown'):
            data = fixture.fixtures(); fixture.change_content(data[3]['records'][0], {'status': status})
            self.assertIn('unsupported_or_unknown_phase', pure.assess(*synthetic(data))['reasons'])
        cap, at, q, policy = synthetic()
        self.assertIn('unsupported_or_unknown_phase', pure.assess(cap, at + timedelta(minutes=6), q, policy)['reasons'])

    def test_missing_settlement_and_rules_expiry_are_negative(self):
        for mode in ('missing', 'expired'):
            data = fixture.fixtures()
            if mode == 'missing': data[3]['records'].pop()
            else:
                fixture.change_content(data[3]['records'][1], {'effective_until': codec._encode(data[0].snapshot.evaluated_at)})
                fixture.reapprove(data[2], data[3], data[3]['records'][1])
            self.assertIn('settlement_authority_unknown', pure.assess(*synthetic(data))['reasons'])

    def test_corruption_and_incomplete_manifest_are_errors(self):
        for mode in ('digest', 'manifest', 'event', 'format'):
            cap, at, q, policy = synthetic()
            if mode == 'manifest': cap['inventories'].pop('phase')
            elif mode == 'event': cap['canonical_binding']['event_id'] = str(uuid4())
            elif mode == 'format': cap['capture_format_version'] = 'unknown'
            else: cap['catalog']['sha256'] = '0' * 64
            with self.assertRaises(ValueError): pure.assess(cap, at, q, policy)

    def test_streams_cannot_be_omitted_duplicated_or_rebound(self):
        for mode in ('missing', 'duplicate', 'binding'):
            cap, at, q, policy = synthetic()
            if mode == 'missing': cap['streams'].pop()
            elif mode == 'duplicate': cap['streams'].append(cap['streams'][0])
            else: cap['streams'][0]['quote']['sportsbook_id'] = str(uuid4())
            with self.assertRaises(ValueError): pure.assess(cap, at, q, policy)

    def test_quote_identity_state_and_separate_deadlines(self):
        for mode, reason in [('identity', 'analytical_evidence_changed'), ('state', 'target_unavailable')]:
            cap, at, q, policy = synthetic()
            quote = cap['streams'][0]['quote']; quote['observation_id'] = str(uuid4())
            if mode == 'state': quote['quote_state'] = 'unavailable'; quote['decimal_odds'] = None
            self.assertIn(reason, pure.assess(cap, at, q, policy)['reasons'])
        cap, at, q, policy = synthetic()
        target_age = at - q.evaluation.target.observed_at
        policy = replace(policy, target_max_age=target_age, reference_max_age=timedelta(days=1))
        self.assertTrue(pure.assess(cap, at, q, policy)['actionable'])
        self.assertEqual(['target_stale'], pure.assess(cap, at + timedelta(microseconds=1), q, policy)['reasons'])
        policy = replace(policy, target_max_age=timedelta(days=1), reference_max_age=timedelta(0))
        self.assertIn('analytical_evidence_stale', pure.assess(cap, at + timedelta(seconds=1), q, policy)['reasons'])

    def test_unknown_versions_and_reasons_cannot_be_lifecycle_booleans(self):
        for version, reason in [('unknown', 'target_stale'), (pure.FORMAT, 'invented')]:
            with self.assertRaises(ValueError): pure.closure_reason(version, reason)
        self.assertEqual('unsupported_phase', pure.closure_reason(pure.FORMAT, 'unsupported_or_unknown_phase'))

    def test_production_authority_cannot_be_enabled_by_a_positive_bundle(self):
        cap, at, q, policy = synthetic()
        cap['authority_policy']['environment'] = 'production'
        with self.assertRaisesRegex(ValueError, 'production'): pure.assess(cap, at, q, policy)

    def test_expired_old_rules_retained_but_not_applied_to_new_revision(self):
        cap, at, q, policy = synthetic()
        catalog = auth.unpack(cap['catalog'])
        old = deepcopy(next(r for r in catalog['records'] if r['scope']['kind'] == 'settlement'))
        old['id'] = str(uuid4())
        fixture.change_content(old, {'effective_until': codec._encode(at), 'conditioning_contract': {'old': 'population'}})
        catalog['records'].append(old)
        cap['catalog'] = auth.envelope(catalog)
        cap['inventories'] = api._inventories(catalog, cap['authority_policy'], cap['canonical_binding'],
            sorted({r['sportsbook_id'] for r in cap['expected_observations']}), at)
        self.assertTrue(pure.assess(cap, at, q, policy)['actionable'])


@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE') == '1' and os.getenv('CORNER_TEST_CONCURRENCY') == '1',
                     'opt-in disposable PostgreSQL v2 assessments')
class V2AssessmentDatabaseTests(WorkDatabase, unittest.TestCase):
    select = fixture.V2CaptureTests.select
    append = fixture.V2CaptureTests.append
    runtime_connect = fixture.V2CaptureTests.runtime_connect
    expire = fixture.V2CaptureTests.expire

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with cls.connect() as conn:
            with conn.cursor() as cur:
                cur.execute((Path(__file__).resolve().parents[1] / 'db/migrations/013_corner_v2_actionability_reasons.sql').read_text())

    def register(self, config):
        self.config = replace(config, analytics=replace(config.analytics, actionability_policy=lifecycle.ActionabilityPolicy(
            pure.IMPLEMENTATION, timedelta(days=36500), timedelta(days=36500))))
        return fixture.V2CaptureTests.register(self, self.config)

    def setUp(self):
        fixture.V2CaptureTests.setUp(self)
        request = fixture.V2CaptureTests.request(self)
        completed = fixture.V2CaptureTests.run_request(self, request)
        self.assertEqual('completed', completed['status'], completed)
        self.evaluation_id = completed['execution']['engine_evaluation_id']
        self.judgment = analytics.record_qualification(self.conn, authority=self.authority, qualification_key=str(uuid4()),
            command=analytics.QualificationCommand(self.evaluation_id, self.config.analytics.qualification_policy, datetime.now(timezone.utc)))
        self.assertEqual('qualified', self.judgment['decision_kind'])
        self.occurrence = channels.create_occurrence(self.conn, qualification_decision_id=self.judgment['id'])
        self.activation = channels.activate_generation(self.conn, authority=self.authority, activation_key=str(uuid4()),
            command=channels.ActivationCommand(self.channel['id'], self.generation['id'], None, self.time))
        self.conn.commit()

    def command(self, basis=None, source=None):
        return api.capture_assessment(self.conn, generation_id=self.generation['id'], qualification_decision_id=self.judgment['id'],
            evaluation_watermark_id=self.evaluation_id, basis_assessment_id=basis, source=source or self.source)

    def record(self, command=None, key=None, conn=None):
        return api.record_assessment(conn or self.conn, authority=self.authority, assessment_key=key or str(uuid4()),
                                     command=command or self.command())

    def request(self, basis=None):
        request = work.enqueue(self.conn, kind='assess', namespace=self.authority.identifier, key=str(uuid4()),
            sources=dict(condition_id=self.condition['id'], generation_id=self.generation['id'], qualification_decision_id=self.judgment['id']),
            intent_json=codec.canonical_json(worker2.request_intent(evaluation_watermark_id=self.evaluation_id, basis_assessment_id=basis)))
        self.conn.commit(); return request

    def run_request(self, request, source=None, settings=None):
        return worker2.run_once(self.runtime_connect, settings=settings or self.settings, request_id=request['id'], source=source or self.source)

    def row(self, table, identity):
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT * FROM corner.' + table + ' WHERE id=%s', (identity,))
            return dict(cur.fetchone())

    def withdrawal(self):
        catalog = deepcopy(self.data[3]); now = codec._encode(datetime.now(timezone.utc))
        catalog['withdrawals'].append(dict(id=str(uuid4()), approval_id=catalog['approvals'][0]['id'], recorded_at=now,
                                          effective_at=now, reason='synthetic withdrawal'))
        return fixture.source(catalog)

    def app(self, kind, identity, at=None, key=None):
        return store.apply_command(self.conn, authority=self.authority, application_key=key or str(uuid4()),
            command=store.ApplicationCommand(self.condition['id'], kind, identity, self.generation['id'], at))

    def opened(self):
        self.app('generation_activation', self.activation['id'], self.time)
        self.app('evaluation', self.evaluation_id)
        self.app('qualification', self.judgment['id'], self.judgment['decided_at'])
        assessment = self.record()
        receipt = self.app('assessment', assessment['id'])
        self.assertEqual('opened', receipt['result_snapshot']['outputs'][0]['transition_kind'])
        return assessment, receipt

    def test_positive_persistence_and_idempotent_retry(self):
        command = self.command(); first = self.record(command, 'same')
        self.assertTrue(first['actionable'])
        self.assertEqual(first, self.record(command, 'same'))
        with self.assertRaises(ValueError): self.record(replace(command, context_json='{"changed":true}'), 'same')
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            self.assertTrue(api.read_fact(cur, first['id']).actionable)

    def test_runtime_worker_negative_completes_without_lifecycle(self):
        request = self.request(); result = self.run_request(request, source=self.withdrawal())
        self.assertEqual('completed', result['status'], result)
        row = self.row('actionability_assessments', result['execution']['actionability_assessment_id'])
        self.assertEqual('approval_withdrawn', row['primary_reason'])
        with self.conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM corner.lifecycle_applications WHERE condition_id=%s', (self.condition['id'],))
            self.assertEqual(0, cur.fetchone()[0])

    def test_corrupt_capture_blocks_with_no_assessment(self):
        catalog = deepcopy(self.data[3]); catalog['records'][0]['content_sha256'] = '0' * 64
        request = self.request(); result = self.run_request(request, fixture.source(catalog))
        self.assertEqual('blocked', result['status'], result)
        self.assertIsNone(worker2.load_prepared(self.conn, request_id=request['id']))

    def test_frozen_retry_after_withdrawal_and_market_change(self):
        request = self.request()
        with patch.object(worker2, 'complete', side_effect=SystemExit('crash')):
            with self.assertRaises(SystemExit): self.run_request(request)
        frozen = worker2.load_prepared(self.conn, request_id=request['id'])
        self.append(self.target_id, price='1.01', observed_at=datetime.now(timezone.utc)); self.conn.commit()
        self.expire(request)
        with patch.object(api, 'capture_assessment', side_effect=AssertionError('no recapture')):
            result = self.run_request(request, source=self.withdrawal(), settings=replace(self.settings, owner='worker-b'))
        self.assertEqual('completed', result['status'], result)
        self.assertTrue(self.row('actionability_assessments', result['execution']['actionability_assessment_id'])['actionable'])
        self.assertEqual(frozen, worker2.load_prepared(self.conn, request_id=request['id']))
        later = self.run_request(self.request(), source=self.withdrawal())
        row = self.row('actionability_assessments', later['execution']['actionability_assessment_id'])
        self.assertFalse(row['actionable'])
        self.assertIn('approval_withdrawn', row['result_snapshot']['reasons'])

    def test_negative_closes_explicitly_and_rebuild_is_identical(self):
        assessment, opened = self.opened()
        negative = self.record(self.command(assessment['id'], self.withdrawal()))
        closed = self.app('assessment', negative['id'])
        self.assertEqual('approval_withdrawn', closed['result_snapshot']['outputs'][0]['reason_code'])
        verified = store.verify_history(self.conn, condition_id=self.condition['id'])
        with self.conn.cursor() as cur:
            cur.execute('DELETE FROM corner.condition_processing_projections WHERE condition_id=%s', (self.condition['id'],))
            cur.execute('DELETE FROM corner.opportunities WHERE condition_id=%s', (self.condition['id'],))
        store.rebuild_projections(self.conn, condition_id=self.condition['id'])
        self.assertEqual(verified, store.verify_history(self.conn, condition_id=self.condition['id']))
        retry = self.app('assessment', assessment['id'])
        self.assertEqual('already_reflected', retry['application_outcome'])
        self.assertEqual(0, retry['transition_count'])

    def test_obsolete_negative_cannot_close_refreshed_binding(self):
        assessment, _ = self.opened()
        stale = self.record(self.command(None, self.withdrawal()))
        receipt = self.app('assessment', stale['id'])
        self.assertEqual('obsolete_binding', receipt['reason_code'])
        self.assertEqual(0, receipt['transition_count'])
        store.verify_history(self.conn, condition_id=self.condition['id'])

    def test_concurrent_identical_persistence_returns_one_record(self):
        command = self.command(); self.conn.commit(); barrier = threading.Barrier(2)
        def write():
            conn = self.runtime_connect()
            try:
                barrier.wait(timeout=10)
                row = self.record(command, 'concurrent', conn)
                conn.commit(); return row
            finally: conn.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = list(pool.map(lambda _: write(), range(2)))
        self.assertEqual(a, b)

    def test_stale_preparer_is_fenced_and_new_owner_can_capture(self):
        request = self.request(); entered, release = threading.Event(), threading.Event()
        original = api.capture_assessment
        def slow(*args, **kwargs):
            value = original(*args, **kwargs); entered.set()
            self.assertTrue(release.wait(10)); return value
        with ThreadPoolExecutor(max_workers=1) as pool, patch.object(api, 'capture_assessment', side_effect=slow):
            job = pool.submit(self.run_request, request)
            self.assertTrue(entered.wait(10)); self.expire(request)
            lease = work.claim(self.conn, owner='worker-b', lease_for=self.settings.lease_for, request_id=request['id'])
            self.conn.commit(); release.set()
            self.assertEqual('lease_lost', job.result(10)['status'])
        self.assertIsNone(worker2.load_prepared(self.conn, request_id=request['id']))
        prepared = worker2.prepare_once(self.runtime_connect, lease=lease, settings=replace(self.settings, owner='worker-b'),
                                       source=self.withdrawal())
        self.assertIn('approval_withdrawn', prepared['command_snapshot']['payload']['capture']['authorization']['reasons'])

    def test_concurrent_preparers_preserve_one_snapshot(self):
        request = self.request()
        lease = work.claim(self.conn, owner=self.settings.owner, lease_for=self.settings.lease_for, request_id=request['id'])
        self.conn.commit(); barrier = threading.Barrier(2); original = api.capture_assessment
        def together(*args, **kwargs):
            value = original(*args, **kwargs); barrier.wait(10); return value
        with ThreadPoolExecutor(max_workers=2) as pool, patch.object(api, 'capture_assessment', side_effect=together):
            jobs = [pool.submit(worker2.prepare_once, self.runtime_connect, lease=lease, settings=self.settings, source=self.source)
                    for _ in range(2)]
            rows = [job.result(15) for job in jobs]
        self.assertEqual(rows[0], rows[1])

    def test_failed_completion_has_no_partial_domain_row(self):
        request = self.request(); original = api.record_assessment
        def fail(*args, **kwargs):
            original(*args, **kwargs); raise ValueError('synthetic failure after domain insert')
        with patch.object(api, 'record_assessment', side_effect=fail): result = self.run_request(request)
        self.assertEqual('blocked', result['status'], result)
        self.assertIsNotNone(worker2.load_prepared(self.conn, request_id=request['id']))
        with self.conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM corner.actionability_assessments WHERE assessment_key=%s',
                        ('corner.worker.assess-v2:' + request['id'],))
            self.assertEqual(0, cur.fetchone()[0])

    def test_valid_completion_holds_fence_after_wall_clock_expiry(self):
        request = self.request()
        lease = work.claim(self.conn, owner=self.settings.owner, lease_for=self.settings.lease_for, request_id=request['id'])
        self.conn.commit()
        worker2.prepare_once(self.runtime_connect, lease=lease, settings=self.settings, source=self.source)
        entered, release = threading.Event(), threading.Event(); original = api.record_assessment
        def held(conn, **kwargs):
            with conn.cursor() as cur:
                cur.execute("UPDATE corner.work_executions SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE work_request_id=%s",
                            (request['id'],))
            entered.set(); self.assertTrue(release.wait(10)); return original(conn, **kwargs)
        def execute():
            with worker._transaction(self.runtime_connect, self.settings) as conn:
                return worker2.complete(conn, request_id=request['id'], owner=self.settings.owner, token=lease['lease_token'])
        with ThreadPoolExecutor(max_workers=1) as pool, patch.object(api, 'record_assessment', side_effect=held):
            job = pool.submit(execute); self.assertTrue(entered.wait(10))
            with worker._transaction(self.runtime_connect, self.settings) as conn:
                self.assertIsNone(work.claim(conn, owner='worker-b', lease_for=self.settings.lease_for, request_id=request['id']))
            release.set(); self.assertEqual('completed', job.result(10)['status'])

    def test_missing_loader_waits_without_preparation(self):
        request = self.request()
        result = worker2.run_once(self.runtime_connect, settings=self.settings, request_id=request['id'])
        self.assertEqual('waiting', result['status'])
        self.assertIsNone(worker2.load_prepared(self.conn, request_id=request['id']))

    def test_exact_observation_change_does_not_reuse_old_approval_as_actionability(self):
        self.append(self.target_id, price='2.25', observed_at=datetime.now(timezone.utc))
        self.conn.commit()
        row = self.record()
        self.assertEqual(['analytical_evidence_changed'], row['result_snapshot']['reasons'])

    def test_missing_stream_preserves_rejection_witness_without_fabricated_quote(self):
        from corner.dispositions import record_disposition, DecisionAuthority, DispositionCommand
        record_disposition(self.conn, authority=DecisionAuthority('service', self.authority.identifier),
            command=DispositionCommand(str(uuid4()), self.target_id, 'rejected', 'synthetic', datetime.now(timezone.utc)))
        self.conn.commit(); row = self.record()
        target = next(s for s in row['command_snapshot']['capture']['streams'] if s['stream_role'] == 'target')
        self.assertEqual('missing_trusted_observation', target['selection_kind'])
        self.assertIsNone(target['quote']); self.assertIsNone(row['target_deadline'])
        self.assertTrue(target['missing_witnesses']); self.assertFalse(row['actionable'])

    def test_unsupported_assessment_version_fails_before_ignored_receipt(self):
        assessment, _ = self.opened()
        original = store._one
        def broken(cur, table, identity):
            row = original(cur, table, identity)
            return dict(row) | {'snapshot_format_version': 'unknown'} if table == 'actionability_assessments' else row
        with patch.object(store, '_one', side_effect=broken):
            with self.assertRaises(ValueError): self.app('assessment', assessment['id'])
        self.assertEqual(4, store.verify_history(self.conn, condition_id=self.condition['id'])['applications'])

    def test_changed_authority_reason_cannot_hide_behind_valid_digest(self):
        row = self.record(); broken = dict(row)
        output = deepcopy(row['result_snapshot']); output.update(actionable=False, primary_reason='unknown_reason', reasons=['unknown_reason'])
        broken.update(result_snapshot=output, result_sha256=codec._digest(output))
        original = api.old._row
        def read(cur, table, identity):
            return broken if table == 'actionability_assessments' and identity == row['id'] else original(cur, table, identity)
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur, patch.object(api.old, '_row', side_effect=read):
            with self.assertRaises(ValueError): api.read_fact(cur, row['id'])


@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE') == '1' and os.getenv('CORNER_TEST_CONCURRENCY') == '1',
                     'opt-in legacy lifecycle compatibility')
class V1LifecycleDispatchTests(legacy_fixture.LifecycleDatabase, unittest.TestCase):
    setUp = legacy_fixture.LifecycleStoreTests.setUp
    select = legacy_fixture.LifecycleStoreTests.select
    evaluate = legacy_fixture.LifecycleStoreTests.evaluate
    qualify = legacy_fixture.LifecycleStoreTests.qualify
    register = legacy_fixture.LifecycleStoreTests.register
    capture = legacy_fixture.LifecycleStoreTests.capture
    command = legacy_fixture.LifecycleStoreTests.command
    record = legacy_fixture.LifecycleStoreTests.record
    append = legacy_fixture.LifecycleStoreTests.append
    app = legacy_fixture.LifecycleStoreTests.app
    opened = legacy_fixture.LifecycleStoreTests.opened
    projections = legacy_fixture.LifecycleStoreTests.projections

    def test_original_history_then_v2_dispatch_preserves_v1_semantics(self):
        self.opened(); before = self.projections()
        result = store.apply_command(self.conn, authority=self.authority, application_key=str(uuid4()),
            command=store.ApplicationCommand(self.condition['id'], 'assessment', self.assessment['id'], self.generation['id']))
        self.assertEqual('already_reflected', result['application_outcome'])
        self.assertEqual(0, result['transition_count'])
        verified = store.verify_history(self.conn, condition_id=self.condition['id'])
        self.assertEqual(5, verified['applications'])
        store.rebuild_projections(self.conn, condition_id=self.condition['id'])
        self.assertEqual(before[1], self.projections()[1])

    def test_v1_reducer_interpretation_is_used_for_new_receipts(self):
        self.app('generation_activation'); self.app('evaluation'); self.app('qualification')
        result = store.apply_command(self.conn, authority=self.authority, application_key=str(uuid4()),
            command=store.ApplicationCommand(self.condition['id'], 'assessment', self.assessment['id'], self.generation['id']))
        self.assertEqual('opened', result['result_snapshot']['outputs'][0]['transition_kind'])
        self.assertEqual(4, store.verify_history(self.conn, condition_id=self.condition['id'])['applications'])
