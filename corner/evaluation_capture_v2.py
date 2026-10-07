"""One explicitly routed v2 capture/execute attempt. No polling or assessment.

Parallel version boundary: pinned v1/v2 analytics and old worker bytes stay intact.
Prepared JSON retains the entire authorization proof; no assertion ledger needed.
Production capture is deliberately unavailable. Only synthetic approval fixtures
can exercise the positive path until an authenticated production loader is built.
"""
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
import hashlib
from pathlib import Path

from psycopg2.extras import Json, RealDictCursor

from corner import analytics_versions as analytics, capture_authority as auth
from corner import channels, ev, ev_conditional as conditional, evaluations as codec
from corner import ev_selection as selection, lifecycle_store, work, worker
from corner.lifecycle import ActionabilityPolicy, ImplementationIdentity

CHANNEL_FORMAT = 'corner.channel.configuration/3'
REGISTRATION_FORMAT = 'corner.channel.registration/3'
SELECTOR_FORMAT = 'corner.ev.selection/2'
COMMAND_FORMAT = 'corner.work.command/2'
REVISION = 'sha256:' + codec._digest({'source': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'authorization': auth.REVISION, 'analytics': analytics.REVISION,
    'selector': hashlib.sha256(Path(selection.__file__).read_bytes()).hexdigest(),
    'work': hashlib.sha256(Path(work.__file__).read_bytes()).hexdigest(),
    'worker': hashlib.sha256(Path(worker.__file__).read_bytes()).hexdigest()}).hex()


@dataclass(frozen=True)
class GenerationConfiguration:
    analytics: analytics.GenerationConfiguration
    authority: auth.AuthorityPolicy

    def __post_init__(self):
        auth.require(type(self.analytics) is analytics.GenerationConfiguration
                     and type(self.authority) is auth.AuthorityPolicy, 'explicit v2 capture generation required')


def generation_snapshot(config):
    auth.require(type(config) is GenerationConfiguration, 'capture-compatible generation required')
    return analytics.generation_snapshot(config.analytics) | {'snapshot_format_version': CHANNEL_FORMAT,
        'capture': {'format': SELECTOR_FORMAT, 'revision': REVISION, 'authority': config.authority.document}}


def _decode_configuration(doc):
    auth.require(doc['snapshot_format_version'] == CHANNEL_FORMAT and
        doc['capture']['format'] == SELECTOR_FORMAT and doc['capture']['revision'] == REVISION,
        'generation is not compatible with this pinned capture implementation')
    pricing = dict(doc['engine']['configuration']['pricing'])
    for key in ('target_max_age', 'reference_max_age', 'max_input_skew', 'provider_max_age'):
        pricing[key] = timedelta(microseconds=pricing[key]) if pricing[key] is not None else None
    pricing['provider_time_policy'] = ev.ProviderTimePolicy(pricing['provider_time_policy'])
    config = dict(doc['engine']['configuration'])
    config['pricing'] = ev.EVConfiguration(**pricing)
    config['settlement'] = conditional.SettlementPolicy(**config['settlement'])
    qualifier = doc['qualification']['configuration']
    life = doc['lifecycle']
    base = analytics.GenerationConfiguration(ImplementationIdentity(**doc['engine']['implementation']),
        conditional.Configuration(**config), ImplementationIdentity(**doc['qualification']['implementation']),
        analytics.ConditionalEVPolicy(qualifier['policy_version'], Decimal(qualifier['minimum_ev_ratio']),
                                     qualifier['expected_calculation_basis']),
        conditional.SettlementPolicy(**doc['settlement']), ActionabilityPolicy(
            ImplementationIdentity(**life['implementation']),
            timedelta(microseconds=life['configuration']['target_max_age_microseconds']),
            timedelta(microseconds=life['configuration']['reference_max_age_microseconds'])))
    result = GenerationConfiguration(base, auth.AuthorityPolicy(codec.canonical_json(doc['capture']['authority'])))
    auth.require(generation_snapshot(result) == doc, 'noncanonical/contradictory generation configuration')
    return result


def register_generation(conn, *, authority, registration_key, command):
    """New immutable format, existing ledger. Does not activate a generation."""
    key = channels._authority(authority, registration_key)
    config = generation_snapshot(command.configuration)
    _decode_configuration(config)
    document = {'snapshot_format_version': REGISTRATION_FORMAT, 'channel_id': channels._uuid(command.channel_id),
        'configuration': config, 'configuration_sha256': auth.digest(config), 'context': channels._context(command.context_json)}
    fields = ('registration_authority_kind', 'registration_authority_id', 'registration_key')
    with channels._write(conn, 'corner_capture_generation') as cur:
        existing = analytics._existing(cur, 'qualification_channel_generations', fields, key, document, 'registration_')
        if existing:
            return existing
        values = dict(zip(fields, key)) | dict(channel_id=document['channel_id'], snapshot_format_version=CHANNEL_FORMAT,
            configuration_snapshot=Json(config), configuration_sha256=codec._digest(config),
            registration_command_snapshot=Json(document), registration_command_sha256=codec._digest(document))
        for part in ('engine', 'qualification', 'lifecycle'):
            for field in ('name', 'version', 'revision'):
                values[part + '_' + field] = config[part]['implementation'][field]
        return analytics._insert(cur, 'qualification_channel_generations', values, fields, key, document, 'registration_')[0]


def request_intent(*, outcome_id, sportsbook_id):
    return {'outcome_id': channels._uuid(outcome_id), 'sportsbook_id': channels._uuid(sportsbook_id),
            'routing_version': 'corner.capture.route/2', 'selector': {'format': SELECTOR_FORMAT, 'revision': REVISION}}


def _scope(cur, request):
    auth.require(request['work_kind'] == 'evaluate' and request['condition_id'] and request['generation_id'],
                 'explicit evaluation condition/generation required')
    condition, _ = lifecycle_store._condition(cur, request['condition_id'])
    cur.execute('SELECT * FROM corner.qualification_channel_generations WHERE id=%s', (request['generation_id'],))
    generation = cur.fetchone()
    auth.require(generation is not None and generation['channel_id'] == condition['qualification_channel_id'],
                 'generation/channel mismatch')
    auth.require(bytes(generation['configuration_sha256']) == codec._digest(generation['configuration_snapshot']),
                 'generation digest mismatch')
    config = _decode_configuration(generation['configuration_snapshot'])
    auth.require(request['intent_snapshot']['intent'] == request_intent(outcome_id=condition['outcome_id'],
        sportsbook_id=condition['target_sportsbook_id']), 'request route/selector mismatch')
    return condition, config


def _binding(cur, outcome_id):
    cur.execute('''SELECT m.id market_id,m.event_id,e.competition_id,mt.code market_type,s.code scope
        FROM corner.outcomes o JOIN corner.markets m ON m.id=o.market_id
        JOIN corner.events e ON e.id=m.event_id JOIN corner.market_types mt ON mt.id=m.market_type_id
        JOIN corner.scopes s ON s.id=m.scope_id WHERE o.id=%s''', (outcome_id,))
    row = cur.fetchone()
    auth.require(row is not None, 'unknown canonical target')
    binding = dict(row)
    cur.execute('SELECT id FROM corner.outcomes WHERE market_id=%s ORDER BY id', (row['market_id'],))
    binding['outcome_ids'] = [o['id'] for o in cur.fetchall()]
    cur.execute('SELECT provider_id,external_id FROM corner.event_provider_identities WHERE event_id=%s AND active ORDER BY provider_id',
                (row['event_id'],))
    binding['provider_identities'] = [[r['provider_id'], r['external_id']] for r in cur.fetchall()]
    return binding


def capture(conn, *, request, source=None):
    """Read-only capture; source is deployment-owned, NOT caller intent metadata."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        condition, config = _scope(cur, request)
        if config.authority.document['environment'] != 'synthetic' or source is None:
            raise auth.UnmetPrerequisite('production_authority_not_installed')
        auth.require(type(source) is auth.SyntheticEvidenceStore, 'no approved loader installed for supplied source')
        binding = _binding(cur, condition['outcome_id'])
        at = work._now(cur)
    # Provisional labels are selection metadata only. No command leaves capture
    # until the actual assertions authorize replacing them below.
    selected = selection.select_ev_snapshot(conn, target_outcome_id=condition['outcome_id'],
        target_sportsbook_id=condition['target_sportsbook_id'], evaluated_at=at,
        configuration=config.analytics.engine_configuration.pricing,
        validation=selection.MarketValidation(binding['event_id'], binding['market_id'],
            'unknown', 'authorization pending', 'unknown', 'authorization pending'))
    if selected.reason == selection.SelectionReason.NO_TRUSTED_TARGET:
        raise auth.UnmetPrerequisite('evaluation_target_missing')
    auth.require(selected.snapshot is not None and selected.reason is None, 'canonical snapshot selection failed')
    return auth.authorize(selected.snapshot, config.analytics.engine_configuration, config.authority,
                          binding, source.capture(at))


def _document(command, authority, key):
    who, identifier, key = channels._authority(authority, key)
    return {'format': COMMAND_FORMAT, 'work_kind': 'evaluate', 'implementation': REVISION,
        'authority': {'kind': who, 'identifier': identifier}, 'domain_command_key': key,
        'payload': analytics.serialize_command(command)}


def _prepared(cur, request_id):
    cur.execute('SELECT * FROM corner.prepared_work_commands WHERE work_request_id=%s', (request_id,))
    row = cur.fetchone()
    if row:
        auth.require(row['command_format_version'] == COMMAND_FORMAT and row['command_snapshot']['format'] == COMMAND_FORMAT
            and bytes(row['command_sha256']) == codec._digest(row['command_snapshot']), 'unsupported/corrupt frozen command')
    return dict(row) if row else None


def _verify(cur, request, document, *, preparing=False):
    auth.require(document['format'] == COMMAND_FORMAT and document['implementation'] == REVISION
                 and document['work_kind'] == 'evaluate', 'original capture implementation unavailable')
    command = analytics.deserialize_command(document['payload'])
    proof = auth.verify(command)  # Retained data ONLY. No loader/current-state call.
    condition, config = _scope(cur, request)
    auth.require(command.configuration == config.analytics.engine_configuration
                 and proof['policy'] == config.authority.document, 'frozen generation authority mismatch')
    target = next(q for q in command.snapshot.quotes if q.observation_id == command.snapshot.target_observation_id)
    auth.require((condition['outcome_id'], condition['target_sportsbook_id']) == (target.outcome_id, target.sportsbook_id),
                 'frozen target/condition mismatch')
    cur.execute('SELECT event_id FROM corner.markets WHERE id=%s', (command.snapshot.contract.market_id,))
    row = cur.fetchone()
    auth.require(row and row['event_id'] == proof['binding']['event_id'], 'frozen event binding mismatch')
    if preparing:
        # Verify the capture's canonical universe before first persistence. Replay
        # keeps these exact bindings, not today's mutable provider reconciliation.
        auth.require(_binding(cur, condition['outcome_id']) == proof['binding'], 'capture identity inventory mismatch')
        cur.execute('SELECT id,selected_participant_id,point FROM corner.outcomes WHERE market_id=%s',
                    (command.snapshot.contract.market_id,))
        actual = {r['id']: (r['selected_participant_id'], r['point']) for r in cur.fetchall()}
        claimed = {o.outcome_id: (o.participant_id, o.point) for o in command.snapshot.contract.outcomes}
        auth.require(actual == claimed, 'capture canonical outcomes mismatch')
    codec._validate_evidence(cur, command)
    return command


def prepare(conn, *, request_id, owner, token, command, authority, domain_key):
    with channels._write(conn, 'corner_v2_prepare') as cur:
        work._fence(cur, request_id, owner, token)
        request = work._request(cur, request_id)
        document = _document(command, authority, domain_key)
        prior = _prepared(cur, request_id)
        if prior:
            if prior['command_snapshot'] != document:
                raise work.WorkConflict('preparation is already frozen')
            _verify(cur, request, prior['command_snapshot'])
            return prior
        _verify(cur, request, document, preparing=True)
        cur.execute('''INSERT INTO corner.prepared_work_commands
            (work_request_id,command_format_version,command_snapshot,command_sha256) VALUES (%s,%s,%s,%s) RETURNING *''',
            (request_id, COMMAND_FORMAT, Json(document), codec._digest(document)))
        return dict(cur.fetchone())


def load_prepared(conn, *, request_id):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        return _prepared(cur, request_id)


def complete(conn, *, request_id, owner, token):
    with channels._write(conn, 'corner_v2_complete') as cur:
        work._fence(cur, request_id, owner, token)
        request = work._request(cur, request_id)
        prepared = _prepared(cur, request_id)
        auth.require(prepared is not None, 'missing frozen preparation')
        document = prepared['command_snapshot']
        command = _verify(cur, request, document)
        result = analytics.record_evaluation(conn, authority=channels.ChannelAuthority(**document['authority']),
            evaluation_key=document['domain_command_key'], command=command)
        work._result_matches(cur, document, result)
        cur.execute('''UPDATE corner.work_executions SET status='completed',completed_at=clock_timestamp(),
            lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,prepared_command_id=%s,engine_evaluation_id=%s,
            updated_at=clock_timestamp() WHERE work_request_id=%s RETURNING *''',
            (prepared['id'], result['id'], request_id))
        return dict(cur.fetchone())


def prepare_once(connect, *, lease, settings, source=None):
    request_id = lease['work_request_id']
    with worker._transaction(connect, settings) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            work._fence(cur, request_id, settings.owner, lease['lease_token'])
            request = work._request(cur, request_id)
            frozen = _prepared(cur, request_id)
            if frozen:
                _verify(cur, request, frozen['command_snapshot'])
                return frozen
    # No execution lock held during capture; stale preparers are fenced below.
    with worker._transaction(connect, settings, read_only=True) as conn:
        command = capture(conn, request=request, source=source)
    with worker._transaction(connect, settings) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            work._fence(cur, request_id, settings.owner, lease['lease_token'])
            prior = _prepared(cur, request_id)
            if prior:
                _verify(cur, request, prior['command_snapshot'])
                return prior  # Concurrent same-token winner, never replace it.
        return prepare(conn, request_id=request_id, owner=settings.owner, token=lease['lease_token'], command=command,
                       authority=settings.authority, domain_key='corner.worker.capture-v2:' + request_id)


def run_once(connect, *, settings, request_id, source=None):
    """Explicit-request worker only. Does not discover/claim unrelated v1 work."""
    auth.require(isinstance(settings, worker.WorkerSettings), 'validated settings required')
    lease = None
    try:
        with worker._transaction(connect, settings) as conn:
            lease = work.claim(conn, owner=settings.owner, lease_for=settings.lease_for, request_id=request_id, kinds=('evaluate',))
        if lease is None:
            return {'status': 'idle', 'request_id': request_id}
        prepare_once(connect, lease=lease, settings=settings, source=source)
        with worker._transaction(connect, settings) as conn:
            result = complete(conn, request_id=request_id, owner=settings.owner, token=lease['lease_token'])
        return {'status': 'completed', 'request_id': request_id, 'execution': result}
    except Exception as error:
        if lease is None:
            raise
        # New transaction after rollback. Never let a stale worker record errors.
        with worker._transaction(connect, settings) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute('SELECT * FROM corner.work_executions WHERE work_request_id=%s', (request_id,))
                execution = cur.fetchone()
                if execution and execution['status'] == 'completed':
                    request = work._request(cur, request_id)
                    prepared = _prepared(cur, request_id)
                    auth.require(prepared and prepared['id'] == execution['prepared_command_id'], 'completion binding mismatch')
                    _verify(cur, request, prepared['command_snapshot'])
                    work._result_matches(cur, prepared['command_snapshot'], {'id': execution['engine_evaluation_id']})
                    return {'status': 'completed', 'request_id': request_id, 'execution': dict(execution)}
                try:
                    current = work._fence(cur, request_id, settings.owner, lease['lease_token'])
                except work.LeaseLost:
                    return {'status': 'lease_lost', 'request_id': request_id}
                if isinstance(error, auth.UnmetPrerequisite):
                    state, reason = 'waiting', str(error)
                elif isinstance(error, auth.IncompatibleConditions):
                    state, reason = 'blocked', 'incompatible_decisive_settlement_conditions'
                else:
                    state, reason = worker._classification(error, current['retry_count'], settings)
                retry_at = work._now(cur) + settings.retry_delay if state == 'retryable' else None
            work.record_failure(conn, request_id=request_id, owner=settings.owner, token=lease['lease_token'],
                status=state, reason=reason, retry_at=retry_at,
                details_json=codec.canonical_json({'error_type': type(error).__name__}))
        return {'status': state, 'request_id': request_id, 'reason': reason}
