"""Retained v2 authorization proof; synthetic loader only, no production grants.

The loader, not the work request, owns the evidence universe. A manifest proves
completeness relative to that retained universe, not authenticity of arbitrary
caller JSON. Only the explicitly synthetic loader is installed in this version.
No old validator, engine, generation, or frozen command is reinterpreted.
"""
from dataclasses import asdict, dataclass, replace
from datetime import timedelta
import base64
import hashlib
from pathlib import Path
from uuid import uuid4

from corner import analytics_versions as analytics, ev_conditional as conditional
from corner import evaluations as codec, ev, market_validation as validation

FORMAT = 'corner.capture.authorization/1'
RULES_FORMAT = 'corner.decisive_rules/1'
REVISION = 'sha256:' + codec._digest({
    'source': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'phase_validator': validation.VALIDATOR_REVISION,
    'analytics': analytics.REVISION,
}).hex()
LOADER = {'name': 'synthetic.complete-catalog', 'version': '1', 'revision': REVISION}


class ValidationFailure(ValueError):
    """Malformed/unverifiable evidence, never a domain non-evaluation."""


class UnmetPrerequisite(Exception):
    """No currently authorized supported command can be prepared."""


class IncompatibleConditions(Exception):
    """Approved rules define different conditional populations."""


def require(ok, message):
    if not ok:
        raise ValidationFailure(message)


def digest(value):
    return codec._digest(value).hex()


def envelope(value):
    return {'snapshot': value, 'sha256': digest(value)}


def unpack(value):
    require(isinstance(value, dict) and set(value) == {'snapshot', 'sha256'}
            and digest(value['snapshot']) == value['sha256'], 'retained envelope digest/shape mismatch')
    return value['snapshot']


def _identity(value):
    validation.PolicyIdentity(**value)
    return value


def phase_policy(value):
    return validation.PhasePolicy(validation.PolicyIdentity(**value['identity']), tuple(
        validation.PhaseSourceGrant(**(s | {
            'max_source_age': timedelta(microseconds=s['max_source_age']),
            'max_receipt_age': timedelta(microseconds=s['max_receipt_age'])})) for s in value['sources']))


@dataclass(frozen=True)
class AuthorityPolicy:
    """Canonical JSON is immutable; references are explicit, never global defaults."""
    snapshot_json: str

    @property
    def document(self):
        doc = validation._json(self.snapshot_json)
        require(set(doc) == {'phase_validation_policy', 'phase_validator_revision',
            'phase_approval_policy', 'phase_approval_references', 'settlement_validation_policy',
            'settlement_validator_revision', 'settlement_approval_policy', 'settlement_approval_references',
            'loader', 'jurisdiction', 'offering', 'environment'}, 'incomplete capture authority policy')
        require(doc['environment'] in ('synthetic', 'production'), 'unknown authority environment')
        require(doc['phase_validator_revision'] == validation.VALIDATOR_REVISION
                and doc['settlement_validator_revision'] == REVISION and doc['loader'] == LOADER,
                'unsupported pinned validator/loader')
        doc['phase_validation_policy'] = validation._encode(phase_policy(doc['phase_validation_policy']))
        for name in ('settlement_validation_policy', 'phase_approval_policy', 'settlement_approval_policy'):
            _identity(doc[name])
        for kind in ('phase', 'settlement'):
            refs = doc[kind + '_approval_references']
            require(isinstance(refs, list), 'approval references must be explicit')
            require(len({r['id'] for r in refs}) == len(refs), 'duplicate approval reference')
            for ref in refs:
                require(set(ref) == {'id', 'revision', 'sha256'}, 'invalid approval reference')
                validation._id(ref['id']); validation._text(ref['revision'])
                require(len(ref['sha256']) == 64 and all(x in '0123456789abcdef' for x in ref['sha256']),
                        'invalid approval digest')
            doc[kind + '_approval_references'] = sorted(refs, key=lambda r: r['id'])
        validation._text(doc['jurisdiction']); validation._text(doc['offering'])
        return doc

    def __post_init__(self):
        object.__setattr__(self, 'snapshot_json', codec.canonical_json(self.document))


@dataclass(frozen=True)
class SyntheticEvidenceStore:
    """Test-only trusted fixture repository; cannot authorize production.

    The repository snapshot includes the entire catalog, not a caller-selected
    response subset. Replacement represents new evidence/withdrawal, not mutation
    of already frozen evidence. Production will need an authenticated loader and
    independently reviewed universe/approval policy; neither is installed here.
    """
    catalog_json: str

    def capture(self, at):
        doc = validation._json(self.catalog_json)
        require(doc.get('environment') == 'synthetic' and doc.get('loader') == LOADER,
                'unrecognized synthetic repository')
        for collection in ('records', 'approvals', 'withdrawals'):
            doc[collection] = sorted(doc[collection], key=lambda item: item['id'])
        return envelope(doc | {'captured_at': codec._encode(at)})


def _catalog(bundle, at):
    catalog = unpack(bundle)
    require(set(catalog) == {'environment', 'loader', 'captured_at', 'records', 'approvals', 'withdrawals'},
            'invalid complete catalog shape')
    require(catalog['environment'] == 'synthetic' and catalog['loader'] == LOADER,
            'no production loader/approval authority installed')
    require(catalog['captured_at'] == codec._encode(at), 'inventory capture time mismatch')
    for collection in ('records', 'approvals', 'withdrawals'):
        require(len({r['id'] for r in catalog[collection]}) == len(catalog[collection]), 'duplicate catalog identity')
    for record in catalog['records']:
        require(set(record) == {'id', 'source_id', 'source_type', 'source_revision', 'scope', 'received_at',
                                'content_base64', 'content_sha256', 'adverse', 'locator'}, 'invalid evidence record')
        validation._id(record['id'])
        for name in ('source_id', 'source_type', 'source_revision', 'locator'):
            validation._text(record[name])
        require(type(record['adverse']) is bool, 'explicit adverse marker required')
        raw = base64.b64decode(record['content_base64'], validate=True)
        require(hashlib.sha256(raw).hexdigest() == record['content_sha256'], 'retained evidence digest mismatch')
        require(validation._instant(record['received_at']) <= at, 'catalog contains future receipt evidence')
    for withdrawal in catalog['withdrawals']:
        require(set(withdrawal) == {'id', 'approval_id', 'effective_at', 'recorded_at', 'reason'},
                'invalid withdrawal record')
        validation._id(withdrawal['id']); validation._id(withdrawal['approval_id'])
        validation._text(withdrawal['reason'])
        validation._instant(withdrawal['effective_at'])
        require(validation._instant(withdrawal['recorded_at']) <= at, 'catalog contains future withdrawal knowledge')
    return catalog


def inventory(catalog, scope, expected_sources, at):
    """Exhaustive scope match over the loader snapshot, INCLUDING adverse records.

    No latest-row/positive-only filtering. Revision conflicts remain evidence.
    The validated catalog rejects future receipts before inventory construction.
    """
    records = sorted((r for r in catalog['records'] if r['scope'] == scope
                      and validation._instant(r['received_at']) <= at), key=lambda r: r['id'])
    missing = sorted(set(expected_sources) - {r['source_id'] for r in records})
    return envelope({'loader': LOADER, 'scope_queried': scope,
        'source_revisions_considered': sorted({(r['source_id'], r['source_revision']) for r in records}),
        'records_retained': [r['id'] for r in records], 'missing_expected_records': missing,
        'conflicting_adverse_records': [r['id'] for r in records if r['adverse']],
        'inventory_captured_at': codec._encode(at), 'catalog_sha256': digest(catalog)})


def _artifacts(catalog, policy, kind, scope):
    refs = policy[kind + '_approval_references']
    found = []
    for ref in refs:
        artifact = next((a for a in catalog['approvals'] if a['id'] == ref['id']), None)
        if artifact is None:
            raise UnmetPrerequisite('missing_approval_artifact')
        require(digest(artifact) == ref['sha256'] and artifact['revision'] == ref['revision'],
                'approval revision/digest mismatch')
        require(set(artifact) == {'id', 'revision', 'environment', 'kind', 'authorized_scope',
            'authorized_assertion_classes', 'effective_from', 'effective_until', 'source_id', 'source_type',
            'rules_sha256'}, 'invalid approval artifact')
        require(artifact['environment'] == 'synthetic' and artifact['kind'] == kind,
                'unapproved authority environment/kind')
        required = {'competition_id', 'jurisdiction', 'offering'} | (
            {'sportsbook_id', 'market_type', 'scope'} if kind == 'settlement' else set())
        require(required <= artifact['authorized_scope'].keys(), 'approval scope is underspecified')
        # Policy can contain grants for other books, but no guessed jurisdiction.
        if all(scope.get(k) == v for k, v in artifact['authorized_scope'].items()):
            found.append(artifact)
    return found


def resolve_approval(catalog, artifact, scope, classification, policy, at):
    start = validation._instant(artifact['effective_from'])
    end = validation._instant(artifact['effective_until']) if artifact['effective_until'] else None
    require(end is None or end > start, 'invalid approval interval')
    withdrawal = sorted((w for w in catalog['withdrawals'] if w['approval_id'] == artifact['id']
        and validation._instant(w['recorded_at']) <= at and validation._instant(w['effective_at']) <= at),
        key=lambda w: (w['effective_at'], w['id']))
    reason = ('approval_withdrawn' if withdrawal else 'approval_not_effective' if at < start or
        (end is not None and at >= end) else 'assertion_class_not_authorized' if classification not in
        artifact['authorized_assertion_classes'] else 'authorized')
    receipt = envelope({'approval_artifact_id': artifact['id'], 'revision': artifact['revision'],
        'approval_digest': digest(artifact), 'authorized_scope': artifact['authorized_scope'],
        'authorized_assertion_classes': artifact['authorized_assertion_classes'],
        'effective_from': artifact['effective_from'], 'effective_until': artifact['effective_until'],
        'withdrawal_state_at_capture': {'withdrawn': bool(withdrawal), 'evidence': withdrawal},
        'approval_policy': policy, 'approval_policy_revision': policy['revision'],
        'resolved_scope': scope, 'resolved_at': codec._encode(at), 'resolution_result': reason})
    if reason != 'authorized':
        raise UnmetPrerequisite(reason)
    return receipt


def _records(catalog, manifest):
    ids = set(unpack(manifest)['records_retained'])
    return sorted((r for r in catalog['records'] if r['id'] in ids), key=lambda r: r['id'])


def _phase(records, event, policy, at, assertion_id):
    evidence = tuple(validation.RetainedEvidence(r['id'], r['source_id'], r['source_type'],
        base64.b64decode(r['content_base64'], validate=True), r['content_sha256'],
        validation._instant(r['received_at']), r['locator']) for r in records)
    assertion = validation.validate_phase(assertion_id=assertion_id, event=event,
        policy=phase_policy(policy['phase_validation_policy']), evidence=evidence, asserted_at=at)
    return envelope(asdict(assertion)), assertion.result


def _settlement(records, scope, policy, at, assertion_id):
    """New descriptive conditional rules format. Never relabel v1 assertions."""
    accepted = []
    for record in records:
        doc = validation._json(base64.b64decode(record['content_base64'], validate=True))
        require(set(doc) == {'format', 'binding', 'rules_revision', 'effective_from', 'effective_until',
            'decisive_structure', 'push_behavior', 'conditioning_contract', 'invalidation_behavior'},
            'malformed conditional rules')
        require(doc['format'] == RULES_FORMAT and doc['binding'] == scope, 'rules format/scope mismatch')
        require(doc['rules_revision'] == record['source_revision'], 'rules revision mismatch')
        conditional.object_json(codec.canonical_json(doc['conditioning_contract']))
        conditional.object_json(codec.canonical_json(doc['invalidation_behavior']))
        require(doc['decisive_structure'] in ('two_way', 'three_way', 'quarter_line', 'unknown')
                and doc['push_behavior'] in ('absent', 'possible', 'split', 'unknown'), 'unknown rules vocabulary')
        if doc['decisive_structure'] == 'two_way':
            require(len(scope['outcome_ids']) == 2, 'two-way assertion contradicts canonical outcome structure')
        start = validation._instant(doc['effective_from'])
        end = validation._instant(doc['effective_until']) if doc['effective_until'] else None
        require(end is None or end > start, 'invalid rules interval')
        if start <= at and (end is None or at < end):
            accepted.append(doc)
    terms = [{k: d[k] for k in ('decisive_structure', 'push_behavior', 'conditioning_contract', 'invalidation_behavior')}
             for d in accepted]
    variants = {codec.canonical_json(t) for t in terms}
    chosen = terms[0] if len(variants) == 1 else None
    classification = ('decisive_two_way' if chosen and chosen['decisive_structure'] == 'two_way'
                      and chosen['push_behavior'] == 'absent' else 'unknown')
    command = envelope({'format': RULES_FORMAT, 'assertion_id': assertion_id, 'scope': scope,
        'validator_revision': REVISION, 'policy': policy['settlement_validation_policy'],
        'evidence': records, 'asserted_at': codec._encode(at)})
    result = {'assertion_id': assertion_id, 'classification': classification,
        'reason': 'conflicting_rules' if len(variants) > 1 else 'explicit_rules' if chosen else 'insufficient_rules',
        'terms': chosen, 'command_sha256': command['sha256'],
        'rules_revisions': sorted(d['rules_revision'] for d in accepted)}
    return envelope({'command': command, 'result': envelope(result)}), result


def _participating(snapshot, config):
    # Reuse the pinned engine's coverage/eligibility policy, NOT capture heuristics.
    # No result is persisted; no prices are removed to obtain a passing population.
    probe = ev.evaluate_ev(replace(snapshot, event_phase='pregame', phase_evidence='authorization probe',
        contract=replace(snapshot.contract, settlement_policy='two_way_no_push',
                         settlement_evidence='authorization probe')), config.pricing)
    target = next(q for q in snapshot.quotes if q.observation_id == snapshot.target_observation_id)
    excluded = {r.sportsbook_id for r in probe.reference_exclusions}
    # If the kernel short-circuits before establishing exclusions, require authority
    # for every configured candidate. Never infer nonparticipation from missing grants.
    return sorted({target.sportsbook_id} | (set(config.pricing.reference_sportsbook_ids) - excluded))


def authorize(snapshot, config, policy, binding, catalog_bundle, *, assertion_ids=None):
    """Pure proof assembly/replay. No I/O, no production authorization installed."""
    policy = policy.document
    if policy['environment'] != 'synthetic':
        raise UnmetPrerequisite('production_authority_not_installed')
    at = snapshot.evaluated_at
    catalog = _catalog(catalog_bundle, at)
    require(binding['market_id'] == snapshot.contract.market_id and binding['competition_id'] == config.pricing.competition_id
            and binding['market_type'] == snapshot.contract.market_type and binding['scope'] == snapshot.contract.scope
            and binding['outcome_ids'] == sorted(o.outcome_id for o in snapshot.contract.outcomes), 'canonical binding mismatch')
    required = _participating(snapshot, config)
    candidates = sorted({q.sportsbook_id for q in snapshot.quotes} | set(config.pricing.reference_sportsbook_ids))
    ids = assertion_ids if assertion_ids is not None else {'phase': str(uuid4()),
        **{b: str(uuid4()) for b in candidates}}
    require(set(ids) == {'phase', *candidates}, 'assertion identities do not cover exact candidate streams')
    for identity in ids.values():
        validation._id(identity)
    require(len(set(ids.values())) == len(ids), 'duplicate assertion identity')
    common = {'competition_id': binding['competition_id'], 'jurisdiction': policy['jurisdiction'],
              'offering': policy['offering'], 'event_id': binding['event_id']}
    scopes = {'phase': common | {'kind': 'phase'}} | {b: common | {
        'kind': 'settlement', 'sportsbook_id': b, 'market_id': binding['market_id'],
        'market_type': binding['market_type'], 'scope': binding['scope'], 'outcome_ids': binding['outcome_ids']}
        for b in candidates}
    bundles, settlements = {}, []
    for stream, scope in scopes.items():
        kind = scope['kind']
        artifacts = _artifacts(catalog, policy, kind, scope)
        expected_sources = {a['source_id'] for a in artifacts}
        if kind == 'phase':
            expected_sources |= {s['authority'] for s in policy['phase_validation_policy']['sources']}
        manifest = inventory(catalog, scope, expected_sources, at)
        records = _records(catalog, manifest)
        if kind == 'phase':
            assertion, result = _phase(records, validation.EventBinding(binding['event_id'],
                binding['provider_identities']), policy, at, ids[stream])
        else:
            assertion, result = _settlement(records, scope, policy, at, ids[stream])
        # All candidate assertions/inventories are retained, even excluded books.
        resolutions = []
        needed = stream == 'phase' or stream in required
        if needed:
            if not artifacts or unpack(manifest)['missing_expected_records']:
                raise UnmetPrerequisite('missing_approved_authority_or_evidence')
            wanted = 'supported_pregame' if kind == 'phase' else 'decisive_two_way'
            if result['classification'] != wanted:
                raise UnmetPrerequisite('unsupported_or_unknown_' + kind)
            # Every applicable record needs an explicit grant, including adverse
            # records. A conveniently omitted revision cannot disappear here.
            for record in records:
                matching = [a for a in artifacts if (a['source_id'], a['source_type']) ==
                    (record['source_id'], record['source_type']) and
                    (kind == 'phase' or a['rules_sha256'] == record['content_sha256'])]
                if not matching:
                    raise UnmetPrerequisite('unapproved_evidence_revision')
                resolutions.extend(resolve_approval(catalog, a, scope, wanted, policy[kind + '_approval_policy'], at)
                                   for a in matching)
            if kind == 'settlement':
                terms = result['terms']
                pinned = config.settlement
                if (terms['decisive_structure'], terms['push_behavior'],
                    codec.canonical_json(terms['conditioning_contract']), codec.canonical_json(terms['invalidation_behavior'])) != (
                        'two_way', 'absent', pinned.conditioning_contract_json, pinned.invalidation_behavior_json):
                    raise IncompatibleConditions('incompatible_decisive_settlement_conditions')
                settlements.append(conditional.SettlementEvidence(stream, binding['market_id'], binding['outcome_ids'],
                    ids[stream], assertion['sha256'], pinned.revision, pinned.conditioning_contract_json,
                    pinned.invalidation_behavior_json))
        bundles[stream] = {'inventory': manifest, 'assertion': assertion,
            'approval_resolutions': resolutions, 'required_by_engine': needed}
    proof = {'format': FORMAT, 'revision': REVISION, 'policy': policy, 'binding': binding,
        'captured_at': codec._encode(at), 'catalog': catalog_bundle, 'assertion_ids': ids,
        'streams': bundles, 'required_books': required}
    frozen = replace(snapshot, event_phase='pregame', phase_evidence='assertion:' + ids['phase'],
        contract=replace(snapshot.contract, settlement_policy='decisive_two_way',
                         settlement_evidence='capture:' + digest(proof)))
    return conditional.EvaluationCommand(frozen, config, tuple(settlements),
        codec.canonical_json({'capture_authorization': envelope(proof)}))


def verify(command):
    """Reproduce complete envelopes offline, NEVER read current approval state."""
    try:
        context = validation._json(command.context_json)
        require(set(context) == {'capture_authorization'}, 'missing authorization envelope')
        proof = unpack(context['capture_authorization'])
        require(proof['format'] == FORMAT and proof['revision'] == REVISION, 'unsupported capture format/revision')
        expected = authorize(command.snapshot, command.configuration, AuthorityPolicy(codec.canonical_json(proof['policy'])),
            proof['binding'], proof['catalog'], assertion_ids=proof['assertion_ids'])
        require(analytics.serialize_command(expected) == analytics.serialize_command(command),
                'incomplete inventory or contradictory authorization envelope')
        return proof
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValidationFailure('malformed authorization envelope') from exc
