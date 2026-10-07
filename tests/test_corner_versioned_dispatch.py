"""Exact installed routing, with no production approvals or polling."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os
import threading
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4
from psycopg2.extras import RealDictCursor

from corner import versioned_dispatch as d, versioned_reconciliation as r
from corner import work as w, worker, evaluations as ev, analytics_versions as av, channels
from corner import evaluation_capture_v2 as e2, assessment_worker_v2 as aw2
from corner import assessments_v2 as a2, lifecycle_versions as l2
import test_corner_v2_assessments as vf
import test_corner_v2_capture as cf
import test_corner_worker as old
from test_corner_work import WorkDatabase


class RoutingIdentityTests(unittest.TestCase):
    def test_registry_requires_exact_kind_format_and_build(self):
        for name, (kind, fmt, revision) in d.HANDLERS.items():
            doc = dict(work_kind=kind, format=fmt, implementation=revision)
            self.assertEqual(name, d.handler(doc))
            for field in doc:
                broken = dict(doc); broken.pop(field)
                with self.assertRaises(w.WorkBlocked): d.handler(broken)
                broken[field] = 'unknown'
                with self.assertRaises(w.WorkBlocked): d.handler(broken)

    def test_installing_another_build_does_not_retarget_original_identity(self):
        original = dict(work_kind='assess', format=w.COMMAND_FORMAT, implementation=d.a1.IMPLEMENTATION.revision)
        with patch.dict(d.HANDLERS, {'assess.future': ('assess', 'future', 'new-build')}):
            self.assertEqual('assess.v1', d.handler(original))


class Helpers:
    def dispatch(self, request, **kwargs):
        self.conn.commit()
        return d.run_once(self.runtime_connect, settings=self.settings, request_id=request['id'], **kwargs)

    def enqueue_versioned(self, kind, sources, details=None):
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            intent = d.request_intent(cur, kind=kind, sources=sources, details=details)
        return w.enqueue(self.conn, kind=kind, namespace=self.authority.identifier, key=str(uuid4()), sources=sources,
                         intent_json=ev.canonical_json(intent))

    def item(self, report, identity):
        return next(i for i in report['items'] if i['candidate_id'] == identity)

    def sweep(self, obligation):
        return r.sweep(self.conn, obligation=obligation, **({'channel_id': self.channel['id']} if obligation != 'occurrence' else {}))

    def lifecycle_request(self, kind, identity):
        return self.enqueue_versioned('apply_lifecycle', dict(condition_id=self.condition['id'], generation_id=self.generation['id'],
            **{d.l1._SOURCE_COLUMNS[kind]: identity}), {'command_kind': kind})


@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE') == '1' and os.getenv('CORNER_TEST_CONCURRENCY') == '1', 'disposable versioned dispatch DB')
class ConditionalDispatchTests(Helpers, WorkDatabase, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with cls.connect() as conn:
            with conn.cursor() as cur:
                cur.execute((Path(__file__).resolve().parents[1] / 'db/migrations/013_corner_v2_actionability_reasons.sql').read_text())
    setUp = vf.V2AssessmentDatabaseTests.setUp
    select = vf.V2AssessmentDatabaseTests.select
    register = vf.V2AssessmentDatabaseTests.register
    runtime_connect = vf.V2AssessmentDatabaseTests.runtime_connect
    expire = vf.V2AssessmentDatabaseTests.expire

    def evaluation_request(self): return cf.V2CaptureTests.request(self)

    def test_v2_discovery_qualification_occurrence_and_repeated_scan(self):
        request = self.evaluation_request(); result = self.dispatch(request, source=self.source)
        self.assertEqual('completed', result['status'], result)
        first = self.item(self.sweep('qualification'), request['id'])
        again = self.item(self.sweep('qualification'), request['id'])
        self.assertEqual('newly_requested', first['status']); self.assertEqual('pending', again['status'])
        self.assertEqual(first['request_id'], again['request_id'])
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            intent = w._request(cur, first['request_id'])['intent_snapshot']['intent']
        self.assertEqual('qualify.v2', intent['dispatch']['handler'])
        finished = self.dispatch({'id': first['request_id']})
        self.assertEqual('completed', finished['status'], finished)
        qid = finished['execution']['qualification_decision_id']
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            self.assertEqual(av.QUALIFICATION_FORMAT, d.decision(cur, qid)['qualification_snapshot_format_version'])
        self.assertEqual('fulfilled', self.item(self.sweep('qualification'), request['id'])['status'])
        occurrence = self.item(self.sweep('occurrence'), qid)
        self.assertEqual('completed', self.dispatch({'id': occurrence['request_id']})['status'])
        self.assertEqual('fulfilled', self.item(self.sweep('occurrence'), qid)['status'])

    def test_activation_discovery_uses_versioned_lifecycle_and_completion_markers(self):
        item = self.item(self.sweep('activation'), self.condition['id'])
        result = self.dispatch({'id': item['request_id']})
        self.assertEqual('completed', result['status'], result)
        self.assertEqual('fulfilled', self.item(self.sweep('activation'), self.condition['id'])['status'])
        self.assertEqual(1, l2.verify_history(self.conn, condition_id=self.condition['id'])['applications'])

    def test_v2_assess_dispatch_then_explicit_lifecycle_open(self):
        for kind, identity in [('generation_activation', self.activation['id']), ('evaluation', self.evaluation_id), ('qualification', self.judgment['id'])]:
            result = self.dispatch(self.lifecycle_request(kind, identity))
            self.assertEqual('completed', result['status'], result)
        req = w.enqueue(self.conn, kind='assess', namespace=self.authority.identifier, key=str(uuid4()),
            sources=dict(condition_id=self.condition['id'], generation_id=self.generation['id'], qualification_decision_id=self.judgment['id']),
            intent_json=ev.canonical_json(aw2.request_intent(evaluation_watermark_id=self.evaluation_id)))
        result = self.dispatch(req, source=self.source)
        self.assertEqual('completed', result['status'], result)
        result = self.dispatch(self.lifecycle_request('assessment', result['execution']['actionability_assessment_id']))
        self.assertEqual('completed', result['status'], result)
        verified = l2.verify_history(self.conn, condition_id=self.condition['id'])
        self.assertEqual(4, verified['applications'])

    def test_missing_request_identity_is_blocked_not_assumed_v1(self):
        req = w.enqueue(self.conn, kind='qualify', namespace=self.authority.identifier, key=str(uuid4()),
            sources=dict(condition_id=self.condition['id'], generation_id=self.generation['id'], engine_evaluation_id=self.evaluation_id))
        self.assertEqual('blocked', self.dispatch(req)['status'])

    def test_changed_route_build_or_family_is_blocked_before_domain_execution(self):
        for mode in ('family', 'revision'):
            sources = dict(condition_id=self.condition['id'], generation_id=self.generation['id'], engine_evaluation_id=self.evaluation_id)
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                intent = d.request_intent(cur, kind='qualify', sources=sources)
            intent['dispatch']['handler' if mode == 'family' else 'implementation_revision'] = 'qualify.v1' if mode == 'family' else 'unknown'
            req = w.enqueue(self.conn, kind='qualify', namespace=self.authority.identifier, key=str(uuid4()), sources=sources,
                             intent_json=ev.canonical_json(intent))
            with patch.object(av, 'record_qualification', side_effect=AssertionError('must not execute')):
                self.assertEqual('blocked', self.dispatch(req)['status'])

    def test_unknown_frozen_version_blocks_without_recapture(self):
        req = self.evaluation_request(); self.conn.commit()
        lease = w.claim(self.conn, owner=self.settings.owner, lease_for=self.settings.lease_for, request_id=req['id'])
        self.conn.commit()
        with self.conn.cursor() as cur:
            from psycopg2.extras import Json
            doc = {'format': 'future', 'work_kind': 'evaluate', 'implementation': 'unknown'}
            cur.execute('INSERT INTO corner.prepared_work_commands(work_request_id,command_format_version,command_snapshot,command_sha256) VALUES (%s,%s,%s,%s)',
                        (req['id'], 'future', Json(doc), ev._digest(doc)))
        self.conn.commit(); self.expire(req)
        with patch.object(e2, 'capture', side_effect=AssertionError('cannot recapture')):
            result = self.dispatch(req, source=self.source)
        self.assertEqual('blocked', result['status']); self.assertEqual('implementation_unavailable', result['reason'])

    def test_frozen_v2_retry_retains_original_path_and_timestamps(self):
        req = self.enqueue_versioned('qualify', dict(condition_id=self.condition['id'], generation_id=self.generation['id'], engine_evaluation_id=self.evaluation_id))
        with patch.object(d, 'complete', side_effect=SystemExit('crash')):
            with self.assertRaises(SystemExit): self.dispatch(req)
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur: frozen = dict(d.prepared(cur, req['id']))
        self.expire(req)
        with patch.dict(d.HANDLERS, {'qualify.future': ('qualify', 'new-format', 'new-build')}), patch.object(d, '_prepare_static', side_effect=AssertionError('do not rebuild')):
            self.assertEqual('completed', self.dispatch(req)['status'])
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur: self.assertEqual(frozen, dict(d.prepared(cur, req['id'])))

    def test_failed_domain_write_rolls_back_but_keeps_preparation(self):
        req = self.enqueue_versioned('qualify', dict(condition_id=self.condition['id'], generation_id=self.generation['id'], engine_evaluation_id=self.evaluation_id))
        original = av.record_qualification
        def fail(*args, **kwargs): original(*args, **kwargs); raise ValueError('synthetic failure')
        with patch.object(av, 'record_qualification', side_effect=fail): self.assertEqual('blocked', self.dispatch(req)['status'])
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            frozen = d.prepared(cur, req['id']); self.assertIsNotNone(frozen)
            cur.execute('SELECT count(*) AS n FROM corner.qualification_decisions WHERE qualification_key=%s',
                        (frozen['command_snapshot']['command']['domain_command_key'],))
            self.assertEqual(0, cur.fetchone()['n'])

    def test_v1_evaluation_cannot_be_assigned_to_v2_qualification_policy(self):
        selection = self.select(configuration=self.config.analytics.engine_configuration.pricing)
        legacy = ev.record_evaluation(self.conn, authority=self.authority, evaluation_key=str(uuid4()),
            command=ev.EvaluationCommand(selection.snapshot, selection.configuration))
        with self.assertRaises(ValueError):
            self.enqueue_versioned('qualify', dict(condition_id=self.condition['id'], generation_id=self.generation['id'], engine_evaluation_id=legacy['id']))

    def test_concurrent_discovery_has_one_deterministic_request(self):
        req = self.evaluation_request(); self.assertEqual('completed', self.dispatch(req, source=self.source)['status'])
        self.conn.commit(); barrier = threading.Barrier(2)
        def scan():
            conn = self.runtime_connect()
            try:
                barrier.wait(10)
                report = r.sweep(conn, obligation='qualification', channel_id=self.channel['id'])
                conn.commit(); return self.item(report, req['id'])
            finally: conn.close()
        with ThreadPoolExecutor(max_workers=2) as pool: items = list(pool.map(lambda _: scan(), range(2)))
        self.assertEqual({'newly_requested', 'pending'}, {v['status'] for v in items})
        self.assertEqual(items[0]['request_id'], items[1]['request_id'])

    def test_competing_workers_commit_one_qualification_result(self):
        req = self.enqueue_versioned('qualify', dict(condition_id=self.condition['id'], generation_id=self.generation['id'], engine_evaluation_id=self.evaluation_id))
        self.conn.commit(); barrier = threading.Barrier(2)
        def run(owner):
            barrier.wait(10)
            return d.run_once(self.runtime_connect, settings=replace(self.settings, owner=owner), request_id=req['id'])
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(run, ('worker-x', 'worker-y')))
        self.assertEqual({'completed', 'idle'}, {v['status'] for v in results})
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            self.assertEqual('completed', d.execution(cur, w._request(cur, req['id']))['status'])

    def test_non_evaluable_v2_is_successful_qualification_completion(self):
        vf.V2AssessmentDatabaseTests.append(self, self.target_id, state='unavailable', price=None, observed_at=datetime.now(timezone.utc))
        self.conn.commit(); req = self.evaluation_request()
        self.assertEqual('completed', self.dispatch(req, source=self.source)['status'])
        item = self.item(self.sweep('qualification'), req['id'])
        result = self.dispatch({'id': item['request_id']})
        self.assertEqual('completed', result['status'], result)
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            self.assertEqual('not_qualifiable', d.decision(cur, result['execution']['qualification_decision_id'])['decision_kind'])


@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE') == '1' and os.getenv('CORNER_TEST_CONCURRENCY') == '1', 'disposable legacy dispatch DB')
class LegacyDispatchTests(Helpers, WorkDatabase, unittest.TestCase):
    setUp = old.WorkerTests.setUp
    select = old.WorkerTests.select
    evaluate = old.WorkerTests.evaluate
    qualify = old.WorkerTests.qualify
    register = old.WorkerTests.register
    capture = old.WorkerTests.capture
    command = old.WorkerTests.command
    record = old.WorkerTests.record
    app = old.WorkerTests.app
    opened = old.WorkerTests.opened
    runtime_connect = old.WorkerTests.runtime_connect
    routed = old.WorkerTests.routed

    def test_v1_evaluation_assignment_discovers_pinned_v1_qualifier(self):
        req, _ = self.routed()
        item = self.item(self.sweep('qualification'), req['id'])
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            routed = w._request(cur, item['request_id'])
        self.assertEqual('qualify.v1', routed['intent_snapshot']['intent']['dispatch']['handler'])
        result = self.dispatch({'id': item['request_id']})
        self.assertEqual('completed', result['status'], result)
        self.assertEqual('fulfilled', self.item(self.sweep('qualification'), req['id'])['status'])

    def test_frozen_v1_assessment_uses_original_interpreter(self):
        req = w.enqueue(self.conn, kind='assess', namespace=self.authority.identifier, key=str(uuid4()),
            sources=dict(condition_id=self.condition['id'], generation_id=self.generation['id'], qualification_decision_id=self.judgment['id']))
        lease = w.claim(self.conn, owner='old-worker', lease_for=timedelta(seconds=1), request_id=req['id'])
        command = self.command()
        frozen = w.prepare(self.conn, request_id=req['id'], owner='old-worker', token=lease['lease_token'], command=command,
                           authority=self.authority, domain_key=str(uuid4()))
        with self.conn.cursor() as cur:
            cur.execute("UPDATE corner.work_executions SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE work_request_id=%s", (req['id'],))
        with patch.object(a2, 'record_assessment', side_effect=AssertionError('wrong version')):
            result = self.dispatch(req)
        self.assertEqual('completed', result['status'], result)
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            self.assertEqual(frozen['command_snapshot'], d.prepared(cur, req['id'])['command_snapshot'])

    def test_existing_blocked_legacy_obligation_is_not_bypassed(self):
        from corner import reconciliation as old_r
        req, _ = self.routed()
        item = self.item(old_r.sweep(self.conn, obligation='qualification', channel_id=self.channel['id']), req['id'])
        lease = w.claim(self.conn, owner='test', lease_for=timedelta(minutes=1), request_id=item['request_id'])
        w.record_failure(self.conn, request_id=item['request_id'], owner='test', token=lease['lease_token'], status='blocked', reason='test')
        again = self.item(self.sweep('qualification'), req['id'])
        self.assertEqual('blocked', again['status']); self.assertEqual(item['request_id'], again['request_id'])

    def test_v1_lifecycle_routes_to_original_reducer(self):
        req = self.lifecycle_request('generation_activation', self.activation['id'])
        with patch.object(l2, 'apply_command', side_effect=AssertionError('wrong reducer')):
            result = self.dispatch(req)
        self.assertEqual('completed', result['status'], result)

    def test_preexisting_v1_qualification_intent_has_explicit_policy_authority(self):
        from corner import reconciliation as old_r
        req, _ = self.routed()
        item = self.item(old_r.sweep(self.conn, obligation='qualification', channel_id=self.channel['id']), req['id'])
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            original = dict(w._request(cur, item['request_id']))
        self.assertNotIn('dispatch', original['intent_snapshot']['intent'])
        self.assertEqual('completed', self.dispatch({'id': item['request_id']})['status'])
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            self.assertEqual(original, dict(w._request(cur, item['request_id'])))

    def test_generic_v1_qualification_intent_still_blocks(self):
        req = w.enqueue(self.conn, kind='qualify', namespace=self.authority.identifier, key=str(uuid4()),
            sources=dict(condition_id=self.condition['id'], generation_id=self.generation['id'], engine_evaluation_id=self.evaluation['id']))
        self.assertEqual('blocked', self.dispatch(req)['status'])

    def test_frozen_v1_evaluation_routes_to_original_engine(self):
        selection = self.select()
        req = w.enqueue(self.conn, kind='evaluate', namespace=self.authority.identifier, key=str(uuid4()),
            sources=dict(condition_id=self.condition['id'], generation_id=self.generation['id']))
        lease = w.claim(self.conn, owner='legacy', lease_for=timedelta(minutes=1), request_id=req['id'])
        w.prepare(self.conn, request_id=req['id'], owner='legacy', token=lease['lease_token'],
            command=ev.EvaluationCommand(selection.snapshot, selection.configuration), authority=self.authority, domain_key=str(uuid4()))
        with self.conn.cursor() as cur:
            cur.execute("UPDATE corner.work_executions SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE work_request_id=%s", (req['id'],))
        with patch.object(av, 'record_evaluation', side_effect=AssertionError('wrong engine')):
            result = self.dispatch(req)
        self.assertEqual('completed', result['status'], result)
