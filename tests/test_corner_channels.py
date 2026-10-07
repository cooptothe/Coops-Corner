"""Pure serialization and rollback-only channel/activation/occurrence tests."""

import os
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import test_corner_ev_selection as fixtures
from corner import channels
from corner.ev import EVConfiguration, ProviderTimePolicy
from corner.evaluations import EvaluationAuthority, EvaluationCommand, record_evaluation, _digest
from corner.lifecycle import ActionabilityPolicy, ImplementationIdentity
from corner.qualifications import (
    MinimumEVPolicy, QualificationAuthority, QualificationCommand, record_qualification,
)


def configuration(ev_config=None):
    if ev_config is None:
        ev_config = EVConfiguration('fixture-v1', str(uuid4()), 'moneyline', 'full_game',
            (str(uuid4()), str(uuid4())), timedelta(seconds=30), timedelta(seconds=30),
            timedelta(seconds=10), ProviderTimePolicy.IGNORE, None, 40)
    return channels.GenerationConfiguration(ImplementationIdentity('ev', '1', 'synthetic-engine-build'),
        ev_config, ImplementationIdentity('minimum_ev', '1', 'synthetic-qualification-build'),
        MinimumEVPolicy('policy-v1', Decimal('.01')),
        ActionabilityPolicy(ImplementationIdentity('lifecycle', '1', 'synthetic-lifecycle-build'),
                            timedelta(minutes=1), timedelta(minutes=2)))


class ChannelSerializationTests(unittest.TestCase):
    def test_registration_canonicalizes_full_configuration_and_context(self):
        config = configuration()
        command = channels.GenerationRegistration(str(uuid4()), config, '{"b":2,"a":1}')
        equivalent = replace(command, channel_id=command.channel_id.upper(), context_json=' { "a": 1, "b": 2 } ',
            configuration=replace(config, qualification_policy=MinimumEVPolicy('policy-v1', Decimal('.0100')),
                engine_configuration=replace(config.engine_configuration,
                    reference_sportsbook_ids=tuple(reversed(config.engine_configuration.reference_sportsbook_ids)))))
        self.assertEqual(channels.registration_snapshot(command), channels.registration_snapshot(equivalent))
        doc = channels.registration_snapshot(command)
        self.assertEqual(_digest(doc['configuration']).hex(), doc['configuration_sha256'])
        self.assertEqual('0.01', doc['configuration']['qualification']['configuration']['minimum_ev_ratio'])
        self.assertEqual(60000000, doc['configuration']['lifecycle']['configuration']['target_max_age_microseconds'])

    def test_bad_context_and_activation_time_rejected(self):
        command = channels.GenerationRegistration(str(uuid4()), configuration())
        for text in ('[]', '{"number":0.1}', '{"number":NaN}', 'invalid'):
            with self.subTest(text=text), self.assertRaises(channels.ChannelValidationError):
                channels.registration_snapshot(replace(command, context_json=text))
        activation = channels.ActivationCommand(command.channel_id, str(uuid4()), None, datetime(2026, 9, 22))
        with self.assertRaises(channels.ChannelValidationError):
            channels.activation_snapshot(activation)

    def test_activation_timestamp_and_ids_have_canonical_semantics(self):
        instant = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
        command = channels.ActivationCommand(str(uuid4()), str(uuid4()), None, instant)
        document = channels.activation_snapshot(command)
        self.assertEqual(document, channels.activation_snapshot(replace(command,
            activated_at=instant.astimezone(timezone(timedelta(hours=-5))))))
        self.assertEqual('2026-09-22T12:00:00.000000Z', document['activated_at'])


@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE') == '1', 'opt-in PostgreSQL tests')
class ChannelLedgerTests(unittest.TestCase):
    select = fixtures.EVSelectionTests.select

    def setUp(self):
        fixtures.EVSelectionTests.setUp(self)
        self.authority = channels.ChannelAuthority('service', 'channel-test')
        self.channel = channels.create_channel(self.conn, code='channel-' + uuid4().hex, display_name='Synthetic +EV')
        self.command = channels.GenerationRegistration(self.channel['id'], configuration(self.config), '{"ticket":"CH-1"}')

    def register(self, key='generation-1', command=None, authority=None, conn=None):
        return channels.register_generation(conn or self.conn, authority=authority or self.authority,
            registration_key=key, command=command or self.command)

    def activation(self, generation, previous=None, seconds=0, channel_id=None):
        return channels.ActivationCommand(channel_id or self.channel['id'], generation['id'],
            previous['id'] if previous else None, self.time + timedelta(seconds=seconds))

    def activate(self, command, key='activation-1', authority=None, conn=None):
        return channels.activate_generation(conn or self.conn, authority=authority or self.authority,
                                            activation_key=key, command=command)

    def qualification(self, threshold='.01', stale=False):
        selected = self.select(evaluated_at=self.time + timedelta(hours=1)) if stale else self.select()
        evaluation = record_evaluation(self.conn, authority=EvaluationAuthority('service', 'channel-test'),
            evaluation_key=str(uuid4()), command=EvaluationCommand(selected.snapshot, selected.configuration))
        return record_qualification(self.conn, authority=QualificationAuthority('service', 'channel-test'),
            qualification_key=str(uuid4()), command=QualificationCommand(evaluation['id'],
                MinimumEVPolicy('v1', Decimal(threshold)), self.time + timedelta(hours=2)))

    def sql_error(self, sql, params, code, constraint=None):
        import psycopg2
        with self.conn.cursor() as cur:
            cur.execute('SAVEPOINT expected_constraint_failure')
            try:
                with self.assertRaises(psycopg2.Error) as error:
                    cur.execute(sql, params)
                self.assertEqual(code, error.exception.pgcode)
                if constraint:
                    self.assertEqual(constraint, error.exception.diag.constraint_name)
            finally:
                cur.execute('ROLLBACK TO SAVEPOINT expected_constraint_failure')
                cur.execute('RELEASE SAVEPOINT expected_constraint_failure')

    def clone_activation_error(self, original, changes, code, constraint):
        from psycopg2.extras import Json
        self.sql_error('''INSERT INTO corner.channel_generation_activations
            SELECT (jsonb_populate_record(NULL::corner.channel_generation_activations,
                to_jsonb(a) || jsonb_build_object('id',uuidv7(),'activation_key',%s) || %s::jsonb)).*
            FROM corner.channel_generation_activations a WHERE id=%s''',
            (str(uuid4()), Json(changes), original['id']), code, constraint)

    def test_channel_identity_has_no_current_generation_pointer(self):
        self.assertEqual(self.channel, channels.create_channel(self.conn, code=self.channel['code'], display_name='Synthetic +EV'))
        with self.assertRaises(channels.ChannelConflict):
            channels.create_channel(self.conn, code=self.channel['code'], display_name='Changed')
        with self.conn.cursor() as cur:
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='corner' AND table_name='qualification_channels'")
            self.assertNotIn('current_generation_id', {row[0] for row in cur.fetchall()})

    def test_registration_retry_identity_and_snapshot_projection(self):
        first = self.register()
        equivalent = replace(self.command, context_json=' { "ticket": "CH-1" } ')
        self.assertEqual(first, self.register(command=equivalent))
        second = self.register('new-intent')
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(bytes(first['configuration_sha256']), bytes(second['configuration_sha256']))
        self.assertEqual(bytes(first['configuration_sha256']), _digest(first['configuration_snapshot']))
        self.assertEqual(first['snapshot_format_version'], first['configuration_snapshot']['snapshot_format_version'])
        self.assertEqual(first['engine_revision'], first['configuration_snapshot']['engine']['implementation']['revision'])
        self.assertEqual(first['lifecycle_revision'], first['configuration_snapshot']['lifecycle']['implementation']['revision'])
        other = self.register(authority=channels.ChannelAuthority('human', 'different-actor'))
        self.assertNotEqual(first['id'], other['id'])

    def test_registration_changed_channel_config_context_or_revision_conflicts(self):
        self.register()
        another = channels.create_channel(self.conn, code='other-' + uuid4().hex, display_name='Other')
        for changed in (
            replace(self.command, channel_id=another['id']),
            replace(self.command, context_json='{"ticket":"CH-2"}'),
            replace(self.command, configuration=replace(self.command.configuration,
                qualification_policy=MinimumEVPolicy('policy-v1', Decimal('.03')))),
            replace(self.command, configuration=replace(self.command.configuration,
                engine=replace(self.command.configuration.engine, revision='different-build'))),
        ):
            with self.assertRaises(channels.ChannelConflict):
                self.register(command=changed)

    def test_activation_sequence_equal_times_and_retry_after_later_activation(self):
        g1, g2 = self.register(), self.register('g2')
        command = self.activation(g1)
        first = self.activate(command)
        second = self.activate(self.activation(g2, g1), 'a2')
        self.assertEqual((1, 2), (first['activation_sequence'], second['activation_sequence']))
        self.assertEqual(first['activated_at'], second['activated_at'])
        self.assertEqual(first, self.activate(command))
        with self.assertRaises(channels.ActivationConflict):
            self.activate(self.activation(g1, g2, seconds=1), 'reactivate')

    def test_stale_predecessor_and_backdated_activation_fail(self):
        g1, g2 = self.register(), self.register('g2')
        self.activate(self.activation(g1, seconds=10))
        with self.assertRaises(channels.ActivationConflict):
            self.activate(self.activation(g2, seconds=20), 'stale-predecessor')
        with self.assertRaises(channels.ActivationConflict):
            self.activate(self.activation(g2, g1, seconds=9), 'backdated')
        second = self.activate(self.activation(g2, g1, seconds=10), 'equal-time')
        self.assertEqual(2, second['activation_sequence'])

    def test_activation_key_conflicts_and_authority_scope(self):
        g1, g2 = self.register(), self.register('g2')
        command = self.activation(g1)
        self.activate(command)
        for changed in (replace(command, new_generation_id=g2['id']),
                        replace(command, expected_previous_generation_id=g1['id']),
                        replace(command, activated_at=self.time + timedelta(seconds=1)),
                        replace(command, context_json='{"changed":true}')):
            with self.assertRaises(channels.ChannelConflict):
                self.activate(changed)
        second = self.activate(self.activation(g2, g1), authority=channels.ChannelAuthority('human', 'other'))
        self.assertEqual(2, second['activation_sequence'])

    def test_cross_channel_generation_fks_are_structural(self):
        g1, g2 = self.register(), self.register('g2')
        activation = self.activate(self.activation(g1))
        other = channels.create_channel(self.conn, code='other-' + uuid4().hex, display_name='Other')
        foreign = self.register('foreign', replace(self.command, channel_id=other['id']))
        self.clone_activation_error(activation, {'new_generation_id': foreign['id'],
            'activation_sequence': 2, 'expected_previous_generation_id': g1['id']},
            '23503', 'channel_activations_new_generation_fk')
        self.clone_activation_error(activation, {'new_generation_id': g2['id'],
            'activation_sequence': 2, 'expected_previous_generation_id': foreign['id']},
            '23503', 'channel_activations_previous_generation_fk')

    def test_activation_unique_constraints_protect_genesis_successors_and_sequence(self):
        g1, g2, g3, g4 = [self.register('g' + str(i)) for i in range(4)]
        first = self.activate(self.activation(g1))
        self.clone_activation_error(first, {'new_generation_id': g2['id']}, '23505', 'channel_activations_successor_key')
        second = self.activate(self.activation(g2, g1), 'second')
        self.clone_activation_error(second, {'new_generation_id': g3['id'], 'activation_sequence': 3},
            '23505', 'channel_activations_successor_key')
        self.clone_activation_error(second, {'new_generation_id': g1['id'], 'expected_previous_generation_id': g2['id'],
            'activation_sequence': 3}, '23505', 'channel_activations_generation_key')
        self.clone_activation_error(second, {'new_generation_id': g3['id'], 'expected_previous_generation_id': g4['id']},
            '23505', 'channel_activations_sequence_key')

    def test_occurrence_is_qualified_only_and_idempotent(self):
        qualified = self.qualification()
        first = channels.create_occurrence(self.conn, qualification_decision_id=qualified['id'])
        self.assertEqual(first, channels.create_occurrence(self.conn, qualification_decision_id=qualified['id']))
        self.assertEqual('qualified', first['qualification_decision_kind'])
        for decision in (self.qualification('.9'), self.qualification(stale=True)):
            with self.assertRaises(channels.ChannelValidationError):
                channels.create_occurrence(self.conn, qualification_decision_id=decision['id'])
            self.sql_error('INSERT INTO corner.opportunity_occurrences (qualification_decision_id) VALUES (%s)',
                (decision['id'],), '23503', 'opportunity_occurrences_qualified_decision_fk')
        self.sql_error('''INSERT INTO corner.opportunity_occurrences
            (qualification_decision_id, qualification_decision_kind) VALUES (%s,'not_qualified')''',
            (self.qualification('.9')['id'],), '23514')

    def test_ledger_update_delete_and_truncate_protection(self):
        generation = self.register()
        activation = self.activate(self.activation(generation))
        occurrence = channels.create_occurrence(self.conn, qualification_decision_id=self.qualification()['id'])
        for table, row in (('qualification_channel_generations', generation),
                           ('channel_generation_activations', activation), ('opportunity_occurrences', occurrence)):
            self.sql_error(f'UPDATE corner.{table} SET created_at=created_at WHERE id=%s', (row['id'],), 'P0001')
            self.sql_error(f'DELETE FROM corner.{table} WHERE id=%s', (row['id'],), 'P0001')
            extra = ', corner.channel_generation_activations' if table == 'qualification_channel_generations' else ''
            # Later ledgers reference these tables; exercise their own immutable
            # triggers after the FK precheck. Triggers reject before deletion.
            self.sql_error(f'TRUNCATE corner.{table}{extra} CASCADE', (), 'P0001')

    def test_restrict_protects_channel_generation_and_qualified_evidence(self):
        generation = self.register()
        self.activate(self.activation(generation))
        qualified = self.qualification()
        channels.create_occurrence(self.conn, qualification_decision_id=qualified['id'])
        self.sql_error('DELETE FROM corner.qualification_channels WHERE id=%s', (self.channel['id'],), '23001')
        with self.conn.cursor() as cur:
            cur.execute('ALTER TABLE corner.qualification_channel_generations DISABLE TRIGGER channel_generations_immutable')
            cur.execute('ALTER TABLE corner.qualification_decisions DISABLE TRIGGER qualification_decisions_immutable')
        self.sql_error('DELETE FROM corner.qualification_channel_generations WHERE id=%s', (generation['id'],), '23001')
        self.sql_error('DELETE FROM corner.qualification_decisions WHERE id=%s', (qualified['id'],),
                       '23001', 'opportunity_occurrences_qualified_decision_fk')
        with self.conn.cursor() as cur:
            cur.execute('ALTER TABLE corner.qualification_channel_generations ENABLE TRIGGER channel_generations_immutable')
            cur.execute('ALTER TABLE corner.qualification_decisions ENABLE TRIGGER qualification_decisions_immutable')

    def test_failed_writes_leave_no_partial_rows_and_transaction_usable(self):
        from psycopg2.extras import RealDictCursor
        generation = self.register()
        qualified = self.qualification()
        cases = (
            ('qualification_channel_generations', lambda conn: self.register('failed-register', conn=conn),
             'registration_key', 'failed-register'),
            ('channel_generation_activations', lambda conn: self.activate(self.activation(generation), conn=conn),
             'channel_id', self.channel['id']),
            ('opportunity_occurrences', lambda conn: channels.create_occurrence(conn, qualification_decision_id=qualified['id']),
             'qualification_decision_id', qualified['id']),
        )
        for table, operation, field, identity in cases:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                tracked = MagicMock(wraps=cur)
                def execute(sql, params=None):
                    cur.execute(sql, params)
                    if sql.startswith('INSERT INTO corner.' + table):
                        raise RuntimeError('simulated post-insert failure')
                tracked.execute.side_effect = execute
                wrapped = MagicMock()
                wrapped.cursor.return_value.__enter__.return_value = tracked
                with self.assertRaisesRegex(RuntimeError, 'post-insert'):
                    operation(wrapped)
            with self.conn.cursor() as cur:
                cur.execute(f'SELECT count(*) FROM corner.{table} WHERE {field}=%s', (identity,))
                self.assertEqual((0,), cur.fetchone())
        self.assertEqual(1, self.activate(self.activation(generation))['activation_sequence'])
