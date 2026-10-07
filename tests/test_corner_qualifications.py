"""Policy boundaries and rollback-only qualification ledger tests."""

import copy
import os
import unittest
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import test_corner_ev_selection as fixtures
from corner.evaluations import EvaluationAuthority, EvaluationCommand, record_evaluation, _digest
from corner.qualifications import (
    MinimumEVPolicy, QualificationAuthority, QualificationCommand, QualificationConflict,
    QualificationValidationError, qualify_evaluation, record_qualification,
)


def synthetic_result(value='0.009999999', kind='evaluated'):
    """Synthetic persisted-result envelope; deliberately not a real engine run."""
    reason = 'insufficient_reference_coverage' if kind == 'not_evaluable' else None
    result = {'result_kind': kind, 'non_evaluation_reason': reason,
              'ev_ratio': value, 'fair_probability': '0.5' if kind == 'evaluated' else None,
              'reference_book_count': 2 if kind == 'evaluated' else 0,
              'reference_estimates': [], 'reference_exclusions': []}
    return {'snapshot_format_version': 'corner.ev.snapshot/1', 'result_snapshot': result,
            'result_sha256': _digest(result), 'result_kind': kind, 'non_evaluation_reason': reason,
            'ev_ratio': Decimal(value).quantize(Decimal('.00000001')) if value is not None else None,
            'fair_probability': Decimal('.5') if kind == 'evaluated' else None}


class QualificationPolicyTests(unittest.TestCase):
    def test_full_precision_boundaries_zero_and_negative(self):
        policy = MinimumEVPolicy('v1', Decimal('.01000000'))
        for value, expected in [('0.0100000000001', 'qualified'), ('0.01000000', 'qualified'),
                                ('0.009999999', 'not_qualified'), ('0', 'not_qualified'),
                                ('-0.02', 'not_qualified')]:
            with self.subTest(value=value):
                evaluation = synthetic_result(value)
                result = qualify_evaluation(evaluation, policy)
                self.assertEqual(expected, result.decision_kind)
                self.assertEqual(Decimal(value), result.compared_ev)
        self.assertEqual(Decimal('.01000000'), synthetic_result()['ev_ratio'])

    def test_non_evaluable_is_not_qualifiable(self):
        result = qualify_evaluation(synthetic_result(None, 'not_evaluable'), MinimumEVPolicy('v1', Decimal('.01')))
        self.assertEqual('not_qualifiable', result.decision_kind)
        self.assertEqual('evaluation_not_evaluable', result.reason_code)
        self.assertIsNone(result.compared_ev)

    def test_missing_and_malformed_ev_fail_even_with_matching_digest(self):
        for value in (None, '', 'NaN', 'Infinity', 'garbage', 0.01, '1e-2'):
            evaluation = synthetic_result()
            evaluation['result_snapshot']['ev_ratio'] = value
            evaluation['result_sha256'] = _digest(evaluation['result_snapshot'])
            with self.subTest(value=value), self.assertRaises(QualificationValidationError):
                qualify_evaluation(evaluation, MinimumEVPolicy('v1', Decimal('.01')))
        evaluation = synthetic_result()
        del evaluation['result_snapshot']['ev_ratio']
        evaluation['result_sha256'] = _digest(evaluation['result_snapshot'])
        with self.assertRaises(QualificationValidationError):
            qualify_evaluation(evaluation, MinimumEVPolicy('v1', Decimal('.01')))

    def test_digest_format_and_shape_errors_are_validation_failures(self):
        original = synthetic_result()
        for changes in ({'result_sha256': bytes(32)}, {'snapshot_format_version': 'future/99'},
                        {'result_kind': 'not_evaluable'}):
            with self.assertRaises(QualificationValidationError):
                qualify_evaluation(original | changes, MinimumEVPolicy('v1', Decimal('.01')))

    def test_threshold_must_be_strictly_positive_decimal(self):
        for threshold in (Decimal('0'), Decimal('-1'), Decimal('NaN'), Decimal('Infinity'), 0.01):
            with self.assertRaises(QualificationValidationError):
                MinimumEVPolicy('v1', threshold)


@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE') == '1', 'opt-in PostgreSQL tests')
class QualificationLedgerTests(unittest.TestCase):
    select = fixtures.EVSelectionTests.select
    append = fixtures.EVSelectionTests.append

    def setUp(self):
        fixtures.EVSelectionTests.setUp(self)
        selected = self.select()
        self.evaluation = record_evaluation(self.conn, authority=EvaluationAuthority('service', 'qual-test'),
            evaluation_key='evaluation', command=EvaluationCommand(selected.snapshot, selected.configuration))
        self.command = QualificationCommand(self.evaluation['id'], MinimumEVPolicy('v1', Decimal('.01')),
                                            self.time + timedelta(minutes=10), '{"ticket":"Q1","tags":["a","b"]}')

    def record(self, command=None, key='judgment', authority=None, conn=None):
        return record_qualification(conn or self.conn,
            authority=authority or QualificationAuthority('service', 'qual-test'), qualification_key=key,
            command=command or self.command)

    def assert_sql_error(self, sql, params, code, constraint=None):
        import psycopg2
        with self.conn.cursor() as cur:
            cur.execute('SAVEPOINT expected_error')
            try:
                with self.assertRaises(psycopg2.Error) as caught:
                    cur.execute(sql, params)
                self.assertEqual(code, caught.exception.pgcode)
                if constraint:
                    self.assertEqual(constraint, caught.exception.diag.constraint_name)
            finally:
                cur.execute('ROLLBACK TO SAVEPOINT expected_error')
                cur.execute('RELEASE SAVEPOINT expected_error')

    def clone_evaluation(self, changes):
        """Insert synthetic test evidence with no input links, always rolled back."""
        from psycopg2.extras import Json, RealDictCursor
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('''INSERT INTO corner.engine_evaluations
                SELECT (jsonb_populate_record(NULL::corner.engine_evaluations,
                    to_jsonb(e) || jsonb_build_object('id', uuidv7(), 'evaluation_key', %s) || %s::jsonb)).*
                FROM corner.engine_evaluations e WHERE e.id=%s RETURNING *''',
                (str(uuid4()), Json(changes), self.evaluation['id']))
            return dict(cur.fetchone())

    def test_persisted_full_precision_boundary(self):
        for value, expected in [('0.0100000000001','qualified'), ('0.01','qualified'),
                                ('0.009999999','not_qualified'), ('0','not_qualified'), ('-0.02','not_qualified')]:
            envelope = synthetic_result(value)
            row = self.clone_evaluation({'result_snapshot': envelope['result_snapshot'],
                'result_sha256': '\\x' + envelope['result_sha256'].hex(), 'ev_ratio': str(envelope['ev_ratio']),
                'fair_probability': '0.5'})
            stored = self.record(replace(self.command, engine_evaluation_id=row['id']), key=str(uuid4()))
            self.assertEqual(expected, stored['decision_kind'])
            self.assertEqual(Decimal(value), Decimal(stored['result_snapshot']['compared_ev']))

    def test_identical_retry_semantic_context_and_multiple_policy_judgments(self):
        first = self.record()
        equivalent = replace(self.command, context_json='{ "tags": ["a", "b"], "ticket": "Q1" }',
                             policy=MinimumEVPolicy('v1', Decimal('.0100000')))
        self.assertEqual(first, self.record(equivalent))
        second = self.record(key='second-intent')
        third = self.record(replace(self.command, policy=MinimumEVPolicy('v2', Decimal('.9'))), key='new-policy')
        fourth = self.record(authority=QualificationAuthority('human', 'another-actor'))
        self.assertEqual(4, len({r['id'] for r in (first, second, third, fourth)}))
        self.assertEqual('qualified', first['decision_kind'])
        self.assertEqual('not_qualified', third['decision_kind'])
        self.assertEqual(bytes(first['command_sha256']), bytes(second['command_sha256']))
        self.assertEqual(bytes(self.evaluation['result_sha256']), bytes(first['evaluation_result_sha256']))

    def test_changed_command_conflicts(self):
        self.record()
        other = self.clone_evaluation({})
        for changes in (
            {'policy': MinimumEVPolicy('v1', Decimal('.02'))},
            {'policy': MinimumEVPolicy('v2', Decimal('.01'))},
            {'engine_evaluation_id': other['id']}, {'context_json': '{"ticket":"Q2"}'},
            {'decided_at': self.command.decided_at + timedelta(microseconds=1)},
        ):
            with self.assertRaises(QualificationConflict):
                self.record(replace(self.command, **changes))
        with patch('corner.qualifications.POLICY_REVISION', 'sha256:new'), self.assertRaises(QualificationConflict):
            self.record()

    def test_non_evaluation_qualifies_without_engine_execution(self):
        selected = self.select(evaluated_at=self.time + timedelta(hours=1))
        evaluation = record_evaluation(self.conn, authority=EvaluationAuthority('service', 'qual-test'),
            evaluation_key='stale', command=EvaluationCommand(selected.snapshot, selected.configuration))
        with patch('corner.ev.evaluate_ev', side_effect=AssertionError('must not run engine')):
            decision = self.record(replace(self.command, engine_evaluation_id=evaluation['id']))
        self.assertEqual('not_qualifiable', decision['decision_kind'])
        self.assertIsNone(decision['result_snapshot']['compared_ev'])

    def test_corruption_and_unknown_format_leave_no_decision(self):
        malformed = copy.deepcopy(self.evaluation['result_snapshot'])
        malformed.pop('ev_ratio')
        for changes in (
            {'result_sha256': '\\x' + bytes(32).hex()},
            {'snapshot_format_version': 'future/99'},
            {'result_snapshot': malformed, 'result_sha256': '\\x' + _digest(malformed).hex()},
        ):
            row = self.clone_evaluation(changes)
            with self.assertRaises(QualificationValidationError):
                self.record(replace(self.command, engine_evaluation_id=row['id']))
        with self.conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM corner.qualification_decisions WHERE authority_id=%s', ('qual-test',))
            self.assertEqual((0,), cur.fetchone())

    def test_composite_fk_rejects_wrong_digest(self):
        decision = self.record()
        self.assert_sql_error('''INSERT INTO corner.qualification_decisions
            SELECT (jsonb_populate_record(NULL::corner.qualification_decisions,
                to_jsonb(q) || jsonb_build_object('id',uuidv7(),'qualification_key','bad-digest',
                    'evaluation_result_sha256',%s::text))).*
            FROM corner.qualification_decisions q WHERE id=%s''',
            ('\\x' + bytes(32).hex(), decision['id']), '23503', 'qualification_decisions_evaluation_result_fk')

    def test_mutation_and_delete_restriction(self):
        evaluation = self.clone_evaluation({})
        decision = self.record(replace(self.command, engine_evaluation_id=evaluation['id']))
        for sql in ('UPDATE corner.qualification_decisions SET reason_code=reason_code WHERE id=%s',
                    'DELETE FROM corner.qualification_decisions WHERE id=%s'):
            self.assert_sql_error(sql, (decision['id'],), 'P0001')
        # Migration 009 adds referencing occurrences. CASCADE passes PostgreSQL's
        # FK precheck so this still proves the ledger's own no-TRUNCATE trigger.
        # The trigger rejects the statement; the helper also rolls back its savepoint.
        self.assert_sql_error('TRUNCATE corner.qualification_decisions CASCADE', (), 'P0001')
        with self.conn.cursor() as cur:
            cur.execute('ALTER TABLE corner.engine_evaluations DISABLE TRIGGER engine_evaluations_immutable')
        self.assert_sql_error('DELETE FROM corner.engine_evaluations WHERE id=%s', (evaluation['id'],),
                              '23001', 'qualification_decisions_evaluation_result_fk')
        with self.conn.cursor() as cur:
            cur.execute('ALTER TABLE corner.engine_evaluations ENABLE TRIGGER engine_evaluations_immutable')

    def test_failure_after_insert_rolls_back_decision(self):
        from psycopg2.extras import RealDictCursor
        wrapped = MagicMock()
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            tracked = MagicMock(wraps=cur)
            def execute(sql, params=None):
                cur.execute(sql, params)
                if sql.startswith('INSERT INTO corner.qualification_decisions'):
                    raise RuntimeError('simulated post-insert failure')
            tracked.execute.side_effect = execute
            wrapped.cursor.return_value.__enter__.return_value = tracked
            with self.assertRaisesRegex(RuntimeError, 'simulated'):
                self.record(conn=wrapped)
        with self.conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM corner.qualification_decisions WHERE engine_evaluation_id=%s',
                        (self.evaluation['id'],))
            self.assertEqual((0,), cur.fetchone())
        self.assertEqual('qualified', self.record()['decision_kind'])
