"""Discovery only: real PostgreSQL, non-owner producer, concurrency and late commits."""
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from psycopg2.extras import RealDictCursor

import test_corner_work as fixtures
from corner import reconciliation as r, work as w, channels as ch, evaluations as ev, lifecycle_store as ls


@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE') == '1' and os.getenv('CORNER_TEST_CONCURRENCY') == '1',
                     'opt-in disposable reconciliation database')
class ReconciliationTests(fixtures.WorkDatabase, unittest.TestCase):
    setUp = fixtures.WorkTests.setUp
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
    role = fixtures.WorkTests.role

    def routed(self, *, conn=None, generation=None, route=True, domain_key=None, evaluated_at=None):
        connection = conn or self.conn
        selected = self.select(**({'evaluated_at': evaluated_at} if evaluated_at else {}))
        request = w.enqueue(connection, kind='evaluate', namespace=self.authority.identifier, key=str(uuid4()),
            sources={'condition_id': self.condition['id'], 'generation_id': (generation or self.generation)['id']},
            intent_json=ev.canonical_json(r.evaluation_route(outcome_id=self.outcome_id, sportsbook_id=self.book_id)) if route else '{}')
        lease = w.claim(connection, owner='fixture', lease_for=timedelta(minutes=1), request_id=request['id'])
        w.prepare(connection, request_id=request['id'], owner='fixture', token=lease['lease_token'],
            command=ev.EvaluationCommand(selected.snapshot, selected.configuration), authority=self.authority,
            domain_key=domain_key or str(uuid4()))
        result = w.complete(connection, request_id=request['id'], owner='fixture', token=lease['lease_token'])
        return request, result

    def sweep(self, kind='qualification', **kwargs):
        if kind != 'occurrence': kwargs.setdefault('channel_id', self.channel['id'])
        return r.sweep(self.conn, obligation=kind, **kwargs)

    def item(self, report, identity):
        return next(v for v in report['items'] if v['candidate_id'] == identity)

    def table_rows(self, table):
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT * FROM corner.' + table)
            return [dict(row) for row in cur.fetchall()]

    def activate_next(self, previous=None):
        previous = previous or self.generation
        generation = self.register()
        activation = ch.activate_generation(self.conn, authority=self.authority, activation_key=str(uuid4()),
            command=ch.ActivationCommand(self.channel['id'], generation['id'], previous['id'], self.time))
        return generation, activation

    def test_repeated_discovery_creates_requests_only_under_producer_role(self):
        request, _ = self.routed()
        protected = ('engine_evaluations', 'qualification_decisions', 'opportunity_occurrences',
                     'prepared_work_commands', 'lifecycle_applications', 'opportunity_transitions',
                     'condition_processing_projections', 'opportunities')
        before = {t: self.table_rows(t) for t in protected}
        with self.role('work_producer'), patch.object(w, '_dispatch', side_effect=AssertionError('no execution')):
            first = self.sweep()
            again = self.sweep()
            self.sweep('activation')
            self.sweep('occurrence')
        self.assertEqual('newly_requested', self.item(first, request['id'])['status'])
        self.assertEqual('pending', self.item(again, request['id'])['status'])
        self.assertEqual(first['items'][0]['request_id'], again['items'][0]['request_id'])
        self.assertEqual(before, {t: self.table_rows(t) for t in protected})

    def test_manual_evaluation_is_not_implicitly_routed(self):
        self.assertEqual([], self.sweep()['items'])  # setup contains a manual evaluation
        request, _ = self.routed(route=False)
        item = self.item(self.sweep(), request['id'])
        self.assertEqual('invalid', item['status'])
        self.assertIn('route', item['reason'])

    def test_unfinished_evaluate_request_is_not_assignment(self):
        w.enqueue(self.conn, kind='evaluate', namespace=self.authority.identifier, key='unfinished',
                  sources={'condition_id': self.condition['id'], 'generation_id': self.generation['id']})
        self.assertEqual([], self.sweep()['items'])

    def test_matching_manual_qualification_fulfills_without_occurrence(self):
        request, execution = self.routed()
        judgment = self.qualify({'id': execution['engine_evaluation_id']})
        self.assertEqual('fulfilled', self.item(self.sweep(), request['id'])['status'])
        result = self.item(self.sweep('occurrence'), judgment['id'])
        self.assertEqual('newly_requested', result['status'])
        self.assertEqual('pending', self.item(self.sweep('occurrence'), judgment['id'])['status'])
        ch.create_occurrence(self.conn, qualification_decision_id=judgment['id'])
        self.assertEqual('fulfilled', self.item(self.sweep('occurrence'), judgment['id'])['status'])

    def test_different_threshold_does_not_fulfill(self):
        request, execution = self.routed()
        self.qualify({'id': execution['engine_evaluation_id']}, threshold='.90')
        self.assertEqual('newly_requested', self.item(self.sweep(), request['id'])['status'])

    def test_not_evaluable_requires_qualification_but_no_occurrence(self):
        request, execution = self.routed(evaluated_at=self.time + timedelta(days=1))
        self.assertEqual('newly_requested', self.item(self.sweep(), request['id'])['status'])
        judgment = self.qualify({'id': execution['engine_evaluation_id']})
        self.assertEqual('not_qualifiable', judgment['decision_kind'])
        self.assertEqual('fulfilled', self.item(self.sweep(), request['id'])['status'])
        self.assertNotIn(judgment['id'], {v['candidate_id'] for v in self.sweep('occurrence')['items']})

    def test_blocked_request_is_visible_without_bypass_and_cursor_advances(self):
        first, _ = self.routed()
        second, _ = self.routed()
        result = self.sweep(limit=1)
        request_id = result['items'][0]['request_id']
        lease = w.claim(self.conn, owner='fixture', lease_for=timedelta(minutes=1), request_id=request_id)
        w.record_failure(self.conn, request_id=request_id, owner='fixture', token=lease['lease_token'],
                         status='blocked', reason='operator_required')
        again = self.sweep(limit=1)
        self.assertEqual('blocked', again['items'][0]['status'])
        self.assertEqual(request_id, again['items'][0]['request_id'])
        next_page = self.sweep(after=again['next_cursor'], limit=1)
        self.assertEqual(second['id'], next_page['items'][0]['candidate_id'])
        self.assertEqual('newly_requested', next_page['items'][0]['status'])
        self.assertIsNone(next_page['next_cursor'])
        self.assertEqual(first['id'], self.sweep(after=next_page['next_cursor'], limit=1)['items'][0]['candidate_id'])

    def test_activation_discovers_first_then_each_immediate_successor(self):
        g2, a2 = self.activate_next()
        g3, a3 = self.activate_next(g2)
        first = self.item(self.sweep('activation'), self.condition['id'])
        def source(item):
            return next(row['channel_generation_activation_id'] for row in self.table_rows('work_requests') if row['id'] == item['request_id'])
        self.assertEqual(self.activation['id'], source(first))
        self.assertEqual('pending', self.item(self.sweep('activation'), self.condition['id'])['status'])
        self.app('generation_activation')
        second = self.item(self.sweep('activation'), self.condition['id'])
        self.assertEqual(a2['id'], source(second))
        self.app('generation_activation', a2, generation=g2, at=self.time)
        third = self.item(self.sweep('activation'), self.condition['id'])
        self.assertEqual(a3['id'], source(third))
        self.app('generation_activation', a3, generation=g3, at=self.time)
        self.assertEqual('fulfilled', self.item(self.sweep('activation'), self.condition['id'])['status'])

    def test_activation_uses_history_without_projections(self):
        self.app('generation_activation')
        _, next_activation = self.activate_next()
        with self.conn.cursor() as cur:
            cur.execute('DELETE FROM corner.condition_processing_projections WHERE condition_id=%s', (self.condition['id'],))
        report = self.item(self.sweep('activation'), self.condition['id'])
        request = next(row for row in self.table_rows('work_requests') if row['id'] == report['request_id'])
        self.assertEqual(next_activation['id'], request['channel_generation_activation_id'])
        self.assertFalse(any(row['condition_id'] == self.condition['id'] for row in self.table_rows('condition_processing_projections')))

    def test_corrupt_processed_activation_marker_is_not_completion_proof(self):
        self.app('generation_activation')
        g2, a2 = self.activate_next()
        # A malformed claimed marker is detected, not accepted merely because a
        # receipt mentions an activation. Injection is read-side, never ledger mutation.
        original = ls._verify_receipt
        def wrong_marker(cur, row):
            result = original(cur, row)
            return result | {'post_state': result['post_state'] | {'activation_id': a2['id']}}
        with patch.object(ls, '_verify_receipt', side_effect=wrong_marker):
            self.assertEqual('invalid', self.item(self.sweep('activation'), self.condition['id'])['status'])

    def test_ignored_out_of_order_activation_is_not_completion_proof(self):
        self.app('generation_activation')
        g2, a2 = self.activate_next()
        g3, a3 = self.activate_next(g2)
        ignored = self.app('generation_activation', a3, generation=g3, at=self.time)
        self.assertEqual('ignored', ignored['application_outcome'])
        first = self.item(self.sweep('activation'), self.condition['id'])
        request = next(row for row in self.table_rows('work_requests') if row['id'] == first['request_id'])
        self.assertEqual(a2['id'], request['channel_generation_activation_id'])
        self.app('generation_activation', a2, generation=g2, at=self.time)
        second = self.item(self.sweep('activation'), self.condition['id'])
        request = next(row for row in self.table_rows('work_requests') if row['id'] == second['request_id'])
        self.assertEqual('newly_requested', second['status'])
        self.assertEqual(a3['id'], request['channel_generation_activation_id'])

    def test_completed_work_with_wrong_policy_is_integrity_failure(self):
        from corner import qualifications as q
        from decimal import Decimal
        request, result = self.routed()
        discovered = self.item(self.sweep(), request['id'])['request_id']
        lease = w.claim(self.conn, owner='fixture', lease_for=timedelta(minutes=1), request_id=discovered)
        w.prepare(self.conn, request_id=discovered, owner='fixture', token=lease['lease_token'], authority=self.authority,
                  domain_key=str(uuid4()), command=q.QualificationCommand(result['engine_evaluation_id'],
                  q.MinimumEVPolicy('wrong-policy', Decimal('.90')), self.time))
        w.complete(self.conn, request_id=discovered, owner='fixture', token=lease['lease_token'])
        before = len(self.table_rows('work_requests'))
        outcome = self.item(self.sweep(), request['id'])
        self.assertEqual('invalid', outcome['status'])
        self.assertIn('does not fulfill', outcome['reason'])
        self.assertEqual(before, len(self.table_rows('work_requests')))

    def test_concurrent_occurrence_and_activation_discovery_converges(self):
        judgment = self.qualify(self.evaluation)
        self.conn.commit()
        for kind, identity in (('occurrence', judgment['id']), ('activation', self.condition['id'])):
            barrier = threading.Barrier(2)
            def scan():
                conn = self.connect()
                try:
                    barrier.wait(timeout=10)
                    report = r.sweep(conn, obligation=kind, **({'channel_id': self.channel['id']} if kind == 'activation' else {}))
                    conn.commit()
                    return self.item(report, identity)
                finally:
                    conn.close()
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: scan(), range(2)))
            self.assertEqual({'newly_requested', 'pending'}, {v['status'] for v in results})
            self.assertEqual(1, len({v['request_id'] for v in results}))

    def test_concurrent_scans_converge(self):
        request, _ = self.routed()
        self.conn.commit()
        barrier = threading.Barrier(2)
        def scan():
            conn = self.connect()
            try:
                barrier.wait(timeout=10)
                report = r.sweep(conn, obligation='qualification', channel_id=self.channel['id'])
                conn.commit()
                return self.item(report, request['id'])
            finally:
                conn.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: scan(), range(2)))
        self.assertEqual({'newly_requested', 'pending'}, {v['status'] for v in results})
        self.assertEqual(1, len({v['request_id'] for v in results}))

    def test_late_commit_behind_cursor_is_discovered_after_wrap(self):
        self.conn.commit()
        producer = self.connect()
        try:
            late, _ = self.routed(conn=producer)
            visible, _ = self.routed()
            extra, _ = self.routed()
            self.conn.commit()
            self.assertLess(late['id'], visible['id'])
            page = self.sweep(limit=1)
            self.assertEqual(visible['id'], page['items'][0]['candidate_id'])
            self.conn.commit()
            producer.commit()
            tail = self.sweep(after=page['next_cursor'], limit=1)
            self.assertEqual(extra['id'], tail['items'][0]['candidate_id'])
            self.assertIsNone(tail['next_cursor'])
            self.conn.commit()
            wrapped = self.sweep(after=tail['next_cursor'], limit=1)
            self.assertEqual(late['id'], wrapped['items'][0]['candidate_id'])
            self.assertEqual('newly_requested', wrapped['items'][0]['status'])
        finally:
            producer.close()

    def test_two_generations_require_explicit_assignments_and_share_no_dedupe(self):
        first, _ = self.routed(domain_key='same-evaluation')
        second_generation = self.register()
        # Identical config does not itself create a second assignment.
        self.assertEqual(1, len(self.sweep()['items']))
        second, _ = self.routed(generation=second_generation, domain_key='same-evaluation')
        report = self.sweep()
        self.assertNotEqual(self.item(report, first['id'])['request_id'], self.item(report, second['id'])['request_id'])

    def test_duplicate_routes_converge_to_same_obligation(self):
        first, _ = self.routed(domain_key='same-evaluation')
        second, _ = self.routed(domain_key='same-evaluation')
        report = self.sweep()
        self.assertEqual(self.item(report, first['id'])['request_id'], self.item(report, second['id'])['request_id'])

    def test_corrupt_qualification_is_invalid_not_fulfilled(self):
        request, result = self.routed()
        self.qualify({'id': result['engine_evaluation_id']})
        original = r._qualification
        def corrupt(cur, row):
            return original(cur, dict(row) | {'decision_kind': 'not_qualified'})
        with patch.object(r, '_qualification', side_effect=corrupt):
            item = self.item(self.sweep(), request['id'])
        self.assertEqual('invalid', item['status'])
        self.assertIn('contradicts', item['reason'])

    def test_invalid_candidate_does_not_stop_later_candidates(self):
        bad, _ = self.routed(route=False)
        good, _ = self.routed()
        report = self.sweep()
        self.assertEqual('invalid', self.item(report, bad['id'])['status'])
        self.assertEqual('newly_requested', self.item(report, good['id'])['status'])

    def test_invalid_page_arguments_are_rejected(self):
        for limit in (0, -1, 1001, True):
            with self.assertRaises(r.ReconciliationError): self.sweep(limit=limit)
        with self.assertRaises(r.ReconciliationError):
            r.sweep(self.conn, obligation='occurrence', channel_id=self.channel['id'])
