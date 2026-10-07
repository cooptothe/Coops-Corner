"""Assessment-only evidence tests; every normal DB test rolls back its fixtures."""

import copy
import json
import os
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import test_corner_ev_selection as fixtures
import test_corner_channels as channel_tests
from corner import assessments as a, channels, ev, evaluations as codec, lifecycle, qualifications as qual
from corner.dispositions import DecisionAuthority, DispositionCommand, record_disposition


@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE') == '1', 'opt-in PostgreSQL tests')
class AssessmentLedgerTests(unittest.TestCase):
    select = fixtures.EVSelectionTests.select
    append = fixtures.EVSelectionTests.append
    sql_error = channel_tests.ChannelLedgerTests.sql_error

    def setUp(self):
        fixtures.EVSelectionTests.setUp(self)
        self.authority = a.AssessmentAuthority('service', 'assessment-' + uuid4().hex)
        self.channel = channels.create_channel(self.conn, code='assessment-' + uuid4().hex, display_name='Synthetic assessment')
        self.evaluation = self.evaluate()
        self.judgment = self.qualify(self.evaluation)
        self.configuration = channels.GenerationConfiguration(
            lifecycle.ImplementationIdentity(ev.ENGINE_NAME, ev.ENGINE_VERSION, codec.ENGINE_REVISION), self.config,
            lifecycle.ImplementationIdentity('minimum_ev', '1', qual.POLICY_REVISION), qual.MinimumEVPolicy('test-policy', Decimal('.01')),
            lifecycle.ActionabilityPolicy(a.IMPLEMENTATION, timedelta(days=36500), timedelta(days=36500)))
        self.generation = self.register()
        self.phase = lifecycle.PhaseEvidence(str(uuid4()), self.event_id, 'pregame', 'Explicitly synthetic event phase')

    def evaluate(self, **changes):
        selected = self.select(**changes)
        return codec.record_evaluation(self.conn, authority=codec.EvaluationAuthority('service', self.authority.identifier),
            evaluation_key=str(uuid4()), command=codec.EvaluationCommand(selected.snapshot, selected.configuration))

    def qualify(self, evaluation, threshold='.01'):
        return qual.record_qualification(self.conn, authority=qual.QualificationAuthority('service', self.authority.identifier),
            qualification_key=str(uuid4()), command=qual.QualificationCommand(evaluation['id'],
                qual.MinimumEVPolicy('test-policy', Decimal(threshold)), self.time + timedelta(hours=2)))

    def register(self, configuration=None):
        return channels.register_generation(self.conn, authority=channels.ChannelAuthority('service', self.authority.identifier),
            registration_key=str(uuid4()), command=channels.GenerationRegistration(self.channel['id'], configuration or self.configuration))

    def capture(self, **changes):
        args = dict(generation_id=self.generation['id'], qualification_decision_id=self.judgment['id'],
                    evaluation_watermark_id=self.evaluation['id'], phase=self.phase,
                    phase_provenance_json='{"source":"synthetic-test-adapter","ticket":"AS-1"}')
        args.update(changes)
        return a.capture_assessment(self.conn, **args)

    def command(self, **changes):
        captured = self.capture(**changes)
        return a.AssessmentCommand(captured, datetime.fromisoformat(json.loads(captured)['snapshot_captured_at']))

    def record(self, command=None, key='assessment', conn=None):
        return a.record_assessment(conn or self.conn, authority=self.authority, assessment_key=key, command=command or self.command())

    def reject(self, observation_id, disposition='rejected'):
        return record_disposition(self.conn, authority=DecisionAuthority('service', 'assessment-test'),
            command=DispositionCommand(str(uuid4()), observation_id, disposition, 'Synthetic trust judgment', self.time))

    def edit_capture(self, command, change):
        capture = json.loads(command.capture_json)
        change(capture)
        return replace(command, capture_json=codec.canonical_json(capture))

    def test_complete_capture_persists_all_expected_streams_without_lifecycle_effects(self):
        row = self.record()
        self.assertTrue(row['actionable'])
        self.assertIsNone(row['primary_reason'])
        self.assertEqual(a.FORMAT_VERSION, row['snapshot_format_version'])
        self.assertEqual(codec._digest(row['command_snapshot']), bytes(row['command_sha256']))
        self.assertEqual(codec._digest(row['result_snapshot']), bytes(row['result_sha256']))
        self.assertEqual(4, len(row['result_snapshot']['reference_deadlines']))
        with self.conn.cursor() as cur:
            cur.execute('SELECT stream_role, selection_kind FROM corner.assessment_stream_evidence WHERE assessment_id=%s', (row['id'],))
            evidence = cur.fetchall()
            self.assertEqual(5, len(evidence))
            self.assertEqual(1, sum(role == 'target' for role, _ in evidence))
            self.assertEqual({'selected_trusted_observation'}, {kind for _, kind in evidence})
            cur.execute('SELECT count(*) FROM corner.channel_generation_activations WHERE channel_id=%s', (self.channel['id'],))
            self.assertEqual((0,), cur.fetchone())
            cur.execute('SELECT count(*) FROM corner.opportunity_occurrences WHERE qualification_decision_id=%s', (self.judgment['id'],))
            self.assertEqual((0,), cur.fetchone())

    def test_retry_after_market_and_trust_changes_returns_original_without_reads(self):
        command = self.command()
        original = self.record(command)
        self.append(self.target_id, price='1.50')
        self.reject(self.rows['pinnacle', 'away'][2])
        equivalent = replace(command, capture_json=json.dumps(json.loads(command.capture_json), indent=2), context_json=' { } ')
        with (patch('corner.assessments.capture_assessment', side_effect=AssertionError('no recapture')),
              patch('corner.assessments._compute', side_effect=AssertionError('no recomputation'))):
            self.assertEqual(original, self.record(equivalent))

    def test_original_capture_can_be_persisted_after_evidence_changes(self):
        command = self.command()
        self.append(self.target_id, price='1.50')
        self.reject(self.target_id)
        self.assertTrue(self.record(command)['actionable'])
        self.assertFalse(self.record(key='new-capture')['actionable'])

    def test_missing_target_and_reference_have_explicit_rows_and_rejection_witnesses(self):
        rejection = self.reject(self.target_id)
        self.reject(self.rows['pinnacle', 'away'][2])
        row = self.record()
        self.assertFalse(row['actionable'])
        self.assertIsNone(row['target_deadline'])
        self.assertIsNotNone(row['result_snapshot']['evaluated_target_deadline'])
        with self.conn.cursor() as cur:
            cur.execute('''SELECT evidence_snapshot FROM corner.assessment_stream_evidence
                WHERE assessment_id=%s AND selection_kind='missing_trusted_observation' ''', (row['id'],))
            missing = [item[0] for item in cur.fetchall()]
        self.assertEqual(2, len(missing))
        target = next(item for item in missing if item['stream_role'] == 'target')
        self.assertEqual('all_observations_rejected', target['missing_reason'])
        self.assertEqual(rejection['id'], target['missing_witnesses'][0]['disposition_id'])
        self.assertIsNone(target['quote'])

    def test_omitted_stream_and_fabricated_absence_are_validation_errors(self):
        command = self.command()
        with self.assertRaises(a.AssessmentValidationError):
            self.record(self.edit_capture(command, lambda c: c['streams'].pop()))
        def falsify(capture):
            stream = capture['streams'][0]
            stream.update(selection_kind='missing_trusted_observation', quote=None, trust=None,
                          missing_reason='no_observations', missing_witnesses=[])
        with self.assertRaises(a.AssessmentValidationError):
            self.record(self.edit_capture(command, falsify))

    def test_selected_reinstatement_is_retained_as_captured_trust(self):
        self.reject(self.target_id)
        reinstated = self.reject(self.target_id, 'reinstated')
        row = self.record()
        stream = next(s for s in row['command_snapshot']['capture']['streams'] if s['stream_role'] == 'target')
        self.assertEqual(reinstated['id'], stream['trust']['disposition_id'])
        self.assertEqual('reinstated', stream['trust']['disposition'])

    def test_inactive_changed_reference_and_phase_evidence_are_preserved(self):
        self.append(self.target_id, 'suspended', None)
        phase = replace(self.phase, phase='live', description='Synthetic transition to live')
        row = self.record(self.command(phase=phase))
        self.assertFalse(row['actionable'])
        self.assertEqual('unsupported_phase', row['primary_reason'])
        self.assertIn('target_unavailable', row['result_snapshot']['reasons'])
        self.assertEqual('synthetic-test-adapter', row['command_snapshot']['capture']['phase_provenance']['source'])
        self.assertEqual('live', row['command_snapshot']['capture']['phase']['phase'])

    def test_freshness_deadlines_and_assessed_at_are_not_evaluation_time(self):
        command = self.command()
        deadline = self.time + self.configuration.actionability_policy.target_max_age
        row = self.record(replace(command, assessed_at=deadline), 'boundary')
        self.assertTrue(row['actionable'])
        stale = self.record(replace(command, assessed_at=deadline + timedelta(microseconds=1)), 'expired')
        self.assertFalse(stale['actionable'])
        self.assertEqual('target_stale', stale['primary_reason'])
        self.assertIn('analytical_evidence_stale', stale['result_snapshot']['reasons'])
        self.assertEqual(self.evaluation['id'], row['evaluation_watermark_id'])

    def test_changed_command_conflicts_and_new_keys_preserve_separate_assessments(self):
        command = self.command()
        original = self.record(command)
        for changed in (replace(command, assessed_at=command.assessed_at + timedelta(seconds=1)),
                        replace(command, context_json='{"ticket":"changed"}'),
                        self.edit_capture(command, lambda c: c['phase'].update(description='changed phase evidence'))):
            with self.assertRaises(a.AssessmentConflict):
                self.record(changed)
        second = self.record(command, 'new-intent')
        self.assertNotEqual(original['id'], second['id'])
        self.assertEqual(bytes(original['command_sha256']), bytes(second['command_sha256']))

    def test_later_not_evaluable_watermark_is_valid_but_older_watermark_is_not(self):
        later = self.evaluate(evaluated_at=self.time + timedelta(hours=1))
        self.assertEqual('not_evaluable', later['result_kind'])
        row = self.record(self.command(evaluation_watermark_id=later['id']))
        self.assertTrue(row['actionable'])
        self.assertEqual(later['id'], row['evaluation_watermark_id'])
        newer = self.evaluate(evaluated_at=self.time + timedelta(seconds=3))
        newer_qualification = self.qualify(newer)
        with self.assertRaisesRegex(a.AssessmentValidationError, 'behind'):
            self.capture(qualification_decision_id=newer_qualification['id'])

    def test_basis_requires_same_generation_and_condition_not_current_acceptance(self):
        first = self.record()
        following = self.record(self.command(basis_assessment_id=first['id']), 'with-basis')
        self.assertEqual(first['id'], following['basis_assessment_id'])
        other_generation = self.register()
        with self.assertRaisesRegex(a.AssessmentValidationError, 'basis'):
            self.command(generation_id=other_generation['id'], basis_assessment_id=first['id'])
        away = self.rows['draftkings', 'away'][3]
        evaluation = self.evaluate(target_outcome_id=away)
        judgment = self.qualify(evaluation)
        with self.assertRaisesRegex(a.AssessmentValidationError, 'basis'):
            self.command(qualification_decision_id=judgment['id'], evaluation_watermark_id=evaluation['id'],
                         basis_assessment_id=first['id'])

    def test_generation_policy_phase_and_watermark_compatibility(self):
        incompatible = self.register(replace(self.configuration, qualification_policy=qual.MinimumEVPolicy('other', Decimal('.02'))))
        with self.assertRaisesRegex(a.AssessmentValidationError, 'configuration'):
            self.command(generation_id=incompatible['id'])
        with self.assertRaisesRegex(a.AssessmentValidationError, 'event'):
            self.command(phase=replace(self.phase, event_id=str(uuid4())))
        away = self.evaluate(target_outcome_id=self.rows['draftkings', 'away'][3])
        with self.assertRaisesRegex(a.AssessmentValidationError, 'condition'):
            self.command(evaluation_watermark_id=away['id'])

    def test_snapshot_evidence_tampering_and_unsupported_format_rejected(self):
        command = self.command()
        for edit in (
            lambda c: c.update(capture_format_version='future/99'),
            lambda c: c['bindings'].update(generation_sha256='0' * 64),
            lambda c: c['streams'][0]['quote'].update(decimal_odds='99'),
            lambda c: c['phase'].update(event_id=str(uuid4())),
        ):
            with self.assertRaises(ValueError):
                self.record(self.edit_capture(command, edit))
        with self.assertRaises(a.AssessmentValidationError):
            self.record(replace(command, assessed_at=command.assessed_at - timedelta(seconds=1)))

    def test_upstream_digest_and_format_corruption_are_validation_failures(self):
        from psycopg2.extras import Json, RealDictCursor
        for changes in ({'configuration_sha256': '\\x' + bytes(32).hex()},
                        {'snapshot_format_version': 'future/99'}):
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute('''INSERT INTO corner.qualification_channel_generations
                    SELECT (jsonb_populate_record(NULL::corner.qualification_channel_generations,
                        to_jsonb(g) || jsonb_build_object('id',uuidv7(),'registration_key',%s) || %s::jsonb)).*
                    FROM corner.qualification_channel_generations g WHERE id=%s RETURNING id''',
                    (str(uuid4()), Json(changes), self.generation['id']))
                generation_id = cur.fetchone()['id']
            with self.assertRaises(a.AssessmentValidationError):
                self.capture(generation_id=generation_id)

    def test_persistence_does_not_select_current_quotes_even_on_first_write(self):
        from psycopg2.extras import RealDictCursor
        command = self.command()
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            tracked = MagicMock(wraps=cur)
            def execute(sql, params=None):
                self.assertNotIn('trusted_current_quotes', sql)
                cur.execute(sql, params)
            tracked.execute.side_effect = execute
            wrapped = MagicMock()
            wrapped.cursor.return_value.__enter__.return_value = tracked
            self.assertTrue(self.record(command, conn=wrapped)['actionable'])

    def test_new_capture_with_same_key_conflicts_after_market_change(self):
        self.record()
        self.append(self.target_id, price='1.50')
        with self.assertRaises(a.AssessmentConflict):
            self.record(self.command())

    def test_qualified_only_fk_and_result_shape_are_database_constraints(self):
        row = self.record()
        for judgment in (self.qualify(self.evaluation, '.9'), self.qualify(self.evaluate(evaluated_at=self.time + timedelta(hours=1)))):
            with self.assertRaises(a.AssessmentValidationError):
                self.command(qualification_decision_id=judgment['id'])
            self.clone_error(row, {'qualification_decision_id': judgment['id']}, '23503', 'actionability_assessments_qualified_fk')
        self.clone_error(row, {'actionable': False, 'primary_reason': None}, '23514', 'actionability_assessments_reason_shape')

    def clone_error(self, row, changes, code, constraint):
        from psycopg2.extras import Json
        self.sql_error('''INSERT INTO corner.actionability_assessments
            SELECT (jsonb_populate_record(NULL::corner.actionability_assessments,
                to_jsonb(a) || jsonb_build_object('id',uuidv7(),'assessment_key',%s) || %s::jsonb)).*
            FROM corner.actionability_assessments a WHERE id=%s''',
            (str(uuid4()), Json(changes), row['id']), code, constraint)

    def test_append_only_and_restrict(self):
        row = self.record()
        for table in ('actionability_assessments', 'assessment_stream_evidence'):
            self.sql_error(f'UPDATE corner.{table} SET id=id', (), 'P0001')
            self.sql_error(f'DELETE FROM corner.{table}', (), 'P0001')
            self.sql_error(f'TRUNCATE corner.{table} CASCADE', (), 'P0001')
        with self.conn.cursor() as cur:
            cur.execute('ALTER TABLE corner.qualification_decisions DISABLE TRIGGER qualification_decisions_immutable')
        self.sql_error('DELETE FROM corner.qualification_decisions WHERE id=%s', (row['qualification_decision_id'],),
                       '23001', 'actionability_assessments_qualified_fk')
        with self.conn.cursor() as cur:
            cur.execute('ALTER TABLE corner.qualification_decisions ENABLE TRIGGER qualification_decisions_immutable')

    def test_missing_stream_shape_is_structural(self):
        row = self.record()
        self.sql_error('''INSERT INTO corner.assessment_stream_evidence
            (assessment_id,stream_role,sportsbook_id,outcome_id,selection_kind,evidence_snapshot)
            VALUES (%s,'reference',%s,%s,'selected_trusted_observation','{}')''',
            (row['id'], self.book_id, self.outcome_id), '23514', 'assessment_stream_evidence_selection_shape')

    def test_failure_after_header_and_first_stream_leaves_no_partial_assessment(self):
        from psycopg2.extras import RealDictCursor
        command = self.command()
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            tracked = MagicMock(wraps=cur)
            def execute(sql, params=None):
                cur.execute(sql, params)
                if sql.startswith('INSERT INTO corner.assessment_stream_evidence'):
                    raise RuntimeError('simulated stream write failure')
            tracked.execute.side_effect = execute
            wrapped = MagicMock()
            wrapped.cursor.return_value.__enter__.return_value = tracked
            with self.assertRaisesRegex(RuntimeError, 'stream write'):
                self.record(command, conn=wrapped)
        with self.conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM corner.actionability_assessments WHERE authority_id=%s', (self.authority.identifier,))
            self.assertEqual((0,), cur.fetchone())
        self.assertTrue(self.record(command)['actionable'])
