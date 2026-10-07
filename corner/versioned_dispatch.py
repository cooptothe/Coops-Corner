"""Explicit installed implementation routing. No polling or default version.

Old prepared envelopes remain executable by their exact format/build tuple.
New downstream requests pin a route derived from immutable generation/evidence.
"""
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal

from psycopg2.extras import Json, RealDictCursor
from corner import work as w, worker as runner, channels as ch, evaluations as ev, qualifications as q1
from corner import assessments as a1, assessments_v2 as a2, analytics_versions as av
from corner import evaluation_capture as e1, evaluation_capture_v2 as e2, assessment_worker_v2 as aw2
from corner import lifecycle_store as l1, lifecycle_versions as l2, capture_authority as auth
from corner import lifecycle as life, ev as math, ev_conditional as conditional

ROUTE_FORMAT = 'corner.work.routing/1'
COMMAND_FORMAT = 'corner.work.dispatch/1'
V2_DOMAIN_FORMAT = 'corner.work.domain/2'
# Exact installed builds, not mutable "latest" aliases. Adding a handler does not
# change existing handler identities or reinterpret an older envelope.
HANDLERS = {
    'evaluate.v1': ('evaluate', w.COMMAND_FORMAT, ev.ENGINE_REVISION),
    'evaluate.v2': ('evaluate', e2.COMMAND_FORMAT, e2.REVISION),
    'qualify.v1': ('qualify', w.COMMAND_FORMAT, q1.POLICY_REVISION),
    'qualify.v2': ('qualify', V2_DOMAIN_FORMAT, av.REVISION),
    'occurrence.v1': ('ensure_occurrence', w.COMMAND_FORMAT, w.OCCURRENCE_REVISION),
    'assess.v1': ('assess', w.COMMAND_FORMAT, a1.IMPLEMENTATION.revision),
    'assess.v2': ('assess', aw2.FORMAT, a2.REVISION),
    'lifecycle.v1': ('apply_lifecycle', w.COMMAND_FORMAT, l1.REVISION),
    'lifecycle.v2': ('apply_lifecycle', V2_DOMAIN_FORMAT, l2.REVISION),
}


def handler(document):
    match = [name for name, identity in HANDLERS.items() if identity ==
             (document.get('work_kind'), document.get('format'), document.get('implementation'))]
    if len(match) != 1: raise w.WorkBlocked('unsupported or missing frozen implementation identity')
    return match[0]


def generation(cur, identity, condition_id):
    row = a1._row(cur, 'qualification_channel_generations', identity)
    a1._verify(row, 'configuration_snapshot', 'configuration_sha256')
    a1._verify(row, 'registration_command_snapshot', 'registration_command_sha256')
    doc, registration = row['configuration_snapshot'], row['registration_command_snapshot']
    condition, key = l1._condition(cur, condition_id)
    w._require(row['channel_id'] == condition['qualification_channel_id'] and registration['channel_id'] == row['channel_id']
        and registration['configuration'] == doc and registration['configuration_sha256'] == bytes(row['configuration_sha256']).hex()
        and doc['snapshot_format_version'] == row['snapshot_format_version'], 'generation binding mismatch')
    formats = {ch.CONFIGURATION_FORMAT: ch.REGISTRATION_FORMAT, av.CHANNEL_FORMAT: av.REGISTRATION_FORMAT,
               e2.CHANNEL_FORMAT: e2.REGISTRATION_FORMAT}
    w._require(doc['snapshot_format_version'] in formats and registration['snapshot_format_version'] == formats[doc['snapshot_format_version']],
               'unsupported generation version')
    if doc['snapshot_format_version'] == ch.CONFIGURATION_FORMAT:
        l1._generation(cur, identity, condition)
        family = 'v1'
    elif doc['snapshot_format_version'] == e2.CHANNEL_FORMAT:
        e2._decode_configuration(doc)
        family = 'v2'
    elif doc['snapshot_format_version'] == av.CHANNEL_FORMAT:
        pricing = dict(doc['engine']['configuration']['pricing'])
        for name in ('target_max_age', 'reference_max_age', 'max_input_skew', 'provider_max_age'):
            pricing[name] = timedelta(microseconds=pricing[name]) if pricing[name] is not None else None
        pricing['provider_time_policy'] = math.ProviderTimePolicy(pricing['provider_time_policy'])
        config = dict(doc['engine']['configuration'])
        config['pricing'] = math.EVConfiguration(**pricing)
        config['settlement'] = conditional.SettlementPolicy(**config['settlement'])
        p, lp = doc['qualification']['configuration'], doc['lifecycle']
        decoded = av.GenerationConfiguration(life.ImplementationIdentity(**doc['engine']['implementation']),
            conditional.Configuration(**config), life.ImplementationIdentity(**doc['qualification']['implementation']),
            av.ConditionalEVPolicy(p['policy_version'], Decimal(p['minimum_ev_ratio']), p['expected_calculation_basis']),
            conditional.SettlementPolicy(**doc['settlement']), life.ActionabilityPolicy(life.ImplementationIdentity(**lp['implementation']),
                timedelta(microseconds=lp['configuration']['target_max_age_microseconds']),
                timedelta(microseconds=lp['configuration']['reference_max_age_microseconds'])))
        w._require(av.generation_snapshot(decoded) == doc, 'incompatible generation policy tuple')
        family = 'v2'
    else:
        raise w.WorkBlocked('generation implementation unavailable')
    for part in ('engine', 'qualification', 'lifecycle'):
        w._require(all(row[part + '_' + f] == doc[part]['implementation'][f] for f in ('name', 'version', 'revision')),
                   'generation identity projection mismatch')
    return row, family, condition, key


def evaluation(cur, identity, gen, condition):
    row = a1._row(cur, 'engine_evaluations', identity)
    a1._verify(row, 'command_snapshot', 'command_sha256')
    av.decode_evaluation(row)
    command = av.deserialize_command(row['command_snapshot'])
    ev._validate_evidence(cur, command)
    engine = gen['configuration_snapshot']['engine']; doc = row['command_snapshot']
    w._require(engine['configuration'] == doc['configuration'] and engine['implementation'] ==
        {k: doc['engine_' + k] for k in ('name', 'version', 'revision')}, 'evaluation/generation implementation mismatch')
    target = next(v for v in command.snapshot.quotes if v.observation_id == command.snapshot.target_observation_id)
    w._require((condition['outcome_id'], condition['target_sportsbook_id']) == (target.outcome_id, target.sportsbook_id),
               'evaluation target mismatch')
    return row


def qualifier(gen, family):
    p = gen['configuration_snapshot']['qualification']['configuration']
    if family == 'v1': return q1.MinimumEVPolicy(p['policy_version'], Decimal(p['minimum_ev_ratio']))
    if family == 'v2': return av.ConditionalEVPolicy(p['policy_version'], Decimal(p['minimum_ev_ratio']), p['expected_calculation_basis'])
    raise w.WorkBlocked('qualifier unavailable')


def decision(cur, identity):
    """Verify an existing judgment without requiring a routing assignment."""
    row = a1._row(cur, 'qualification_decisions', identity)
    a1._verify(row, 'command_snapshot', 'command_sha256'); a1._verify(row, 'result_snapshot', 'result_sha256')
    doc = row['command_snapshot']; p = doc['policy']; fmt = row['qualification_snapshot_format_version']
    if fmt == q1.FORMAT_VERSION:
        from corner.reconciliation import _qualification
        _qualification(cur, row)
        return row
    w._require(fmt == av.QUALIFICATION_FORMAT and doc['qualification_snapshot_format_version'] == fmt, 'unsupported qualification version')
    policy = av.ConditionalEVPolicy(p['policy_version'], Decimal(p['minimum_ev_ratio']), p['expected_calculation_basis'])
    w._require(av.qualification_policy_snapshot(policy) == p and ev._digest(p).hex() == doc['policy_sha256'], 'qualification policy mismatch')
    erow = a1._row(cur, 'engine_evaluations', row['engine_evaluation_id'])
    a1._verify(erow, 'command_snapshot', 'command_sha256')
    result = av.qualify_evaluation(erow, policy)
    expected = q1._result_snapshot(result, doc) | {'calculation_basis': av.v2.BASIS}
    w._require(doc['engine_evaluation_id'] == erow['id'] and doc['evaluation_snapshot_format_version'] == erow['snapshot_format_version']
        and bytes(row['evaluation_result_sha256']) == bytes(erow['result_sha256'])
        and doc['evaluation_result_sha256'] == bytes(erow['result_sha256']).hex()
        and doc['decided_at'] == ev._encode(row['decided_at']) and row['result_snapshot'] == expected
        and row['decision_kind'] == result.decision_kind and row['reason_code'] == result.reason_code
        and all(row[k] == p[k] for k in ('policy_name', 'policy_version', 'policy_revision')), 'qualification evidence mismatch')
    return row


def route(cur, kind, sources, intent):
    """Produce a deterministic routing contract from exact immutable authority."""
    gen = family = condition = key = None
    if kind != 'ensure_occurrence':
        w._require(sources.get('condition_id') and sources.get('generation_id'), 'explicit condition/generation required')
        gen, family, condition, key = generation(cur, sources['generation_id'], sources['condition_id'])
    evidence = None
    if kind == 'qualify':
        evidence = evaluation(cur, sources['engine_evaluation_id'], gen, condition)
        selected = 'qualify.' + family
    elif kind == 'ensure_occurrence':
        evidence = decision(cur, sources['qualification_decision_id'])
        w._require(evidence['decision_kind'] == 'qualified', 'occurrence requires qualified decision')
        selected = 'occurrence.v1'
    elif kind == 'apply_lifecycle':
        command_kind = intent['command_kind']
        w._require(command_kind in l1._SOURCE_COLUMNS, 'unsupported lifecycle command kind')
        if family == 'v1': adapter = l1
        elif family == 'v2': adapter = l2
        else: raise w.WorkBlocked('lifecycle implementation unavailable')
        adapter._generation(cur, gen['id'], condition)
        column = l1._SOURCE_COLUMNS[command_kind]
        table = dict(evaluation='engine_evaluations', qualification='qualification_decisions',
                     assessment='actionability_assessments', generation_activation='channel_generation_activations')[command_kind]
        evidence = a1._row(cur, table, sources[column])
        if command_kind == 'evaluation': evaluation(cur, evidence['id'], gen, condition)
        elif command_kind == 'qualification': adapter._qualification(cur, evidence['id'], gen['id'], key)
        elif command_kind == 'assessment':
            fmt = a1.FORMAT_VERSION if family == 'v1' else a2.FORMAT
            w._require(evidence['snapshot_format_version'] == fmt and evidence['channel_generation_id'] == gen['id'], 'assessment family mismatch')
            cmd = adapter.ApplicationCommand(condition['id'], 'assessment', evidence['id'], gen['id'])
            adapter._input(cur, adapter._document(cmd), condition, key)
        else:
            w._require(evidence['new_generation_id'] == gen['id'], 'activation generation mismatch')
            cmd = adapter.ApplicationCommand(condition['id'], command_kind, evidence['id'], gen['id'], evidence['activated_at'])
            adapter._input(cur, adapter._document(cmd), condition, key)
        selected = 'lifecycle.' + family
    elif kind == 'assess':
        selected = 'assess.' + family
        if family == 'v2':
            a2.load(cur, gen['id'], sources['qualification_decision_id'], intent['evaluation_watermark_id'], intent['basis_assessment_id'])
        elif family == 'v1':
            a1._load(cur, gen['id'], sources['qualification_decision_id'], intent['evaluation_watermark_id'], intent['basis_assessment_id'])
        evidence = decision(cur, sources['qualification_decision_id'])
    elif kind == 'evaluate':
        selected = 'evaluate.' + family
    else: raise w.WorkBlocked('unsupported work kind')
    _, command_format, revision = HANDLERS[selected]
    return {'format': ROUTE_FORMAT, 'handler': selected, 'command_format': command_format, 'implementation_revision': revision,
        'generation_id': gen['id'] if gen else None, 'generation_sha256': bytes(gen['configuration_sha256']).hex() if gen else None,
        'source_id': evidence['id'] if evidence else None,
        'source_format': evidence.get('snapshot_format_version', evidence.get('qualification_snapshot_format_version')) if evidence else None,
        'source_sha256': bytes(evidence.get('result_sha256', evidence.get('command_sha256'))).hex() if evidence else None}


def request_intent(cur, *, kind, sources, details=None):
    w._require(kind in ('qualify', 'ensure_occurrence', 'apply_lifecycle'),
               'capture work uses its existing explicitly versioned intent factory')
    details = dict(details or {})
    w._require('dispatch' not in details, 'routing is derived, not caller supplied')
    return details | {'dispatch': route(cur, kind, sources, details)}


def prepared(cur, identity):
    cur.execute('SELECT * FROM corner.prepared_work_commands WHERE work_request_id=%s', (identity,))
    row = cur.fetchone()
    if row:
        w._require(row['command_format_version'] == row['command_snapshot']['format']
            and bytes(row['command_sha256']) == ev._digest(row['command_snapshot']), 'invalid frozen format/digest')
    return row


def request_route(cur, request):
    """Recognize explicit new routes and narrowly defined retained v1 intents.

    Legacy support is based on exact immutable formats/policies, not absence of
    a version. Generic qualify intents still have no routing authority.
    """
    intent = request['intent_snapshot']['intent']
    expected = route(cur, request['work_kind'], request, intent)
    if 'dispatch' in intent:
        w._require(intent['dispatch'] == expected, 'incompatible request implementation route')
        return expected
    selected = expected['handler']
    if selected == 'qualify.v1':
        gen, _, _, _ = generation(cur, request['generation_id'], request['condition_id'])
        known = {'routing_version': 'corner.evaluation.routing/1', 'qualification': gen['configuration_snapshot']['qualification']}
        w._require(intent == known, 'missing qualification version identity')
    elif selected == 'lifecycle.v1':
        w._require(intent == {'command_kind': intent['command_kind']}, 'unknown legacy lifecycle intent')
    elif selected == 'occurrence.v1' and expected['source_format'] == q1.FORMAT_VERSION:
        w._require(intent == {}, 'unknown legacy occurrence intent')
    else: raise w.WorkBlocked('missing request implementation identity')
    return expected


def validate(cur, request, document):
    outer = document
    if document.get('format') == COMMAND_FORMAT:
        w._require(set(document) == {'format', 'route', 'command'}, 'invalid dispatch envelope')
        document = document['command']
    selected = handler(document)  # Explicit tuple match, never default-to-v1.
    w._require(document['work_kind'] == request['work_kind'], 'frozen kind mismatch')
    if request.get('generation_id') and request.get('condition_id'):
        _, family, _, _ = generation(cur, request['generation_id'], request['condition_id'])
        w._require(selected == 'occurrence.v1' or selected.endswith('.' + family), 'frozen implementation/generation family mismatch')
    intent = request['intent_snapshot']['intent']
    if 'dispatch' in intent or outer.get('format') == COMMAND_FORMAT:
        expected = request_route(cur, request)
        w._require(expected['handler'] == selected, 'incompatible request implementation route')
        if outer.get('format') == COMMAND_FORMAT:
            w._require(outer['route'] == expected, 'frozen route mismatch')
    payload = document['payload']
    if selected == 'evaluate.v2': e2._verify(cur, request, document)
    elif selected == 'assess.v2': aw2._verify(cur, request, document)
    elif selected in ('qualify.v2', 'lifecycle.v2'):
        w._require('dispatch' in intent, 'explicit versioned route required')
        gen, family, condition, _ = generation(cur, request['generation_id'], request['condition_id'])
        if selected == 'qualify.v2':
            w._require(payload['engine_evaluation_id'] == request['engine_evaluation_id']
                and payload['policy'] == ev._encode(asdict(qualifier(gen, family))), 'frozen qualifier policy mismatch')
        else:
            w._require(payload['format'] == l2.FORMAT and payload['condition_id'] == request['condition_id']
                and payload['generation_id'] == request['generation_id'] and payload['kind'] == intent['command_kind']
                and payload['evidence_id'] == request[l1._SOURCE_COLUMNS[payload['kind']]], 'frozen lifecycle route mismatch')
    else:
        # Each entry above explicitly identifies an installed legacy build.
        w._bind(cur, request, document)
        if selected == 'qualify.v1':
            gen, family, condition, _ = generation(cur, request['generation_id'], request['condition_id'])
            w._require(family == 'v1', 'legacy qualifier/generation mismatch')
            evaluation(cur, request['engine_evaluation_id'], gen, condition)
            w._require(payload['policy'] == ev._encode(asdict(qualifier(gen, family))), 'legacy qualifier policy mismatch')
        if selected == 'assess.v1':
            w._require(payload['snapshot_format_version'] == a1.FORMAT_VERSION, 'legacy assessment format mismatch')
            command = a1.AssessmentCommand(ev.canonical_json(payload['capture']), datetime.fromisoformat(payload['assessed_at']),
                                          ev.canonical_json(payload['context']))
            w._require(a1._document(command) == payload, 'legacy assessment implementation mismatch')
        if selected == 'evaluate.v1': ev.deserialize_command(payload)
        if selected == 'lifecycle.v1':
            w._require(payload.get('format') == l1.FORMAT, 'unsupported legacy lifecycle payload version')
            command = l1.ApplicationCommand(payload['condition_id'], payload['kind'], payload['evidence_id'], payload['generation_id'],
                datetime.fromisoformat(payload['transition_at']) if payload['transition_at'] else None, ev.canonical_json(payload['context']))
            w._require(l1._document(command) == payload, 'legacy lifecycle command mismatch')
    return selected, document


def result_matches(cur, document, result):
    inner = document['command'] if document.get('format') == COMMAND_FORMAT else document
    handler(inner)
    w._result_matches(cur, inner, result)
    if inner['work_kind'] == 'qualify': decision(cur, result['id'])


def execution(cur, request):
    cur.execute('SELECT * FROM corner.work_executions WHERE work_request_id=%s', (request['id'],))
    row = cur.fetchone()
    if row and row['status'] == 'completed':
        frozen = prepared(cur, request['id'])
        w._require(frozen is not None and frozen['id'] == row['prepared_command_id'], 'completion preparation mismatch')
        validate(cur, request, frozen['command_snapshot'])
        result_matches(cur, frozen['command_snapshot'], {'id': row[w.RESULTS[request['work_kind']][1]]})
    return row


def _prepare_static(conn, lease, settings):
    with ch._write(conn, 'corner_versioned_prepare') as cur:
        w._fence(cur, lease['work_request_id'], settings.owner, lease['lease_token'])
        request = w._request(cur, lease['work_request_id']); prior = prepared(cur, request['id'])
        if prior:
            validate(cur, request, prior['command_snapshot']); return
        intent = request['intent_snapshot']['intent']; kind = request['work_kind']
        expected = request_route(cur, request)
        selected = expected['handler']; domain_key = 'corner.versioned.worker:' + request['id']
        if kind == 'qualify':
            gen, family, _, _ = generation(cur, request['generation_id'], request['condition_id'])
            policy = qualifier(gen, family)
            cls = q1.QualificationCommand if selected == 'qualify.v1' else av.QualificationCommand
            command = cls(request['engine_evaluation_id'], policy, w._now(cur))
            if selected == 'qualify.v1': inner = w._serialize(kind, command, settings.authority, domain_key)
            else: inner = {'format': V2_DOMAIN_FORMAT, 'work_kind': kind, 'implementation': av.REVISION,
                'authority': asdict(settings.authority), 'domain_command_key': domain_key, 'payload': ev._encode(asdict(command))}
        elif kind == 'ensure_occurrence': inner = w._serialize(kind, request['qualification_decision_id'], None, None)
        elif kind == 'apply_lifecycle':
            command_kind = intent['command_kind']
            if command_kind != 'generation_activation':
                cur.execute('SELECT 1 FROM corner.lifecycle_applications WHERE condition_id=%s LIMIT 1', (request['condition_id'],))
                if not cur.fetchone(): raise runner.WaitingForPrerequisite('condition_uninitialized')
            adapter = {'lifecycle.v1': l1, 'lifecycle.v2': l2}[selected]
            command = adapter.ApplicationCommand(request['condition_id'], command_kind, request[l1._SOURCE_COLUMNS[command_kind]],
                request['generation_id'], w._now(cur) if command_kind in ('qualification', 'generation_activation') else None)
            inner = {'format': expected['command_format'], 'work_kind': kind, 'implementation': expected['implementation_revision'],
                'authority': asdict(settings.authority), 'domain_command_key': domain_key, 'payload': adapter._document(command)}
        else: raise runner.WaitingForPrerequisite('capture_adapter_required')
        doc = {'format': COMMAND_FORMAT, 'route': expected, 'command': inner}
        validate(cur, request, doc)
        cur.execute('INSERT INTO corner.prepared_work_commands(work_request_id,command_format_version,command_snapshot,command_sha256) VALUES (%s,%s,%s,%s)',
                    (request['id'], COMMAND_FORMAT, Json(doc), ev._digest(doc)))


def complete(conn, *, lease, settings):
    with ch._write(conn, 'corner_versioned_complete') as cur:
        w._fence(cur, lease['work_request_id'], settings.owner, lease['lease_token'])
        request = w._request(cur, lease['work_request_id']); frozen = prepared(cur, request['id'])
        w._require(frozen is not None, 'missing preparation')
        selected, doc = validate(cur, request, frozen['command_snapshot'])
        payload = doc['payload']; who = ch.ChannelAuthority(**doc['authority']) if doc['authority'] else None
        if selected == 'qualify.v2':
            p = payload['policy']
            command = av.QualificationCommand(payload['engine_evaluation_id'], av.ConditionalEVPolicy(p['version'], Decimal(p['minimum_ev_ratio']),
                p['expected_calculation_basis']), datetime.fromisoformat(payload['decided_at']), payload['context_json'])
            result = av.record_qualification(conn, authority=who, qualification_key=doc['domain_command_key'], command=command)
        elif selected == 'lifecycle.v2':
            command = l2.ApplicationCommand(payload['condition_id'], payload['kind'], payload['evidence_id'], payload['generation_id'],
                datetime.fromisoformat(payload['transition_at']) if payload['transition_at'] else None, ev.canonical_json(payload['context']))
            result = l2.apply_command(conn, authority=who, application_key=doc['domain_command_key'], command=command)
        elif selected == 'evaluate.v2':
            result = av.record_evaluation(conn, authority=who, evaluation_key=doc['domain_command_key'], command=av.deserialize_command(payload))
        elif selected == 'assess.v2':
            command = a2.AssessmentCommand(ev.canonical_json(payload['capture']), datetime.fromisoformat(payload['assessed_at']), ev.canonical_json(payload['context']))
            result = a2.record_assessment(conn, authority=who, assessment_key=doc['domain_command_key'], command=command)
        elif selected in ('evaluate.v1', 'qualify.v1', 'occurrence.v1', 'assess.v1', 'lifecycle.v1'):
            result = w._dispatch(conn, doc)
        else: raise w.WorkBlocked('uninstalled handler')
        result_matches(cur, frozen['command_snapshot'], result)
        column = w.RESULTS[request['work_kind']][1]
        cur.execute("UPDATE corner.work_executions SET status='completed',completed_at=clock_timestamp(),lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,prepared_command_id=%s,"+
            column+'=%s,updated_at=clock_timestamp() WHERE work_request_id=%s RETURNING *', (frozen['id'], result['id'], request['id']))
        return dict(cur.fetchone())


def run_once(connect, *, settings, request_id, source=None, evaluation_validator=None,
             should_stop=lambda: False, claim_observer=None):
    """One explicit request. No poller; frozen dispatch wins over current capture."""
    lease = None
    try:
        if should_stop(): return {'status': 'stopped', 'request_id': request_id}
        with runner._transaction(connect, settings) as conn:
            # Lock the exact candidate before inspecting its old status. This
            # makes reclaim telemetry a fact about the successful claim, not a
            # racing queue preview. Never wait behind another poller here.
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute('SELECT status FROM corner.work_executions WHERE work_request_id=%s FOR UPDATE SKIP LOCKED', (request_id,))
                prior = cur.fetchone()
            if prior and not should_stop():
                lease = w.claim(conn, owner=settings.owner, lease_for=settings.lease_for, request_id=request_id)
        if lease is None: return {'status': 'idle', 'request_id': request_id}
        if claim_observer is not None: claim_observer(prior['status'] == 'leased')
        with runner._transaction(connect, settings) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                w._fence(cur, request_id, settings.owner, lease['lease_token'])
                request = w._request(cur, request_id); frozen = prepared(cur, request_id)
                if frozen: validate(cur, request, frozen['command_snapshot'])
                kind = request['work_kind']; intent = request['intent_snapshot']['intent']
        if not frozen:
            # Leave the committed lease reclaimable; shutdown must not invent a
            # failure or capture a new command. Frozen work may drain normally.
            if should_stop(): return {'status': 'stopped', 'request_id': request_id}
            if kind == 'evaluate':
                selector = intent.get('selector', {})
                if selector.get('format') == e1.FORMAT and selector.get('revision') == e1.REVISION:
                    runner._prepare_evaluation(connect, lease, settings, evaluation_validator)
                elif selector.get('format') == e2.SELECTOR_FORMAT and selector.get('revision') == e2.REVISION:
                    e2.prepare_once(connect, lease=lease, settings=settings, source=source)
                else: raise w.WorkBlocked('missing/unsupported evaluation selector identity')
            elif kind == 'assess':
                if intent.get('format') == aw2.FORMAT and intent.get('revision') == a2.REVISION:
                    aw2.prepare_once(connect, lease=lease, settings=settings, source=source)
                else: raise w.WorkBlocked('missing/unsupported assessment capture identity; v1 requires frozen preparation')
            else:
                with runner._transaction(connect, settings) as conn: _prepare_static(conn, lease, settings)
        with runner._transaction(connect, settings) as conn: result = complete(conn, lease=lease, settings=settings)
        return {'status': 'completed', 'request_id': request_id, 'execution': result}
    except Exception as error:
        if lease is None: raise
        with runner._transaction(connect, settings) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                req = w._request(cur, request_id)
                existing = execution(cur, req)
                if existing and existing['status'] == 'completed':
                    return {'status': 'completed', 'request_id': request_id, 'execution': dict(existing)}
                try: owned = w._fence(cur, request_id, settings.owner, lease['lease_token'])
                except w.LeaseLost: return {'status': 'lease_lost', 'request_id': request_id}
                if isinstance(error, auth.UnmetPrerequisite): status, reason = 'waiting', str(error)
                else: status, reason = runner._classification(error, owned['retry_count'], settings)
                retry = w._now(cur) + settings.retry_delay if status == 'retryable' else None
            w.record_failure(conn, request_id=request_id, owner=settings.owner, token=lease['lease_token'], status=status,
                reason=reason, retry_at=retry, details_json=ev.canonical_json({'error_type': type(error).__name__}))
        return {'status': status, 'reason': reason, 'request_id': request_id}
