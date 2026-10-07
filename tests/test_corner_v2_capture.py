"""Synthetic authorization only. No fixture is a production source approval."""
import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from corner import analytics_versions as analytics, capture_authority as auth
from corner import channels, evaluation_capture_v2 as capture, evaluations as codec
from corner import lifecycle_store, market_validation as validation, work, worker
import test_corner_conditional_ev as math
import test_corner_ev_selection as db_fixture
from test_corner_work import WorkDatabase


def fixtures(command=None, binding=None, *, at=None):
    command = command or math.conditional()
    at = at or command.snapshot.evaluated_at
    binding = binding or {'event_id': str(uuid4()), 'market_id': command.snapshot.contract.market_id,
        'competition_id': command.snapshot.contract.competition_id, 'market_type': 'moneyline', 'scope': 'full_game',
        'outcome_ids': sorted(o.outcome_id for o in command.snapshot.contract.outcomes),
        'provider_identities': [[str(uuid4()), 'synthetic-event']]}
    books = sorted({q.sportsbook_id for q in command.snapshot.quotes} | set(command.configuration.pricing.reference_sportsbook_ids))
    common = {'competition_id': binding['competition_id'], 'event_id': binding['event_id'],
              'jurisdiction': 'SYNTHETIC-ONLY', 'offering': 'test-only'}
    scopes = {'phase': common | {'kind': 'phase'}} | {b: common | {'kind': 'settlement', 'sportsbook_id': b,
        'market_id': binding['market_id'], 'market_type': 'moneyline', 'scope': 'full_game',
        'outcome_ids': binding['outcome_ids']} for b in books}
    records, artifacts = [], []
    phase_policy = validation.PhasePolicy(validation.PolicyIdentity('synthetic-phase', '1', 'test-policy'), (
        validation.PhaseSourceGrant('synthetic-phase', 'synthetic-phase', binding['provider_identities'][0][0],
            (('explicit_pregame', 'supported_pregame'), ('explicit_live', 'unsupported_live')),
            timedelta(minutes=5), timedelta(minutes=5)),))
    refs = {'phase': [], 'settlement': []}
    for stream, scope in scopes.items():
        kind = scope['kind']
        if kind == 'phase':
            content = {'format': validation.PHASE_FORMAT, 'provider_id': binding['provider_identities'][0][0],
                'external_event_id': binding['provider_identities'][0][1], 'status': 'explicit_pregame',
                'source_asserted_at': codec._encode(at - timedelta(seconds=1))}
            source = 'synthetic-phase'
        else:
            content = {'format': auth.RULES_FORMAT, 'binding': scope, 'rules_revision': 'test-rules-1',
                'effective_from': '2020-01-01T00:00:00.000000Z', 'effective_until': '2100-01-01T00:00:00.000000Z',
                'decisive_structure': 'two_way', 'push_behavior': 'absent',
                'conditioning_contract': json.loads(command.configuration.settlement.conditioning_contract_json),
                'invalidation_behavior': json.loads(command.configuration.settlement.invalidation_behavior_json)}
            source = 'synthetic-rules-' + stream
        raw = codec.canonical_json(content).encode()
        record = {'id': str(uuid4()), 'scope': scope, 'source_id': source, 'source_type': 'synthetic-' + kind,
            'source_revision': 'test-rules-1', 'received_at': codec._encode(at), 'adverse': False,
            'content_base64': base64.b64encode(raw).decode(), 'content_sha256': hashlib.sha256(raw).hexdigest(),
            'locator': 'synthetic://retained/' + source}
        records.append(record)
        artifact = {'id': str(uuid4()), 'revision': 'synthetic-approval-1', 'kind': kind, 'environment': 'synthetic',
            'authorized_scope': scope, 'authorized_assertion_classes': ['supported_pregame' if kind == 'phase' else 'decisive_two_way'],
            'effective_from': '2020-01-01T00:00:00.000000Z', 'effective_until': '2100-01-01T00:00:00.000000Z',
            'source_id': source, 'source_type': record['source_type'],
            'rules_sha256': None if kind == 'phase' else record['content_sha256']}
        artifacts.append(artifact)
        refs[kind].append({'id': artifact['id'], 'revision': artifact['revision'], 'sha256': auth.digest(artifact)})
    policy = {'environment': 'synthetic', 'loader': auth.LOADER, 'jurisdiction': 'SYNTHETIC-ONLY', 'offering': 'test-only',
        'phase_validation_policy': validation._encode(phase_policy), 'phase_validator_revision': validation.VALIDATOR_REVISION,
        'phase_approval_policy': {'name': 'synthetic-phase-approval', 'version': '1', 'revision': 'phase-approval-test-1'},
        'phase_approval_references': refs['phase'],
        'settlement_validation_policy': {'name': 'synthetic-conditional-validation', 'version': '1', 'revision': 'settlement-test-1'},
        'settlement_validator_revision': auth.REVISION,
        'settlement_approval_policy': {'name': 'synthetic-rules-approval', 'version': '1', 'revision': 'rules-approval-test-1'},
        'settlement_approval_references': refs['settlement']}
    catalog = {'environment': 'synthetic', 'loader': auth.LOADER, 'records': records, 'approvals': artifacts, 'withdrawals': []}
    return command, binding, policy, catalog


def source(catalog):
    return auth.SyntheticEvidenceStore(codec.canonical_json(catalog))


def authorize(data):
    command, binding, policy, catalog = data
    return auth.authorize(command.snapshot, command.configuration, auth.AuthorityPolicy(codec.canonical_json(policy)),
                          binding, source(catalog).capture(command.snapshot.evaluated_at))


def change_content(record, changes):
    doc = json.loads(base64.b64decode(record['content_base64'])) | changes
    raw = codec.canonical_json(doc).encode()
    record['content_base64'] = base64.b64encode(raw).decode()
    record['content_sha256'] = hashlib.sha256(raw).hexdigest()


def reapprove(policy, catalog, record):
    artifact = next(a for a in catalog['approvals'] if a['source_id'] == record['source_id'])
    artifact['rules_sha256'] = record['content_sha256']
    ref = next(r for r in policy['settlement_approval_references'] if r['id'] == artifact['id'])
    ref['sha256'] = auth.digest(artifact)


class AuthorizationTests(unittest.TestCase):
    def test_complete_proof_roundtrip_retains_approvals_inventories_and_raw_bytes(self):
        command = authorize(fixtures())
        frozen = analytics.deserialize_command(analytics.serialize_command(command))
        proof = auth.verify(frozen)
        self.assertEqual(auth.FORMAT, proof['format'])
        for stream in proof['streams'].values():
            self.assertTrue(stream['approval_resolutions'])
            self.assertEqual([], auth.unpack(stream['inventory'])['missing_expected_records'])
            for receipt in stream['approval_resolutions']:
                resolved = auth.unpack(receipt)
                self.assertEqual('authorized', resolved['resolution_result'])
                self.assertFalse(resolved['withdrawal_state_at_capture']['withdrawn'])
        self.assertEqual('evaluated', analytics.serialize_result(analytics.evaluate_command(command))['result_kind'])

    def test_no_production_path_even_with_self_declared_positive_artifacts(self):
        data = fixtures()
        data[2]['environment'] = 'production'
        with self.assertRaisesRegex(auth.UnmetPrerequisite, 'production_authority'):
            authorize(data)

    def test_legacy_generation_is_not_capture_compatible(self):
        with self.assertRaises(ValueError):
            capture._decode_configuration(analytics.generation_snapshot(math.generation()))

    def test_new_generation_requires_every_authority_field_and_roundtrips(self):
        data = fixtures()
        config = capture.GenerationConfiguration(math.generation(data[0]), auth.AuthorityPolicy(codec.canonical_json(data[2])))
        self.assertEqual(capture.generation_snapshot(config),
                         capture.generation_snapshot(capture._decode_configuration(capture.generation_snapshot(config))))
        for field in data[2]:
            broken = dict(data[2]); del broken[field]
            with self.assertRaises(auth.ValidationFailure):
                auth.AuthorityPolicy(codec.canonical_json(broken))

    def test_unknown_phase_and_conflicting_adverse_phase_prevent_preparation(self):
        for status, duplicate in [('unknown', False), ('explicit_live', True)]:
            data = fixtures()
            record = deepcopy(data[3]['records'][0])
            change_content(record, {'status': status})
            if duplicate:
                record['id'] = str(uuid4()); record['adverse'] = True
                data[3]['records'].append(record)
            else:
                data[3]['records'][0] = record
            with self.assertRaisesRegex(auth.UnmetPrerequisite, 'unknown_phase'):
                authorize(data)

    def test_correct_hash_without_approved_provenance_cannot_authorize(self):
        data = fixtures()
        data[2]['settlement_approval_references'] = []
        with self.assertRaises(auth.UnmetPrerequisite):
            authorize(data)

    def test_missing_expected_record_is_not_a_complete_inventory(self):
        data = fixtures()
        data[3]['records'].pop()
        with self.assertRaises(auth.UnmetPrerequisite):
            authorize(data)

    def test_self_consistent_but_trimmed_manifest_does_not_verify(self):
        command = authorize(fixtures())
        proof = auth.verify(command)
        inventory = auth.unpack(proof['streams']['phase']['inventory'])
        inventory['records_retained'] = []
        proof['streams']['phase']['inventory'] = auth.envelope(inventory)
        changed = replace(command, context_json=codec.canonical_json({'capture_authorization': auth.envelope(proof)}))
        with self.assertRaisesRegex(auth.ValidationFailure, 'inventory|contradictory'):
            auth.verify(changed)

    def test_phase_expiry_and_rules_applicability_have_independent_clocks(self):
        data = fixtures()
        change_content(data[3]['records'][0], {'source_asserted_at': codec._encode(data[0].snapshot.evaluated_at - timedelta(hours=1))})
        with self.assertRaises(auth.UnmetPrerequisite):
            authorize(data)
        data = fixtures()
        record = data[3]['records'][1]
        change_content(record, {'effective_until': codec._encode(data[0].snapshot.evaluated_at)})
        reapprove(data[2], data[3], record)
        with self.assertRaises(auth.UnmetPrerequisite):
            authorize(data)

    def test_approval_scope_expiry_class_and_withdrawal_fail_closed(self):
        for field, value in [('effective_until', '2021-01-01T00:00:00.000000Z'),
                             ('authorized_assertion_classes', []), ('authorized_scope', {'competition_id': str(uuid4()),
                              'jurisdiction': 'SYNTHETIC-ONLY', 'offering': 'test-only'})]:
            data = fixtures()
            data[3]['approvals'][0][field] = value
            data[2]['phase_approval_references'][0]['sha256'] = auth.digest(data[3]['approvals'][0])
            with self.assertRaises(auth.UnmetPrerequisite):
                authorize(data)
        data = fixtures()
        data[3]['withdrawals'].append({'id': str(uuid4()), 'approval_id': data[3]['approvals'][0]['id'],
            'effective_at': codec._encode(data[0].snapshot.evaluated_at),
            'recorded_at': codec._encode(data[0].snapshot.evaluated_at), 'reason': 'synthetic withdrawal'})
        with self.assertRaisesRegex(auth.UnmetPrerequisite, 'withdrawn'):
            authorize(data)

    def test_new_conflicting_rules_are_not_hidden_by_latest_positive_record(self):
        data = fixtures()
        bad = deepcopy(data[3]['records'][1]); bad['id'] = str(uuid4()); bad['adverse'] = True
        change_content(bad, {'conditioning_contract': {'overtime': 'excluded'}})
        data[3]['records'].append(bad)
        with self.assertRaises(auth.UnmetPrerequisite):
            authorize(data)

    def test_approved_but_different_conditioning_is_incompatible_not_unknown(self):
        data = fixtures()
        record = data[3]['records'][1]
        change_content(record, {'invalidation_behavior': {'different': 'population'}})
        reapprove(data[2], data[3], record)
        with self.assertRaises(auth.IncompatibleConditions):
            authorize(data)

    def test_wrong_binding_bad_digest_and_unknown_serialization_are_validation_failures(self):
        for mode in ('digest', 'event', 'format', 'revision'):
            data = fixtures()
            record = data[3]['records'][0]
            if mode == 'digest': record['content_sha256'] = '0' * 64
            elif mode == 'event': change_content(record, {'external_event_id': 'another-event'})
            elif mode == 'format': change_content(record, {'format': 'unknown'})
            else: data[2]['settlement_validator_revision'] = 'unknown'
            with self.assertRaises(ValueError):
                authorize(data)

    def test_exact_assertion_or_resolution_tampering_fails_offline_reproduction(self):
        for field in ('assertion', 'approval_resolutions'):
            command = authorize(fixtures())
            proof = auth.verify(command)
            if field == 'assertion':
                proof['streams']['phase']['assertion']['sha256'] = '0' * 64
            else:
                proof['streams']['phase']['approval_resolutions'] = []
            changed = replace(command, context_json=codec.canonical_json({'capture_authorization': auth.envelope(proof)}))
            with self.assertRaises(auth.ValidationFailure):
                auth.verify(changed)

    def test_contributing_book_cannot_be_silently_dropped_for_missing_authority(self):
        original = math.conditional()
        book = str(uuid4())
        old_book = original.configuration.pricing.reference_sportsbook_ids[0]
        extra = tuple(replace(q, sportsbook_id=book, observation_id=str(uuid4())) for q in original.snapshot.quotes
                      if q.sportsbook_id == old_book)
        original = replace(original, snapshot=replace(original.snapshot, quotes=original.snapshot.quotes + extra),
            configuration=replace(original.configuration, pricing=replace(original.configuration.pricing,
                reference_sportsbook_ids=original.configuration.pricing.reference_sportsbook_ids + (book,))))
        data = fixtures(original)
        artifact = next(a for a in data[3]['approvals'] if a['authorized_scope'].get('sportsbook_id') == book)
        data[2]['settlement_approval_references'] = [r for r in data[2]['settlement_approval_references'] if r['id'] != artifact['id']]
        with self.assertRaises(auth.UnmetPrerequisite):
            authorize(data)
        # Engine-defined nonparticipation is different: evidence still retained.
        command = data[0]
        snapshot = replace(command.snapshot, quotes=tuple(q for q in command.snapshot.quotes if q.sportsbook_id != book))
        new_data = (replace(command, snapshot=snapshot), *data[1:])
        prepared = authorize(new_data)
        self.assertFalse(auth.verify(prepared)['streams'][book]['required_by_engine'])
        self.assertEqual('evaluated', analytics.serialize_result(analytics.evaluate_command(prepared))['result_kind'])

    def test_future_evidence_is_error_not_a_way_to_hide_adverse_records(self):
        data = fixtures()
        data[3]['records'][0]['received_at'] = codec._encode(data[0].snapshot.evaluated_at + timedelta(seconds=1))
        with self.assertRaisesRegex(auth.ValidationFailure, 'future'):
            authorize(data)

    def test_frozen_phase_expiry_does_not_invoke_current_validation(self):
        data = fixtures()
        frozen = authorize(data)
        later = replace(data[0], snapshot=replace(data[0].snapshot,
            evaluated_at=data[0].snapshot.evaluated_at + timedelta(hours=1)))
        with self.assertRaises(auth.UnmetPrerequisite):
            authorize((later, *data[1:]))
        with patch.object(auth.SyntheticEvidenceStore, 'capture', side_effect=AssertionError('no source fetch')):
            self.assertEqual(analytics.serialize_command(frozen),
                analytics.serialize_command(analytics.deserialize_command(analytics.serialize_command(frozen))))
            auth.verify(frozen)

    def test_unordered_inventory_and_approval_references_have_canonical_serialization(self):
        data = fixtures()
        policy, catalog = deepcopy(data[2]), deepcopy(data[3])
        for kind in ('phase', 'settlement'):
            policy[kind + '_approval_references'].reverse()
        for collection in ('records', 'approvals', 'withdrawals'):
            catalog[collection].reverse()
        self.assertEqual(auth.AuthorityPolicy(codec.canonical_json(data[2])), auth.AuthorityPolicy(codec.canonical_json(policy)))
        self.assertEqual(source(data[3]).capture(data[0].snapshot.evaluated_at), source(catalog).capture(data[0].snapshot.evaluated_at))


@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE') == '1' and os.getenv('CORNER_TEST_CONCURRENCY') == '1',
                     'opt-in disposable v2 capture PostgreSQL tests')
class V2CaptureTests(WorkDatabase, unittest.TestCase):
    select = db_fixture.EVSelectionTests.select
    append = db_fixture.EVSelectionTests.append

    def setUp(self):
        with patch('db.insert.connect', self.connect):
            db_fixture.EVSelectionTests.setUp(self)
        self.authority = channels.ChannelAuthority('service', 'capture-v2-' + uuid4().hex)
        self.settings = worker.WorkerSettings('worker-a', self.authority, timedelta(minutes=1), timedelta(seconds=1), 2,
                                             timedelta(seconds=10))
        old = self.select()
        command = math.conditional(codec.EvaluationCommand(old.snapshot, replace(old.configuration,
            target_max_age=timedelta(days=36500), reference_max_age=timedelta(days=36500))))
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            binding = capture._binding(cur, self.outcome_id)
        self.data = fixtures(command, binding, at=datetime.now(timezone.utc))
        self.source = source(self.data[3])
        self.config = capture.GenerationConfiguration(math.generation(command),
            auth.AuthorityPolicy(codec.canonical_json(self.data[2])))
        self.channel = channels.create_channel(self.conn, code='v2-' + uuid4().hex, display_name='Synthetic capture')
        self.generation = self.register(self.config)
        self.condition = lifecycle_store.resolve_condition(self.conn, sportsbook_id=self.book_id, outcome_id=self.outcome_id,
                                                          channel_id=self.channel['id'])
        self.conn.commit()

    def register(self, config):
        return capture.register_generation(self.conn, authority=self.authority, registration_key=str(uuid4()),
            command=channels.GenerationRegistration(self.channel['id'], config))

    def request(self, generation=None):
        row = work.enqueue(self.conn, kind='evaluate', namespace=self.authority.identifier, key=str(uuid4()),
            sources={'condition_id': self.condition['id'], 'generation_id': (generation or self.generation)['id']},
            intent_json=codec.canonical_json(capture.request_intent(outcome_id=self.outcome_id, sportsbook_id=self.book_id)))
        self.conn.commit()
        return row

    def runtime_connect(self):
        conn = self.connect()
        with conn.cursor() as cur:
            cur.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(self.roles['worker'])))
        conn.commit()
        return conn

    def run_request(self, request, **kwargs):
        return capture.run_once(self.runtime_connect, settings=kwargs.pop('settings', self.settings), request_id=request['id'],
                                source=kwargs.pop('source', self.source), **kwargs)

    def crash_after_prepare(self, request):
        with patch.object(capture, 'complete', side_effect=SystemExit('synthetic crash')):
            with self.assertRaises(SystemExit): self.run_request(request)
        return capture.load_prepared(self.conn, request_id=request['id'])

    def expire(self, request):
        with self.conn.cursor() as cur:
            cur.execute("UPDATE corner.work_executions SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE work_request_id=%s",
                        (request['id'],))
        self.conn.commit()

    def test_generation_and_preparation_complete_without_activations_or_lifecycle(self):
        request = self.request()
        result = self.run_request(request)
        self.assertEqual('completed', result['status'], result)
        prepared = capture.load_prepared(self.conn, request_id=request['id'])
        self.assertEqual(capture.COMMAND_FORMAT, prepared['command_format_version'])
        auth.verify(analytics.deserialize_command(prepared['command_snapshot']['payload']))
        with self.conn.cursor() as cur:
            cur.execute('SELECT command_snapshot FROM corner.engine_evaluations WHERE id=%s', (result['execution']['engine_evaluation_id'],))
            self.assertEqual(prepared['command_snapshot']['payload'], cur.fetchone()[0])
            cur.execute('SELECT count(*) FROM corner.lifecycle_applications WHERE condition_id=%s', (self.condition['id'],))
            self.assertEqual(0, cur.fetchone()[0])

    def test_frozen_retry_survives_withdrawal_quote_movement_and_phase_expiry(self):
        request = self.request()
        frozen = self.crash_after_prepare(request)
        self.append(self.target_id, price='1.01', observed_at=datetime.now(timezone.utc))
        catalog = deepcopy(self.data[3])
        now = codec._encode(datetime.now(timezone.utc))
        catalog['withdrawals'].append({'id': str(uuid4()), 'approval_id': catalog['approvals'][0]['id'],
            'recorded_at': now, 'effective_at': now, 'reason': 'synthetic withdrawal'})
        self.source = source(catalog)
        self.expire(request)
        with patch.object(capture, 'capture', side_effect=AssertionError('must not recapture')):
            result = self.run_request(request, source=None, settings=replace(self.settings, owner='worker-b'))
        self.assertEqual('completed', result['status'], result)
        self.assertEqual(frozen, capture.load_prepared(self.conn, request_id=request['id']))
        later = self.request()
        result = self.run_request(later)
        self.assertEqual(('waiting', 'approval_withdrawn'), (result['status'], result['reason']))
        self.assertIsNone(capture.load_prepared(self.conn, request_id=later['id']))

    def test_production_positive_is_impossible_with_synthetic_loader(self):
        policy = dict(self.data[2]) | {'environment': 'production'}
        generation = self.register(replace(self.config, authority=auth.AuthorityPolicy(codec.canonical_json(policy))))
        request = self.request(generation)
        result = self.run_request(request)
        self.assertEqual('waiting', result['status'])
        self.assertIsNone(capture.load_prepared(self.conn, request_id=request['id']))

    def test_missing_authority_and_invalid_evidence_never_create_evaluations(self):
        for mode in ('missing', 'corrupt'):
            catalog = deepcopy(self.data[3])
            if mode == 'missing': catalog['records'].pop()
            else: catalog['records'][0]['content_sha256'] = '0' * 64
            request = self.request()
            result = self.run_request(request, source=source(catalog))
            self.assertEqual('waiting' if mode == 'missing' else 'blocked', result['status'], result)
            self.assertIsNone(capture.load_prepared(self.conn, request_id=request['id']))
            with self.conn.cursor() as cur:
                cur.execute('SELECT count(*) FROM corner.engine_evaluations WHERE evaluation_key=%s',
                            ('corner.worker.capture-v2:' + request['id'],))
                self.assertEqual(0, cur.fetchone()[0])

    def test_old_generation_cannot_obtain_missing_authority_from_runtime_source(self):
        generation = analytics.register_generation(self.conn, authority=self.authority, registration_key=str(uuid4()),
            command=channels.GenerationRegistration(self.channel['id'], self.config.analytics))
        request = self.request(generation)
        self.assertEqual('blocked', self.run_request(request)['status'])
        self.assertIsNone(capture.load_prepared(self.conn, request_id=request['id']))

    def test_non_evaluable_pricing_is_successful_authorized_completion(self):
        self.append(self.target_id, state='unavailable', price=None, observed_at=datetime.now(timezone.utc))
        self.conn.commit()
        request = self.request()
        result = self.run_request(request)
        self.assertEqual('completed', result['status'], result)
        with self.conn.cursor() as cur:
            cur.execute('SELECT result_kind FROM corner.engine_evaluations WHERE id=%s', (result['execution']['engine_evaluation_id'],))
            self.assertEqual('not_evaluable', cur.fetchone()[0])

    def test_lease_reclaim_during_capture_fences_old_preparer(self):
        request = self.request()
        entered, release = threading.Event(), threading.Event()
        original = capture.capture
        def slow(*args, **kwargs):
            value = original(*args, **kwargs)
            entered.set()
            self.assertTrue(release.wait(10))
            return value
        with ThreadPoolExecutor(max_workers=1) as pool, patch.object(capture, 'capture', side_effect=slow):
            job = pool.submit(self.run_request, request)
            self.assertTrue(entered.wait(10))
            self.expire(request)
            lease = work.claim(self.conn, owner='worker-b', lease_for=timedelta(minutes=1), request_id=request['id'])
            self.conn.commit()
            release.set()
            self.assertEqual('lease_lost', job.result(10)['status'])
        self.assertIsNone(capture.load_prepared(self.conn, request_id=request['id']))
        capture.prepare_once(self.runtime_connect, lease=lease, settings=replace(self.settings, owner='worker-b'), source=self.source)
        self.assertIsNotNone(capture.load_prepared(self.conn, request_id=request['id']))

    def test_concurrent_preparers_return_one_original_frozen_command(self):
        request = self.request()
        lease = work.claim(self.conn, owner=self.settings.owner, lease_for=self.settings.lease_for, request_id=request['id'])
        self.conn.commit()
        barrier = threading.Barrier(2)
        original = capture.capture
        def together(*args, **kwargs):
            result = original(*args, **kwargs)
            barrier.wait(10)
            return result
        with ThreadPoolExecutor(max_workers=2) as pool, patch.object(capture, 'capture', side_effect=together):
            jobs = [pool.submit(capture.prepare_once, self.runtime_connect, lease=lease, settings=self.settings, source=self.source)
                    for _ in range(2)]
            rows = [job.result(15) for job in jobs]
        self.assertEqual(rows[0], rows[1])

    def test_failed_domain_completion_rolls_back_and_preserves_frozen_command(self):
        request = self.request()
        frozen = self.crash_after_prepare(request)
        self.expire(request)
        real = analytics.record_evaluation
        def fail_after_write(*args, **kwargs):
            real(*args, **kwargs)
            raise ValueError('synthetic post-domain failure')
        with patch.object(analytics, 'record_evaluation', side_effect=fail_after_write):
            result = self.run_request(request)
        self.assertEqual('blocked', result['status'])
        self.assertEqual(frozen, capture.load_prepared(self.conn, request_id=request['id']))
        with self.conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM corner.engine_evaluations WHERE evaluation_key=%s',
                        ('corner.worker.capture-v2:' + request['id'],))
            self.assertEqual(0, cur.fetchone()[0])

    def test_frozen_unsupported_format_blocks_without_recapture(self):
        request = self.request()
        frozen = self.crash_after_prepare(request)
        self.expire(request)
        with (patch.object(analytics, 'deserialize_command', side_effect=ValueError('unsupported pinned format')),
              patch.object(capture, 'capture', side_effect=AssertionError('cannot recapture'))):
            self.assertEqual('blocked', self.run_request(request)['status'])
        self.assertEqual(frozen, capture.load_prepared(self.conn, request_id=request['id']))

    def test_approval_resolution_receipt_cannot_be_replaced_at_prepare(self):
        request = self.request()
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            current = work._request(cur, request['id'])
        command = capture.capture(self.conn, request=current, source=self.source)
        proof = auth.verify(command)
        proof['streams']['phase']['approval_resolutions'] = []
        changed = replace(command, context_json=codec.canonical_json({'capture_authorization': auth.envelope(proof)}))
        lease = work.claim(self.conn, owner=self.settings.owner, lease_for=self.settings.lease_for, request_id=request['id'])
        with self.assertRaises(auth.ValidationFailure):
            capture.prepare(self.conn, request_id=request['id'], owner=self.settings.owner, token=lease['lease_token'],
                command=changed, authority=self.authority, domain_key='tampered')
        self.assertIsNone(capture.load_prepared(self.conn, request_id=request['id']))

    def test_committed_completion_is_atomic_against_reclaimer_after_expiry(self):
        request = self.request()
        self.crash_after_prepare(request)
        self.expire(request)
        lease = work.claim(self.conn, owner=self.settings.owner, lease_for=self.settings.lease_for, request_id=request['id'])
        self.conn.commit()
        entered, release = threading.Event(), threading.Event()
        original = analytics.record_evaluation
        def held(conn, **kwargs):
            # Simulate expiry only after completion owns the execution fence.
            with conn.cursor() as cur:
                cur.execute("UPDATE corner.work_executions SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE work_request_id=%s",
                            (request['id'],))
            entered.set()
            self.assertTrue(release.wait(10))
            return original(conn, **kwargs)
        def execute():
            with worker._transaction(self.runtime_connect, self.settings) as conn:
                return capture.complete(conn, request_id=request['id'], owner=self.settings.owner, token=lease['lease_token'])
        with ThreadPoolExecutor(max_workers=1) as pool, patch.object(analytics, 'record_evaluation', side_effect=held):
            job = pool.submit(execute)
            self.assertTrue(entered.wait(10))
            with worker._transaction(self.runtime_connect, self.settings) as conn:
                self.assertIsNone(work.claim(conn, owner='worker-b', lease_for=self.settings.lease_for, request_id=request['id']))
            release.set()
            self.assertEqual('completed', job.result(10)['status'])
        with worker._transaction(self.runtime_connect, self.settings) as conn:
            self.assertIsNone(work.claim(conn, owner='worker-b', lease_for=self.settings.lease_for, request_id=request['id']))
