"""Versioned analytics only. All settlement policies/assertions are synthetic."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import os
import threading
import unittest
from unittest.mock import Mock, patch
from uuid import NAMESPACE_DNS, uuid4, uuid5

import test_corner_ev as math_fixtures
import test_corner_ev_selection as database_fixtures
from test_corner_work import WorkDatabase
from corner import analytics_versions as api, ev_conditional as v2, evaluations as v1
from corner import channels, qualifications as q1, work
from corner.lifecycle import ActionabilityPolicy, ImplementationIdentity


def uid(label):
    return str(uuid5(NAMESPACE_DNS, label))


def legacy_command():
    snapshot, config = math_fixtures.inputs()
    contract = replace(snapshot.contract, market_id=uid('market'), competition_id=uid('competition'),
        outcomes=tuple(replace(o, outcome_id=uid(o.outcome_id), participant_id=uid(o.participant_id))
                       for o in snapshot.contract.outcomes))
    quotes = tuple(replace(q, observation_id=uid(q.observation_id), market_id=uid(q.market_id),
                           outcome_id=uid(q.outcome_id), sportsbook_id=uid(q.sportsbook_id)) for q in snapshot.quotes)
    return v1.EvaluationCommand(replace(snapshot, contract=contract, quotes=quotes,
        target_observation_id=uid(snapshot.target_observation_id)), replace(config,
        competition_id=uid(config.competition_id), reference_sportsbook_ids=tuple(uid(b) for b in config.reference_sportsbook_ids)))


def conditional(command=None):
    command = command or legacy_command()
    policy = v2.SettlementPolicy('synthetic-conditioning', 'test-1', 'synthetic-policy-revision',
        '{"period":"full_game","overtime":"included","result":"official_winner"}',
        '{"rule":"synthetic-identical-void-conditions","net_return":"0"}')
    snapshot = replace(command.snapshot, contract=replace(command.snapshot.contract, settlement_policy='decisive_two_way'))
    evidence = tuple(v2.SettlementEvidence(book, snapshot.contract.market_id,
        tuple(o.outcome_id for o in snapshot.contract.outcomes), uid(book + '-assertion'), 'a' * 64,
        policy.revision, policy.conditioning_contract_json, policy.invalidation_behavior_json)
        for book in sorted({q.sportsbook_id for q in snapshot.quotes}))
    return v2.EvaluationCommand(snapshot, v2.Configuration('conditional-test-1', command.configuration, policy), evidence)


def row_for(command):
    result = api.evaluate_command(command)
    document, output = api.serialize_command(command), api.serialize_result(result)
    return dict(id=str(uuid4()), result_kind=output['result_kind'], non_evaluation_reason=output['non_evaluation_reason'],
        reference_book_count=output['reference_book_count'], snapshot_format_version=document['snapshot_format_version'],
        command_snapshot=document, command_sha256=v1._digest(document), result_snapshot=output,
        result_sha256=v1._digest(output), fair_probability=api._rounded(result.fair_probability, '.0000000001'),
        ev_ratio=api._rounded(result.ev_ratio, '.00000001'))


def generation(command=None):
    command = command or conditional()
    return api.GenerationConfiguration(api.ENGINE, command.configuration, api.QUALIFIER,
        api.ConditionalEVPolicy('conditional-threshold-1', Decimal('.03')), command.configuration.settlement,
        ActionabilityPolicy(ImplementationIdentity('synthetic-lifecycle', '1', 'synthetic-build'),
                            timedelta(seconds=10), timedelta(seconds=20)))


class ConditionalEVTests(unittest.TestCase):
    def test_v1_decodes_without_acquiring_conditional_semantics(self):
        command = legacy_command()
        self.assertEqual(v1.serialize_command(command), api.serialize_command(command))
        self.assertEqual(api.serialize_command(command), api.serialize_command(api.deserialize_command(api.serialize_command(command))))
        self.assertEqual(api.LEGACY_BASIS, api.decode_evaluation(row_for(command)).calculation_basis)
        self.assertNotIn('calculation_basis', row_for(command)['result_snapshot'])

    def test_v2_roundtrip_and_explicit_result_basis(self):
        command = conditional()
        document = api.serialize_command(command)
        decoded = api.deserialize_command(document)
        self.assertEqual(document, api.serialize_command(decoded))
        self.assertEqual(api.serialize_result(api.evaluate_command(command)),
                         api.serialize_result(api.evaluate_command(decoded)))
        output = api.serialize_result(api.evaluate_command(command))
        self.assertEqual(v2.BASIS, output['calculation_basis'])
        self.assertEqual(v2.PROBABILITY_BASIS, output['fair_probability_basis'])
        self.assertEqual('none', output['invalidation_probability_model'])
        self.assertIsNone(output['unconditional_ev_ratio'])
        self.assertNotIn('ev_ratio', output)
        self.assertNotIn('fair_probability', output)
        self.assertEqual('decisive_two_way', document['snapshot']['contract']['settlement_policy'])
        self.assertNotIn('settlement_policy', document['configuration']['pricing'])

    def test_binary_math_is_unchanged_but_meaning_is_not_equivalent(self):
        legacy, current = row_for(legacy_command()), row_for(conditional())
        self.assertEqual(legacy['ev_ratio'], current['ev_ratio'])
        self.assertNotEqual(api.decode_evaluation(legacy), api.decode_evaluation(current))
        self.assertNotEqual(legacy['command_sha256'], current['command_sha256'])

    def test_v1_policy_rejects_v2_and_v2_policy_rejects_v1(self):
        for row, policy in [(row_for(conditional()), q1.MinimumEVPolicy('legacy', Decimal('.03'))),
                            (row_for(legacy_command()), api.ConditionalEVPolicy('new', Decimal('.03')))]:
            with self.assertRaises(api.BasisMismatch):
                api.qualify_evaluation(row, policy)
        with self.assertRaises(q1.QualificationValidationError):
            q1.qualify_evaluation(row_for(conditional()), q1.MinimumEVPolicy('legacy', Decimal('.03')))

    def test_conditional_threshold_uses_full_precision_and_inclusive_boundary(self):
        policy = api.ConditionalEVPolicy('threshold', Decimal('.01'))
        for value, expected in [('0.009999999', 'not_qualified'), ('0.01000000', 'qualified'),
                                ('0.0100000000001', 'qualified'), ('0', 'not_qualified'), ('-0.01', 'not_qualified')]:
            row = row_for(conditional())
            row['result_snapshot']['conditional_ev_ratio'] = value
            row['result_sha256'] = v1._digest(row['result_snapshot'])
            row['ev_ratio'] = api._rounded(Decimal(value), '.00000001')
            self.assertEqual(expected, api.qualify_evaluation(row, policy).decision_kind)

    def test_non_evaluation_retains_basis_but_no_estimates(self):
        command = conditional()
        command = replace(command, snapshot=replace(command.snapshot,
            evaluated_at=command.snapshot.evaluated_at + timedelta(days=1)))
        row = row_for(command)
        self.assertEqual('not_evaluable', row['result_kind'])
        self.assertIsNone(row['result_snapshot']['conditional_ev_ratio'])
        self.assertIsNone(row['result_snapshot']['conditional_fair_probability'])
        self.assertEqual('not_qualifiable', api.qualify_evaluation(row,
            api.ConditionalEVPolicy('new', Decimal('.01'))).decision_kind)
        with self.assertRaises(api.BasisMismatch):
            api.qualify_evaluation(row, q1.MinimumEVPolicy('old', Decimal('.01')))

    def test_different_conditioning_or_invalidation_cannot_contribute(self):
        command = conditional()
        for changes in ({'conditioning_contract_json': '{"overtime":"excluded"}'},
                        {'invalidation_behavior_json': '{"rule":"different_void_population"}'},
                        {'policy_revision': 'another-policy'}, {'push_behavior': 'possible'},
                        {'decisive_structure': 'three_way'}):
            for index in range(len(command.settlements)):
                evidence = list(command.settlements)
                evidence[index] = replace(evidence[index], **changes)
                result = api.evaluate_command(replace(command, settlements=tuple(evidence)))
                self.assertEqual(v2.Reason.INCOMPATIBLE, result.reason)
                self.assertIsNone(result.fair_probability)
                self.assertIsNone(result.ev_ratio)
                self.assertEqual((), result.reference_estimates)

    def test_missing_assertion_fails_closed_and_wrong_binding_is_error(self):
        command = conditional()
        self.assertEqual(v2.Reason.MISSING, api.evaluate_command(replace(command,
            settlements=command.settlements[:-1])).reason)
        wrong = replace(command.settlements[0], market_id=uid('wrong-market'))
        with self.assertRaisesRegex(ValueError, 'subject mismatch'):
            api.evaluate_command(replace(command, settlements=(wrong,) + command.settlements[1:]))

    def test_no_automatic_reinterpretation_of_legacy_settlement_label(self):
        command = conditional()
        command = replace(command, snapshot=replace(command.snapshot,
            contract=replace(command.snapshot.contract, settlement_policy='two_way_no_push')))
        self.assertEqual(v1.ev.Reason.UNSUPPORTED_SETTLEMENT, api.evaluate_command(command).reason)

    def test_unknown_formats_builds_and_models_are_errors(self):
        for field, value in [('snapshot_format_version', 'unknown'), ('engine_revision', 'changed'),
                            ('engine_version', '1.0.0'), ('engine_build', {})]:
            doc = api.serialize_command(conditional())
            doc[field] = value
            with self.assertRaises(ValueError):
                api.deserialize_command(doc)
        for field, value in [('calculation_basis', 'unconditional'), ('invalidation_probability_model', 'guessed')]:
            with self.assertRaises(ValueError):
                replace(conditional().configuration, **{field: value})

    def test_result_corruption_and_projection_mismatch_are_not_qualification_outcomes(self):
        row = row_for(conditional())
        bad = deepcopy(row)
        bad['result_snapshot']['conditional_ev_ratio'] = '8'
        with self.assertRaisesRegex(ValueError, 'digest'):
            api.decode_evaluation(bad)
        for field, value in [('calculation_basis', 'unconditional'), ('conditional_ev_ratio', 'NaN'),
                            ('unconditional_ev_ratio', '0.1'), ('conditional_fair_probability', '1.1')]:
            bad = deepcopy(row)
            bad['result_snapshot'][field] = value
            bad['result_sha256'] = v1._digest(bad['result_snapshot'])
            with self.assertRaises(ValueError):
                api.decode_evaluation(bad)
        bad = deepcopy(row)
        bad['ev_ratio'] += Decimal('.01')
        with self.assertRaises(ValueError):
            api.decode_evaluation(bad)

    def test_canonical_unordered_evidence_and_policy_json(self):
        command = conditional()
        reordered = replace(command, settlements=tuple(reversed(command.settlements)),
            snapshot=replace(command.snapshot, quotes=tuple(reversed(command.snapshot.quotes))))
        self.assertEqual(api.serialize_command(command), api.serialize_command(reordered))
        with self.assertRaises(ValueError):
            replace(command.configuration.settlement, conditioning_contract_json='{"a":1,"a":2}')

    def test_generation_checks_entire_compatibility_tuple(self):
        config = generation()
        self.assertEqual(v2.BASIS, api.generation_snapshot(config)['qualification']['configuration']['expected_calculation_basis'])
        for changes in ({'qualification_policy': q1.MinimumEVPolicy('old', Decimal('.01'))},
                        {'qualification_implementation': ImplementationIdentity('minimum_ev', '1', q1.POLICY_REVISION)},
                        {'engine': ImplementationIdentity(v1.ev.ENGINE_NAME, '1.0.0', v1.ENGINE_REVISION)},
                        {'settlement_policy': replace(config.settlement_policy, revision='other-revision')}):
            with self.assertRaises(ValueError):
                replace(config, **changes)
        # The version-dispatch registration boundary also rejects a disguised v2
        # implementation paired with an otherwise well-formed v1 configuration.
        old = channels.GenerationConfiguration(api.ENGINE, legacy_command().configuration,
            ImplementationIdentity('minimum_ev', '1', q1.POLICY_REVISION),
            q1.MinimumEVPolicy('old', Decimal('.01')), config.actionability_policy)
        with self.assertRaises(ValueError):
            api.register_generation(Mock(), authority=channels.ChannelAuthority('service', 'test'),
                registration_key='bad', command=channels.GenerationRegistration(str(uuid4()), old))

    def test_missing_full_precision_fields_raise_validation_error(self):
        for field in ('conditional_ev_ratio', 'conditional_fair_probability'):
            row = row_for(conditional())
            del row['result_snapshot'][field]
            row['result_sha256'] = v1._digest(row['result_snapshot'])
            with self.assertRaises(q1.QualificationValidationError):
                api.decode_evaluation(row)

    def test_v1_frozen_dispatch_still_calls_exact_v1_adapter(self):
        authority = channels.ChannelAuthority('service', 'legacy-test')
        command = legacy_command()
        frozen = work._serialize('evaluate', command, authority, 'legacy-command')
        self.assertEqual(v1.ENGINE_REVISION, frozen['implementation'])
        self.assertEqual('1.0.0', frozen['payload']['engine_version'])
        with patch.object(v1, 'record_evaluation', return_value={'id': 'original'}) as old:
            self.assertEqual({'id': 'original'}, work._dispatch(Mock(), frozen))
        replayed = old.call_args.kwargs['command']
        self.assertEqual(v1.serialize_command(command), v1.serialize_command(replayed))


@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE') == '1', 'opt-in PostgreSQL regression tests')
class ConditionalLedgerTests(unittest.TestCase):
    setUp = database_fixtures.EVSelectionTests.setUp
    select = database_fixtures.EVSelectionTests.select

    def command(self):
        selected = self.select()
        return conditional(v1.EvaluationCommand(selected.snapshot, selected.configuration))

    def record(self, command=None, key='conditional-evaluation'):
        return api.record_evaluation(self.conn, authority=channels.ChannelAuthority('service', 'conditional-test'),
                                     evaluation_key=key, command=command or self.command())

    def test_v2_evaluation_persists_exact_inputs_basis_and_idempotent_result(self):
        command = self.command()
        row = self.record(command)
        self.assertEqual(row, self.record(command))
        self.assertEqual('2.0.0', row['engine_version'])
        self.assertEqual(v2.BASIS, api.decode_evaluation(row).calculation_basis)
        self.assertEqual(row['command_snapshot'], api.serialize_command(api.deserialize_command(row['command_snapshot'])))
        with self.conn.cursor() as cur:
            cur.execute('SELECT observation_id FROM corner.engine_evaluation_inputs WHERE evaluation_id=%s', (row['id'],))
            self.assertEqual({q.observation_id for q in command.snapshot.quotes}, {r[0] for r in cur.fetchall()})
        with self.assertRaises(v1.EvaluationConflict):
            self.record(replace(command, context_json='{"changed":true}'))

    def test_v2_qualification_basis_and_retry_are_persisted(self):
        evaluation = self.record()
        command = api.QualificationCommand(evaluation['id'], api.ConditionalEVPolicy('threshold', Decimal('.01')),
                                           self.time + timedelta(seconds=5))
        args = dict(authority=channels.ChannelAuthority('service', 'conditional-test'),
                    qualification_key='qualification', command=command)
        row = api.record_qualification(self.conn, **args)
        self.assertEqual(row, api.record_qualification(self.conn, **args))
        self.assertEqual('qualified', row['decision_kind'])
        self.assertEqual(v2.BASIS, row['command_snapshot']['policy']['expected_calculation_basis'])
        self.assertEqual(v2.BASIS, row['result_snapshot']['calculation_basis'])
        with self.assertRaises(ValueError):
            q1.record_qualification(self.conn, authority=args['authority'], qualification_key='wrong-basis',
                command=q1.QualificationCommand(evaluation['id'], q1.MinimumEVPolicy('old', Decimal('.01')), command.decided_at))

    def test_v1_evaluation_cannot_be_qualified_by_conditional_policy(self):
        selected = self.select()
        row = api.record_evaluation(self.conn, authority=channels.ChannelAuthority('service', 'legacy-test'),
            evaluation_key='old', command=v1.EvaluationCommand(selected.snapshot, selected.configuration))
        self.assertEqual(api.LEGACY_BASIS, api.decode_evaluation(row).calculation_basis)
        with self.assertRaises(api.BasisMismatch):
            api.record_qualification(self.conn, authority=channels.ChannelAuthority('service', 'conditional-test'),
                qualification_key='wrong-basis', command=api.QualificationCommand(row['id'],
                    api.ConditionalEVPolicy('new', Decimal('.01')), self.time))

    def test_conditioning_failure_is_persisted_as_non_evaluable(self):
        command = self.command()
        bad = replace(command.settlements[0], invalidation_behavior_json='{"void":"different_population"}')
        row = self.record(replace(command, settlements=(bad,) + command.settlements[1:]))
        self.assertEqual(v2.Reason.INCOMPATIBLE.value, row['non_evaluation_reason'])
        self.assertIsNone(api.decode_evaluation(row).ev_ratio)
        self.assertIsNone(row['ev_ratio'])

    def test_generation_registers_new_explicit_tuple_without_schema_changes(self):
        channel = channels.create_channel(self.conn, code='conditional-' + uuid4().hex, display_name='Synthetic v2 only')
        config = generation(self.command())
        command = channels.GenerationRegistration(channel['id'], config)
        args = dict(authority=channels.ChannelAuthority('service', 'conditional-test'), registration_key='new-generation', command=command)
        row = api.register_generation(self.conn, **args)
        self.assertEqual(row, api.register_generation(self.conn, **args))
        self.assertEqual(api.CHANNEL_FORMAT, row['snapshot_format_version'])
        self.assertEqual(config.settlement_policy.revision, row['configuration_snapshot']['settlement']['revision'])
        # No activation, fan-out, or lifecycle processing is implied by registration.
        with self.conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM corner.channel_generation_activations WHERE new_generation_id=%s', (row['id'],))
            self.assertEqual(0, cur.fetchone()[0])

    def test_failed_evidence_write_leaves_no_partial_header(self):
        command = self.command()
        quotes = tuple(replace(q, decimal_odds=Decimal('9')) if q.observation_id == command.snapshot.target_observation_id else q
                       for q in command.snapshot.quotes)
        with self.assertRaises(ValueError):
            self.record(replace(command, snapshot=replace(command.snapshot, quotes=quotes)))
        with self.conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM corner.engine_evaluations WHERE authority_id='conditional-test' AND evaluation_key='conditional-evaluation'")
            self.assertEqual(0, cur.fetchone()[0])
        self.assertEqual('evaluated', self.record(command)['result_kind'])

    def test_failure_after_header_insert_rolls_back_header_and_leaves_key_reusable(self):
        insert = api._insert
        def crash(*args, **kwargs):
            insert(*args, **kwargs)
            raise RuntimeError('synthetic failure after header insert')
        with patch.object(api, '_insert', side_effect=crash), self.assertRaises(RuntimeError):
            self.record()
        with self.conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM corner.engine_evaluations WHERE authority_id='conditional-test' AND evaluation_key='conditional-evaluation'")
            self.assertEqual(0, cur.fetchone()[0])
        self.assertEqual('evaluated', self.record()['result_kind'])

    def test_real_frozen_v1_work_command_executes_with_v2_installed(self):
        selected = self.select()
        authority = channels.ChannelAuthority('service', 'v1-replay-proof')
        old = v1.EvaluationCommand(selected.snapshot, selected.configuration)
        request = work.enqueue(self.conn, kind='evaluate', namespace='v1-replay-proof', key=str(uuid4()))
        lease = work.claim(self.conn, owner='test-worker', lease_for=timedelta(minutes=1), request_id=request['id'])
        frozen = work.prepare(self.conn, request_id=request['id'], owner='test-worker', token=lease['lease_token'],
                              command=old, authority=authority, domain_key='old-command')
        complete = work.complete(self.conn, request_id=request['id'], owner='test-worker', token=lease['lease_token'])
        self.assertEqual('completed', complete['status'])
        self.assertEqual(v1.ENGINE_REVISION, frozen['command_snapshot']['implementation'])
        with self.conn.cursor() as cur:
            cur.execute('SELECT engine_version, engine_revision, command_snapshot FROM corner.engine_evaluations WHERE id=%s',
                        (complete['engine_evaluation_id'],))
            version, revision, document = cur.fetchone()
        self.assertEqual(('1.0.0', v1.ENGINE_REVISION), (version, revision))
        self.assertEqual(frozen['command_snapshot']['payload'], document)


@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE') == '1' and os.getenv('CORNER_TEST_CONCURRENCY') == '1',
                     'opt-in disposable concurrent versioned analytics tests')
class ConditionalConcurrencyTests(WorkDatabase, unittest.TestCase):
    select = database_fixtures.EVSelectionTests.select

    def setUp(self):
        with patch('db.insert.connect', self.connect):
            database_fixtures.EVSelectionTests.setUp(self)
        selected = self.select()
        self.input = conditional(v1.EvaluationCommand(selected.snapshot, selected.configuration))
        self.authority = channels.ChannelAuthority('service', 'concurrent-' + uuid4().hex)
        self.conn.commit()

    def race(self, operation, role='analysis'):
        from psycopg2 import sql
        def execute(index):
            conn = self.connect()
            try:
                with conn.cursor() as cur:
                    cur.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(self.roles[role])))
                result = operation(conn, index)
                conn.commit()
                return result
            except Exception as exc:
                conn.rollback()
                return exc
            finally:
                conn.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(execute, (0, 1)))

    def test_concurrent_evaluation_retry_under_nonowner_role(self):
        barrier = threading.Barrier(2)
        evaluate = api.evaluate_command
        def synchronized(command):
            barrier.wait(timeout=10)
            return evaluate(command)
        with patch.object(api, 'evaluate_command', side_effect=synchronized):
            rows = self.race(lambda conn, _: api.record_evaluation(conn, authority=self.authority,
                evaluation_key='same', command=self.input))
        self.assertTrue(all(isinstance(r, dict) for r in rows), rows)
        self.assertEqual(rows[0], rows[1])

    def test_concurrent_disagreement_preserves_winner_and_surfaces_failure(self):
        barrier, local = threading.Barrier(2), threading.local()
        evaluate = api.evaluate_command
        def inconsistent(command):
            result = evaluate(command)
            barrier.wait(timeout=10)
            return replace(result, ev_ratio=result.ev_ratio + Decimal('.001') * local.variant)
        def operation(conn, index):
            local.variant = index
            return api.record_evaluation(conn, authority=self.authority, evaluation_key='same', command=self.input)
        with patch.object(api, 'evaluate_command', side_effect=inconsistent):
            results = self.race(operation)
        self.assertEqual(1, sum(isinstance(r, dict) for r in results), results)
        self.assertEqual(1, sum(isinstance(r, v1.DeterminismFailure) for r in results), results)
        with self.conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM corner.engine_evaluations WHERE authority_id=%s', (self.authority.identifier,))
            self.assertEqual(1, cur.fetchone()[0])

    def test_concurrent_conditional_qualification_returns_original_record(self):
        evaluation = api.record_evaluation(self.conn, authority=self.authority, evaluation_key='evaluation', command=self.input)
        self.conn.commit()
        command = api.QualificationCommand(evaluation['id'], api.ConditionalEVPolicy('new', Decimal('.01')), self.time)
        qualify = api.qualify_evaluation
        barrier = threading.Barrier(2)
        def synchronized(*args):
            barrier.wait(timeout=10)
            return qualify(*args)
        with patch.object(api, 'qualify_evaluation', side_effect=synchronized):
            rows = self.race(lambda conn, _: api.record_qualification(conn, authority=self.authority,
                qualification_key='same', command=command))
        self.assertTrue(all(isinstance(r, dict) for r in rows), rows)
        self.assertEqual(rows[0], rows[1])

    def test_concurrent_generation_registration_does_not_activate(self):
        channel = channels.create_channel(self.conn, code='v2-race-' + uuid4().hex, display_name='Synthetic v2')
        self.conn.commit()
        command = channels.GenerationRegistration(channel['id'], generation(self.input))
        barrier = threading.Barrier(2)
        insert = api._insert
        def synchronized(*args, **kwargs):
            barrier.wait(timeout=10)
            return insert(*args, **kwargs)
        with patch.object(api, '_insert', side_effect=synchronized):
            rows = self.race(lambda conn, _: api.register_generation(conn, authority=self.authority,
                registration_key='same', command=command), role='channel_admin')
        self.assertTrue(all(isinstance(r, dict) for r in rows), rows)
        self.assertEqual(rows[0], rows[1])


if __name__ == '__main__':
    unittest.main()
