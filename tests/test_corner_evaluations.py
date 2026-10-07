"""Evaluation serialization and rollback-only ledger integration tests."""

import hashlib
import json
import os
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from unittest.mock import MagicMock, patch
from uuid import uuid4

import test_corner_ev_selection as fixture_helpers
from corner import ev
from corner.evaluations import (
    EvaluationAuthority, EvaluationCommand, EvaluationConflict, DeterminismFailure,
    _encode, canonical_json, deserialize_command, record_evaluation, serialize_command,
)


class EvaluationSerializationTests(unittest.TestCase):
    def test_decimal_is_exact_without_ambient_precision(self):
        with localcontext() as context:
            context.prec = 3
            self.assertEqual('123.456789', _encode(Decimal('123.45678900')))
            self.assertEqual('0', _encode(Decimal('-0.000')))
        with self.assertRaises(ValueError):
            _encode(1.2)

    def test_uuid_and_timestamp_canonical_forms(self):
        value = uuid4()
        self.assertEqual(str(value), _encode(str(value).upper(), 'observation_id'))
        moment = datetime(2026, 9, 22, 7, 1, 2, 34, timezone(timedelta(hours=-5)))
        self.assertEqual('2026-09-22T12:01:02.000034Z', _encode(moment))
        with self.assertRaises(ValueError):
            _encode(moment.replace(tzinfo=None))


@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE') == '1', 'opt-in PostgreSQL tests')
class EvaluationLedgerTests(unittest.TestCase):
    setUp = fixture_helpers.EVSelectionTests.setUp
    select = fixture_helpers.EVSelectionTests.select
    append = fixture_helpers.EVSelectionTests.append

    def command(self, **selection_changes):
        selection = self.select(**selection_changes)
        return EvaluationCommand(selection.snapshot, selection.configuration, '{"ticket":"EV-1"}')

    def record(self, command=None, key='execution-1', authority=None, conn=None):
        return record_evaluation(conn or self.conn,
            authority=authority or EvaluationAuthority('service', 'ev-test'),
            evaluation_key=key, command=command or self.command())

    def test_typed_columns_snapshots_hashes_inputs_and_replay(self):
        command = self.command()
        row = self.record(command)
        result = ev.evaluate_ev(command.snapshot, command.configuration)
        self.assertEqual('evaluated', row['result_kind'])
        self.assertEqual(2, row['reference_book_count'])
        self.assertEqual(result.fair_probability.quantize(Decimal('.0000000001')), row['fair_probability'])
        self.assertEqual(Decimal(row['result_snapshot']['fair_probability']), result.fair_probability)
        self.assertGreater(len(row['result_snapshot']['fair_probability']), 12)
        for name in ('command', 'result'):
            expected = hashlib.sha256(canonical_json(row[name + '_snapshot']).encode('utf-8')).digest()
            self.assertEqual(expected, bytes(row[name + '_sha256']))
        self.assertTrue(row['engine_revision'].startswith('sha256:'))
        replay = deserialize_command(row['command_snapshot'])
        self.assertEqual(result.ev_ratio, ev.evaluate_ev(replay.snapshot, replay.configuration).ev_ratio)
        with self.conn.cursor() as cur:
            cur.execute('SELECT observation_id, role FROM corner.engine_evaluation_inputs WHERE evaluation_id=%s', (row['id'],))
            inputs = dict(cur.fetchall())
        self.assertEqual({q.observation_id for q in command.snapshot.quotes}, set(inputs))
        self.assertEqual('target', inputs[self.target_id])
        self.assertEqual(1, list(inputs.values()).count('target'))

    def test_semantically_identical_retry_preserves_record_and_timestamps(self):
        command = self.command()
        first = self.record(command)
        snapshot = replace(command.snapshot, quotes=tuple(reversed(command.snapshot.quotes)),
            evaluated_at=command.snapshot.evaluated_at.astimezone(timezone(timedelta(hours=-5))),
            contract=replace(command.snapshot.contract, outcomes=tuple(reversed(command.snapshot.contract.outcomes))))
        config = replace(command.configuration, reference_sportsbook_ids=tuple(reversed(self.reference_ids)))
        retry = EvaluationCommand(snapshot, config, '{ "ticket" : "EV-1" }')
        self.assertEqual(first, self.record(retry))

    def test_new_key_or_authority_preserves_distinct_execution_same_digest(self):
        first = self.record()
        second = self.record(key='execution-2')
        third = self.record(authority=EvaluationAuthority('service', 'another-worker'))
        self.assertEqual(3, len({first['id'], second['id'], third['id']}))
        self.assertEqual(bytes(first['command_sha256']), bytes(second['command_sha256']))

    def test_negative_and_zero_estimates_are_persisted_as_evaluated(self):
        # Both references at 2.0/2.0 make a fair probability of 0.5.
        for side in ('home', 'away'):
            self.append(self.rows['pinnacle', side][2], price='2')
        for index, (price, expected) in enumerate([('1.9', '-0.05'), ('2', '0')]):
            self.append(self.target_id, price=price, observed_at=self.time + timedelta(seconds=index + 1))
            row = self.record(key=str(index))
            self.assertEqual('evaluated', row['result_kind'])
            self.assertEqual(Decimal(expected), row['ev_ratio'])
            self.assertIsNone(row['non_evaluation_reason'])

    def test_unknown_build_cannot_be_replayed_as_current_engine(self):
        document = serialize_command(self.command())
        document['engine_revision'] = 'sha256:other-build'
        with self.assertRaisesRegex(ValueError, 'original engine'):
            deserialize_command(document)

    def test_changed_command_conflicts_for_each_boundary(self):
        command = self.command()
        self.record(command)
        for changed in (
            replace(command, context_json='{"ticket":"EV-2"}'),
            replace(command, configuration=replace(command.configuration, version='new')),
            replace(command, snapshot=replace(command.snapshot, evaluated_at=self.time)),
            replace(command, snapshot=replace(command.snapshot, phase_evidence='different authority')),
            replace(command, snapshot=replace(command.snapshot,
                contract=replace(command.snapshot.contract, settlement_evidence='different rules'))),
        ):
            with self.assertRaises(EvaluationConflict):
                self.record(changed)
        with patch('corner.evaluations.ENGINE_REVISION', 'sha256:changed'), self.assertRaises(EvaluationConflict):
            self.record(command)

    def test_non_evaluation_retains_excluded_evidence_and_no_fake_missing_input(self):
        latest = self.append(self.rows['pinnacle', 'away'][2], 'unavailable', None)
        row = self.record()
        self.assertEqual('not_evaluable', row['result_kind'])
        self.assertEqual('insufficient_reference_coverage', row['non_evaluation_reason'])
        self.assertIsNone(row['fair_probability'])
        self.assertIsNone(row['ev_ratio'])
        with self.conn.cursor() as cur:
            cur.execute('SELECT role FROM corner.engine_evaluation_inputs WHERE evaluation_id=%s AND observation_id=%s', (row['id'], latest))
            self.assertEqual(('reference',), cur.fetchone())
        excluded = row['result_snapshot']['reference_exclusions']
        self.assertIn(latest, {oid for item in excluded for oid in item['observation_ids']})

    def test_contradictory_evidence_is_rejected_without_partial_write(self):
        command = self.command()
        quotes = tuple(replace(q, decimal_odds=Decimal('8')) if q.observation_id == self.target_id else q
                       for q in command.snapshot.quotes)
        with self.assertRaisesRegex(ValueError, 'contradicts'):
            self.record(replace(command, snapshot=replace(command.snapshot, quotes=quotes)))
        # Savepoint rollback keeps caller's transaction usable and the key available.
        self.assertEqual('evaluated', self.record(command)['result_kind'])

    def assert_sql_error(self, sql, params, code):
        import psycopg2
        with self.conn.cursor() as cur:
            cur.execute('SAVEPOINT expected_error')
            try:
                with self.assertRaises(psycopg2.Error) as caught:
                    cur.execute(sql, params)
                self.assertEqual(code, caught.exception.pgcode)
            finally:
                cur.execute('ROLLBACK TO SAVEPOINT expected_error')
                cur.execute('RELEASE SAVEPOINT expected_error')

    def test_append_only_and_input_constraints(self):
        row = self.record()
        for table, where in [('engine_evaluations', 'id'), ('engine_evaluation_inputs', 'evaluation_id')]:
            self.assert_sql_error(f'DELETE FROM corner.{table} WHERE {where}=%s', (row['id'],), 'P0001')
            self.assert_sql_error(f'UPDATE corner.{table} SET id=id WHERE {where}=%s', (row['id'],), 'P0001')
            self.assert_sql_error(f'TRUNCATE corner.{table} CASCADE', (), 'P0001')
        self.assert_sql_error('''INSERT INTO corner.engine_evaluation_inputs (evaluation_id, observation_id, role)
            VALUES (%s,%s,'target')''', (row['id'], self.rows['draftkings', 'away'][2]), '23505')
        self.assert_sql_error('''INSERT INTO corner.engine_evaluation_inputs (evaluation_id, observation_id, role)
            VALUES (%s,%s,'reference')''', (row['id'], self.target_id), '23505')

    def test_structural_result_checks(self):
        row = self.record()
        with self.conn.cursor() as cur:
            cur.execute('ALTER TABLE corner.engine_evaluations DISABLE TRIGGER engine_evaluations_immutable')
        for assignment in ("fair_probability=NULL", "fair_probability=1.1", "non_evaluation_reason='stale_target'",
                           "reference_book_count=-1", "result_kind='pending'", "ev_ratio='NaN'::numeric"):
            self.assert_sql_error(f'UPDATE corner.engine_evaluations SET {assignment} WHERE id=%s', (row['id'],), '23514')
        with self.conn.cursor() as cur:
            cur.execute('ALTER TABLE corner.engine_evaluations ENABLE TRIGGER engine_evaluations_immutable')

    def test_restrict_protects_header_and_observations(self):
        row = self.record()
        with self.conn.cursor() as cur:
            cur.execute('ALTER TABLE corner.engine_evaluations DISABLE TRIGGER engine_evaluations_immutable')
            cur.execute('ALTER TABLE corner.odds_observations DISABLE TRIGGER odds_observations_immutable')
        self.assert_sql_error('DELETE FROM corner.engine_evaluations WHERE id=%s', (row['id'],), '23001')
        self.assert_sql_error('DELETE FROM corner.odds_observations WHERE id=%s', (self.target_id,), '23001')
        with self.conn.cursor() as cur:
            cur.execute('ALTER TABLE corner.engine_evaluations ENABLE TRIGGER engine_evaluations_immutable')
            cur.execute('ALTER TABLE corner.odds_observations ENABLE TRIGGER odds_observations_immutable')

    def test_atomicity_when_input_insert_fails(self):
        wrapped = MagicMock()
        from psycopg2.extras import RealDictCursor
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            tracked = MagicMock(wraps=cur)
            tracked.executemany.side_effect = RuntimeError('simulated input write failure')
            wrapped.cursor.return_value.__enter__.return_value = tracked
            with self.assertRaisesRegex(RuntimeError, 'simulated'):
                self.record(conn=wrapped)
        with self.conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM corner.engine_evaluations WHERE target_observation_id=%s', (self.target_id,))
            self.assertEqual((0,), cur.fetchone())

    def test_race_loser_detects_different_result_and_keeps_original(self):
        command = self.command()
        original = self.record(command)
        wrapped = MagicMock()
        from psycopg2.extras import RealDictCursor
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            tracked = MagicMock(wraps=cur)
            calls = [0]
            def fetchone():
                calls[0] += 1
                return None if calls[0] == 1 else cur.fetchone()
            tracked.fetchone.side_effect = fetchone
            wrapped.cursor.return_value.__enter__.return_value = tracked
            # Simulate preflight missing a concurrent winner, then a defective result.
            bad = replace(ev.evaluate_ev(command.snapshot, command.configuration), ev_ratio=Decimal('.123'))
            with patch('corner.evaluations.ev.evaluate_ev', return_value=bad), self.assertRaises(DeterminismFailure):
                self.record(command, conn=wrapped)
        self.assertEqual(original, self.record(command))
