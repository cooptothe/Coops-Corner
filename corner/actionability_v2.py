"""Pure current authorization over a historical conditional-EV judgment.

No clock, SQL, source acquisition, EV recomputation or lifecycle side effects.
Valid negative evidence is a result. Unverifiable evidence is an exception.
"""
from dataclasses import asdict, replace
from datetime import datetime
import base64
import hashlib
from pathlib import Path

from corner import analytics_versions as analytics, assessments as v1
from corner import capture_authority as authority, evaluations as codec, lifecycle
from corner import market_validation as validation

FORMAT = 'corner.actionability/2'
CAPTURE_FORMAT = 'corner.actionability.capture/2'
BUILD = {'source': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
         'authority': authority.REVISION, 'analytics': analytics.REVISION,
         'quote_policy': hashlib.sha256(Path(lifecycle.__file__).read_bytes()).hexdigest(),
         'v1_assessment': v1.IMPLEMENTATION.revision}
IMPLEMENTATION = lifecycle.ImplementationIdentity('corner.actionability', '2', 'sha256:' + codec._digest(BUILD).hex())
REASONS = ('target_unavailable', 'target_stale', 'analytical_evidence_stale', 'analytical_evidence_changed',
           'unsupported_or_unknown_phase', 'approval_withdrawn', 'approval_expired_or_not_applicable',
           'settlement_authority_unknown', 'current_settlement_incompatible', 'analytical_conditioning_changed')
CLOSURE_REASONS = {r: ('unsupported_phase' if r == 'unsupported_or_unknown_phase' else r) for r in REASONS}
require = authority.require


def historical_basis(evaluation):
    """Reference the persisted full meaning, not a current generation substitute."""
    doc, result = evaluation['command_snapshot'], evaluation['result_snapshot']
    require(bytes(evaluation['command_sha256']) == codec._digest(doc)
            and bytes(evaluation['result_sha256']) == codec._digest(result), 'historical evaluation digest mismatch')
    decoded = analytics.decode_evaluation(evaluation)
    require(decoded.calculation_basis == analytics.v2.BASIS and evaluation['result_kind'] == 'evaluated',
            'assessment requires an evaluated conditional basis')
    command = analytics.deserialize_command(doc)
    return {'evaluation_id': evaluation['id'], 'command_sha256': bytes(evaluation['command_sha256']).hex(),
        'result_sha256': bytes(evaluation['result_sha256']).hex(), 'calculation_basis': decoded.calculation_basis,
        'fair_probability_basis': decoded.fair_probability_basis,
        'conditioning_contract': validation._json(command.configuration.settlement.conditioning_contract_json),
        'invalidation_behavior': validation._json(command.configuration.settlement.invalidation_behavior_json),
        'decisive_structure': command.configuration.settlement.decisive_structure,
        'push_behavior': command.configuration.settlement.push_behavior,
        'historical_settlement_assertions': codec._encode([asdict(s) for s in command.settlements])}


def _artifacts(catalog, policy, kind, scope):
    """A complete loader can establish absence. A mismatching digest is corruption."""
    refs = policy[kind + '_approval_references']
    found, missing = [], []
    for ref in refs:
        artifact = next((a for a in catalog['approvals'] if a['id'] == ref['id']), None)
        if artifact is None:
            missing.append(ref)
            continue
        # Reuse exact artifact integrity/scope validation, but not its positive-only gate.
        narrowed = dict(policy) | {kind + '_approval_references': [ref]}
        found.extend(authority._artifacts(catalog, narrowed, kind, scope))
    return found, missing


def _resolution(catalog, artifact, scope, policy, at, classification):
    start = validation._instant(artifact['effective_from'])
    end = validation._instant(artifact['effective_until']) if artifact['effective_until'] else None
    require(end is None or end > start, 'invalid approval interval')
    # Catalog availability is frozen at capture. Known future-effective withdrawal
    # can take effect before assessed_at, without looking up new knowledge.
    withdrawals = sorted((w for w in catalog['withdrawals'] if w['approval_id'] == artifact['id']
        and validation._instant(w['effective_at']) <= at), key=lambda w: (w['effective_at'], w['id']))
    reason = ('approval_withdrawn' if withdrawals else 'approval_expired_or_not_applicable'
        if at < start or (end is not None and at >= end) else 'assertion_class_not_authorized'
        if classification not in artifact['authorized_assertion_classes'] else 'authorized')
    return authority.envelope({'approval_artifact_id': artifact['id'], 'revision': artifact['revision'],
        'approval_digest': authority.digest(artifact), 'authorized_scope': artifact['authorized_scope'],
        'authorized_assertion_classes': artifact['authorized_assertion_classes'],
        'effective_from': artifact['effective_from'], 'effective_until': artifact['effective_until'],
        'withdrawal_state_at_capture': {'known_withdrawals': [w for w in catalog['withdrawals'] if w['approval_id'] == artifact['id']]},
        'withdrawals_effective_at_assessment': withdrawals, 'approval_policy': policy,
        'resolved_scope': scope, 'resolved_at': codec._encode(at), 'resolution_result': reason})


def authorization(capture, assessed_at):
    """Reproduce assertions AND negative authorization from retained inventories."""
    policy = authority.AuthorityPolicy(codec.canonical_json(capture['authority_policy'])).document
    require(policy['environment'] == 'synthetic', 'no production assessment authority installed')
    captured_at = validation._instant(capture['snapshot_captured_at'])
    require(assessed_at >= captured_at, 'assessment precedes capture')
    catalog = authority._catalog(capture['catalog'], captured_at)
    binding = capture['canonical_binding']
    basis = capture['historical_basis']
    expected = capture['expected_observations']
    books = sorted({q['sportsbook_id'] for q in expected})
    ids = capture['assertion_ids']
    require(set(ids) == {'phase', *books} and len(set(ids.values())) == len(ids), 'assertion coverage/identity mismatch')
    common = {'competition_id': binding['competition_id'], 'jurisdiction': policy['jurisdiction'],
              'offering': policy['offering'], 'event_id': binding['event_id']}
    scopes = {'phase': common | {'kind': 'phase'}} | {b: common | {'kind': 'settlement', 'sportsbook_id': b,
        'market_id': binding['market_id'], 'market_type': binding['market_type'], 'scope': binding['scope'],
        'outcome_ids': binding['outcome_ids']} for b in books}
    require(set(capture['inventories']) == set(scopes), 'missing/extra evidence inventory')
    results, terms, reasons, deadlines = {}, [], [], []
    for stream, scope in scopes.items():
        kind = scope['kind']
        artifacts, missing = _artifacts(catalog, policy, kind, scope)
        sources = {a['source_id'] for a in artifacts}
        if kind == 'phase':
            sources |= {s['authority'] for s in policy['phase_validation_policy']['sources']}
        inventory = authority.inventory(catalog, scope, sources, captured_at)
        require(codec.canonical_json(inventory) == codec.canonical_json(capture['inventories'][stream]),
                'incomplete or contradictory evidence manifest')
        records = authority._records(catalog, inventory)
        applicable_records = records
        if kind == 'phase':
            assertion, result = authority._phase(records, validation.EventBinding(binding['event_id'], binding['provider_identities']),
                                                 policy, assessed_at, ids[stream])
            if result['classification'] != 'supported_pregame': reasons.append('unsupported_or_unknown_phase')
            deadlines.append({'kind': 'phase', 'stream': stream, 'valid_until': result['valid_until'], 'end_inclusive': True})
        else:
            assertion, result = authority._settlement(records, scope, policy, assessed_at, ids[stream])
            # Rules applicability is checked at assessed_at, not acquisition start.
            applicable_records = []
            for record in records:
                doc = validation._json(base64.b64decode(record['content_base64'], validate=True))
                if (validation._instant(doc['effective_from']) <= assessed_at and
                    (doc['effective_until'] is None or assessed_at < validation._instant(doc['effective_until']))):
                    applicable_records.append(record)
                deadlines.append({'kind': 'rules', 'stream': stream, 'record_id': record['id'],
                    'valid_from': doc['effective_from'], 'valid_until': doc['effective_until'], 'end_inclusive': False})
            if result['classification'] != 'decisive_two_way': reasons.append('settlement_authority_unknown')
        negative = 'unsupported_or_unknown_phase' if kind == 'phase' else 'settlement_authority_unknown'
        receipts, valid = [], bool(artifacts and records and not missing and
                                      not authority.unpack(inventory)['missing_expected_records'])
        if not valid: reasons.append(negative)
        # Evaluate every relevant approval even when phase/rules is unknown; loss
        # of authority is itself independently observable negative evidence.
        active_grants = []
        for artifact in artifacts:
            receipt = _resolution(catalog, artifact, scope, policy[kind + '_approval_policy'], assessed_at,
                                  'supported_pregame' if kind == 'phase' else 'decisive_two_way')
            receipts.append(receipt)
            decision = authority.unpack(receipt)['resolution_result']
            deadlines.append({'kind': 'approval', 'stream': stream, 'approval_id': artifact['id'],
                'valid_from': artifact['effective_from'], 'valid_until': artifact['effective_until'], 'end_inclusive': False})
            if decision == 'authorized': active_grants.append(artifact)
        for record in applicable_records:
            matches = lambda a: (a['source_id'] == record['source_id'] and a['source_type'] == record['source_type']
                       and (kind == 'phase' or a['rules_sha256'] == record['content_sha256']))
            if not any(matches(a) for a in active_grants):
                valid = False
                rejected = [authority.unpack(r)['resolution_result'] for a, r in zip(artifacts, receipts) if matches(a)]
                reasons.extend(r if r in REASONS else negative for r in rejected)
                if not rejected: reasons.append(negative)
        if kind == 'settlement' and valid and result['classification'] == 'decisive_two_way':
            terms.append(result['terms'])
        results[stream] = {'inventory': inventory, 'assertion': assertion, 'approval_resolutions': receipts,
                           'missing_approval_references': missing}
    variants = {codec.canonical_json(t) for t in terms}
    if len(variants) > 1:
        reasons.append('current_settlement_incompatible')
    elif len(terms) == len(books):
        historical = {k: basis[k] for k in ('decisive_structure', 'push_behavior', 'conditioning_contract', 'invalidation_behavior')}
        if variants != {codec.canonical_json(historical)}:
            reasons.append('analytical_conditioning_changed')
    return {'streams': results, 'deadlines': deadlines, 'reasons': [r for r in REASONS if r in reasons]}


def assess(capture, assessed_at, qualification, policy):
    require(policy.identity == IMPLEMENTATION, 'unsupported actionability policy implementation')
    require(capture['capture_format_version'] == CAPTURE_FORMAT and capture['implementation'] == asdict(IMPLEMENTATION),
            'unsupported assessment capture format/revision')
    b = capture['bindings']
    require(capture['historical_basis']['evaluation_id'] == qualification.evaluation.order.evaluation_id
            and capture['historical_basis']['calculation_basis'] == analytics.v2.BASIS, 'historical calculation basis mismatch')
    expected = (qualification.evaluation.target,) + qualification.evaluation.contributing_references
    require(sorted(capture['expected_observations'], key=lambda q: q['observation_id']) ==
            sorted(codec._encode([asdict(q) for q in expected]), key=lambda q: q['observation_id']), 'analytical evidence mismatch')
    require(capture['canonical_binding']['event_id'] == qualification.evaluation.event_id, 'assessment event mismatch')
    slots = {(q.outcome_id, q.sportsbook_id): ('target' if q == qualification.evaluation.target else 'reference') for q in expected}
    streams = capture['streams']
    require(len(streams) == len(slots) and {(s['outcome_id'], s['sportsbook_id']) for s in streams} == set(slots),
            'incomplete/duplicate expected streams')
    for stream in streams:
        require(stream['stream_role'] == slots[(stream['outcome_id'], stream['sportsbook_id'])], 'wrong stream role')
        selected = stream['selection_kind'] == 'selected_trusted_observation'
        require(stream['selection_kind'] in ('selected_trusted_observation', 'missing_trusted_observation')
                and selected == (stream['quote'] is not None), 'invalid selection shape')
        if selected:
            quote = stream['quote']
            require((quote['outcome_id'], quote['sportsbook_id'], quote['market_id']) ==
                    (stream['outcome_id'], stream['sportsbook_id'], capture['canonical_binding']['market_id']),
                    'selected quote binding mismatch')
    authorization_result = authorization(capture, assessed_at)
    quotes = tuple(v1._quote(s['quote']) for s in capture['streams'] if s['quote'])
    request = lifecycle.AssessmentRequest('unpersisted-assessment', b['generation_id'], assessed_at,
        lifecycle.EvaluationOrder(datetime.fromisoformat(b['watermark_evaluated_at']), b['watermark_id']),
        b['qualification_id'], b['basis_assessment_id'], quotes,
        lifecycle.PhaseEvidence(capture['assertion_ids']['phase'], qualification.evaluation.event_id,
                                'pregame', 'phase checked separately by pinned v2 authority policy'))
    # Reuse unchanged quote identity/freshness semantics, not v1 authority meaning.
    base = lifecycle.assess_actionability(request, qualification, policy)
    reasons = [r for r in REASONS if r in set(base.reasons) | set(authorization_result['reasons'])]
    present = any(s['stream_role'] == 'target' and s['quote'] for s in capture['streams'])
    return {'snapshot_format_version': FORMAT, 'implementation': asdict(IMPLEMENTATION),
        'actionable': not reasons, 'primary_reason': reasons[0] if reasons else None, 'reasons': reasons,
        'target_deadline': codec._encode(base.target_deadline) if present else None,
        'evaluated_target_deadline': codec._encode(base.target_deadline),
        'reference_deadlines': [{'observation_id': oid, 'deadline': codec._encode(at)} for oid, at in sorted(base.reference_deadlines)],
        'quote_deadline_end_inclusive': True, 'authority': authorization_result,
        'historical_basis': capture['historical_basis']}


def closure_reason(format_version, reason):
    if format_version == v1.FORMAT_VERSION:
        require(reason in {'target_unavailable', 'target_stale', 'analytical_evidence_stale',
                           'analytical_evidence_changed', 'unsupported_phase'}, 'unsupported v1 actionability reason')
        return reason
    require(format_version == FORMAT and reason in CLOSURE_REASONS, 'unsupported assessment format/reason')
    return CLOSURE_REASONS[reason]


def process_assessment(state, fact):
    """Apply a validated, versioned fact. Never interpret an unknown boolean.

    Shared chronology, watermark/basis, episode projection and transition helpers
    retain v1 semantics. V2's authoritative reason set comes from its pure policy.
    """
    if fact.policy.identity == v1.IMPLEMENTATION:
        return lifecycle.process_assessment(state, fact.request)
    require(fact.policy.identity == IMPLEMENTATION and all(r in REASONS for r in fact.reasons),
            'unsupported assessment implementation/reasons')
    request = fact.request
    for prior, _ in state.assessments:
        if prior.request.id == request.id:
            if prior != fact: raise lifecycle.LifecycleConflict('assessment identity reused')
            return state
    generation = next((g for g in state.generations if g.id == request.generation_id), None)
    require(generation is not None and generation.actionability_policy == fact.policy, 'assessment generation policy mismatch')
    q = lifecycle._qualification(state, request.qualification_id)
    require(q == fact.qualification, 'assessment qualification mismatch')
    candidate = lifecycle._candidate(state)
    disposition = 'applicable'
    if not lifecycle._compatible(q, state.generation): disposition = 'incompatible_generation_or_policy'
    elif state.generation_activated_at is not None and request.assessed_at < state.generation_activated_at:
        disposition = 'assessment_predates_generation'
    elif request.watermark != state.watermark or request.basis_assessment_id != state.current_assessment_id:
        disposition = 'obsolete_binding'
    elif candidate is None or candidate.id != q.id: disposition = 'obsolete_analytical_evidence'
    elif state.current_assessment_id is not None:
        previous = next(a for a, _ in state.assessments if a.request.id == state.current_assessment_id)
        if fact.order <= previous.order: disposition = 'historical_assessment'
    result = replace(state, assessments=state.assessments + ((fact, disposition),))
    if disposition != 'applicable': return result
    result = replace(result, current_assessment_id=request.id)
    episode = result.open_episode
    if not fact.actionable:
        if episode:
            return lifecycle._transition(result, episode, 'closed', closure_reason(FORMAT, fact.reasons[0]),
                request.assessed_at, 'assessment', request.id)
        return result
    occurrence = lifecycle._occurrence(result, q.id)
    if episode is None:
        lifecycle._text(request.opening_episode_id)
        require(not any(e.id == request.opening_episode_id for e in result.episodes), 'episode identity reused')
        episode = lifecycle.Episode(request.opening_episode_id, generation.id, request.assessed_at, occurrence.id)
        return lifecycle._transition(result, episode, 'opened', 'qualified_current', request.assessed_at,
                                     'assessment', request.id, occurrence.id)
    if episode.current_occurrence_id != occurrence.id:
        return lifecycle._transition(result, episode, 'continued', 'qualified_current', request.assessed_at,
                                     'assessment', request.id, occurrence.id)
    return result
