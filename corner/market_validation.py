"""Pure evidence-policy proof. No DB, clock reads, provider calls or capture wiring.

Evidence envelopes and policies come from trusted loaders/configuration, not an
untrusted request. A digest proves byte integrity, NOT authenticity. The two input
formats below are Corner evidence contracts, not The Odds API response formats.
No production source is approved by this module.
"""
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import json
from pathlib import Path
from uuid import UUID


FORMAT = 'corner.market_validation/1'
PHASE_FORMAT = 'corner.explicit_phase_evidence/1'
RULES_FORMAT = 'corner.settlement_rules_evidence/1'
VALIDATOR_VERSION = '1.0.0'
VALIDATOR_REVISION = 'sha256:' + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
PHASES = {'supported_pregame', 'unsupported_live', 'unsupported_completed', 'unknown'}


class ValidationError(ValueError):
    """Unverifiable/malformed input, not a successful unknown judgment."""


def _require(condition, message):
    if not condition:
        raise ValidationError(message)


def _text(value):
    _require(isinstance(value, str) and bool(value.strip()), 'nonblank text required')
    return value


def _id(value):
    try:
        return str(UUID(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValidationError('canonical UUID required') from exc


def _time(value):
    _require(isinstance(value, datetime) and value.tzinfo is not None
             and value.utcoffset() is not None, 'aware timestamp required')
    return value.astimezone(timezone.utc)


def _instant(value):
    try:
        return _time(datetime.fromisoformat(value.replace('Z', '+00:00')))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValidationError('invalid source timestamp') from exc


def _encode(value):
    if is_dataclass(value):
        return _encode(asdict(value))
    if isinstance(value, datetime):
        return _time(value).isoformat(timespec='microseconds').replace('+00:00', 'Z')
    if isinstance(value, timedelta):
        return (value.days * 86400 + value.seconds) * 1_000_000 + value.microseconds
    if isinstance(value, bytes):
        return {'base64': base64.b64encode(value).decode('ascii')}
    if isinstance(value, (tuple, list)):
        return [_encode(x) for x in value]
    if isinstance(value, dict):
        _require(all(isinstance(k, str) for k in value), 'string JSON keys required')
        return {k: _encode(v) for k, v in value.items()}
    if value is None or isinstance(value, (str, bool, int)):
        return value
    raise ValidationError('unsupported canonical value')


def canonical(value):
    return json.dumps(_encode(value), sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False)


def sha256(content):
    return hashlib.sha256(content).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def _json(content):
    try:
        result = json.loads(content, object_pairs_hook=_pairs,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValidationError('nonfinite JSON')))
    except (ValueError, UnicodeError, TypeError) as exc:
        raise ValidationError('invalid retained JSON') from exc
    _require(isinstance(result, dict), 'JSON object required')
    return result


@dataclass(frozen=True)
class PolicyIdentity:
    name: str
    version: str
    revision: str

    def __post_init__(self):
        for value in (self.name, self.version, self.revision):
            _text(value)


@dataclass(frozen=True)
class RetainedEvidence:
    id: str
    authority: str
    source_type: str
    content: bytes
    content_sha256: str
    received_at: datetime
    locator: str

    def __post_init__(self):
        object.__setattr__(self, 'id', _id(self.id))
        for value in (self.authority, self.source_type, self.locator):
            _text(value)
        _require(type(self.content) is bytes, 'immutable retained bytes required')
        _require(sha256(self.content) == self.content_sha256, 'payload digest mismatch')
        _time(self.received_at)


@dataclass(frozen=True)
class EventBinding:
    event_id: str
    # Established provider mappings, supplied by a trusted identity loader.
    provider_identities: tuple[tuple[str, str], ...]

    def __post_init__(self):
        object.__setattr__(self, 'event_id', _id(self.event_id))
        pairs = tuple(sorted((_id(provider), _text(external)) for provider, external in self.provider_identities))
        _require(len({p for p, _ in pairs}) == len(pairs), 'ambiguous provider event binding')
        object.__setattr__(self, 'provider_identities', pairs)


@dataclass(frozen=True)
class PhaseSourceGrant:
    authority: str
    source_type: str
    provider_id: str
    status_mapping: tuple[tuple[str, str], ...]
    max_source_age: timedelta
    max_receipt_age: timedelta

    def __post_init__(self):
        _text(self.authority)
        _text(self.source_type)
        object.__setattr__(self, 'provider_id', _id(self.provider_id))
        mapping = tuple(sorted((_text(k), _text(v)) for k, v in self.status_mapping))
        _require(len(dict(mapping)) == len(mapping) and all(v in PHASES for _, v in mapping),
                 'invalid phase status mapping')
        object.__setattr__(self, 'status_mapping', mapping)
        for value in (self.max_source_age, self.max_receipt_age):
            _require(isinstance(value, timedelta) and value > timedelta(0), 'positive phase age limits required')


@dataclass(frozen=True)
class PhasePolicy:
    identity: PolicyIdentity
    sources: tuple[PhaseSourceGrant, ...]

    def __post_init__(self):
        _require(isinstance(self.identity, PolicyIdentity), 'phase policy identity required')
        sources = tuple(self.sources)
        _require(all(isinstance(s, PhaseSourceGrant) for s in sources), 'phase grants required')
        sources = tuple(sorted(sources, key=lambda x: (x.authority, x.source_type, x.provider_id)))
        _require(len({(s.authority, s.source_type, s.provider_id) for s in sources}) == len(sources),
                 'duplicate phase authority')
        object.__setattr__(self, 'sources', sources)


@dataclass(frozen=True)
class ContractBinding:
    event_id: str
    market_id: str
    competition_id: str
    market_type: str
    scope: str
    # Complete canonical settlement selection mapping, NOT the observed quotes.
    outcomes: tuple[tuple[str, str], ...]

    def __post_init__(self):
        for name in ('event_id', 'market_id', 'competition_id'):
            object.__setattr__(self, name, _id(getattr(self, name)))
        _text(self.market_type)
        _text(self.scope)
        outcomes = tuple(sorted((_id(identifier), _text(label)) for identifier, label in self.outcomes))
        _require(bool(outcomes) and len({i for i, _ in outcomes}) == len(outcomes)
                 and len({label for _, label in outcomes}) == len(outcomes), 'invalid contract outcomes')
        object.__setattr__(self, 'outcomes', outcomes)


@dataclass(frozen=True)
class SettlementSourceGrant:
    authority: str
    source_type: str
    rules_sha256: str
    sportsbook_id: str
    competition_id: str
    market_type: str
    scope: str

    def __post_init__(self):
        for name in ('authority', 'source_type', 'market_type', 'scope'):
            _text(getattr(self, name))
        for name in ('sportsbook_id', 'competition_id'):
            object.__setattr__(self, name, _id(getattr(self, name)))
        _require(isinstance(self.rules_sha256, str) and len(self.rules_sha256) == 64
                 and all(c in '0123456789abcdef' for c in self.rules_sha256), 'rules digest required')


@dataclass(frozen=True)
class SettlementPolicy:
    identity: PolicyIdentity
    sources: tuple[SettlementSourceGrant, ...]

    def __post_init__(self):
        _require(isinstance(self.identity, PolicyIdentity), 'settlement policy identity required')
        sources = tuple(self.sources)
        _require(all(isinstance(s, SettlementSourceGrant) for s in sources), 'settlement grants required')
        sources = tuple(sorted(sources, key=canonical))
        _require(len(set(sources)) == len(sources), 'duplicate settlement authority')
        object.__setattr__(self, 'sources', sources)


@dataclass(frozen=True)
class ValidationAssertion:
    """Immutable value, not a persisted ledger row. IDs supplied by the caller.

    JSON text avoids mutable dict/list children. Digests are not record identity.
    No created_at: persistence/identity registration is deliberately deferred.
    """
    command_snapshot: str
    result_snapshot: str
    command_sha256: str
    result_sha256: str

    @property
    def result(self):
        _require(isinstance(self.command_snapshot, str) and isinstance(self.result_snapshot, str),
                 'serialized assertion snapshots required')
        _require(sha256(self.command_snapshot.encode()) == self.command_sha256
                 and sha256(self.result_snapshot.encode()) == self.result_sha256,
                 'assertion digest mismatch')
        command, result = _json(self.command_snapshot), _json(self.result_snapshot)
        _require(command.get('format') == FORMAT and result.get('format') == FORMAT,
                 'unsupported assertion format')
        _require(result.get('command_sha256') == self.command_sha256
                 and result.get('assertion_id') == command.get('assertion_id')
                 and result.get('kind') == command.get('kind'), 'assertion command/result mismatch')
        _verify_assertion(self, command)
        return result

    @property
    def reference(self):
        return (self.result['assertion_id'], self.result_sha256)


def _inputs(evidence, at):
    at = _time(at)
    evidence = tuple(evidence)
    _require(all(isinstance(e, RetainedEvidence) for e in evidence), 'retained evidence required')
    evidence = tuple(sorted(evidence, key=lambda e: e.id))
    _require(len({e.id for e in evidence}) == len(evidence), 'duplicate evidence identity')
    for item in evidence:
        _require(isinstance(item, RetainedEvidence), 'retained evidence required')
        _require(item.received_at <= at, 'evidence was not available at assertion time')
        _require(sha256(item.content) == item.content_sha256, 'payload digest mismatch')
    return evidence, at


def _assertion(identifier, kind, subject, policy, evidence, at, classification, reason,
               diagnostics, valid_from=None, valid_until=None, terms=None):
    command = canonical(dict(format=FORMAT, assertion_id=_id(identifier), kind=kind,
                             subject=subject, policy=policy, evidence=evidence, asserted_at=at,
                             validator_version=VALIDATOR_VERSION, validator_revision=VALIDATOR_REVISION))
    digest = sha256(command.encode())
    result = canonical(dict(format=FORMAT, assertion_id=_id(identifier), kind=kind,
                            command_sha256=digest, subject=subject, asserted_at=at,
                            classification=classification, reason=reason, diagnostics=diagnostics,
                            valid_from=valid_from, valid_until=valid_until, terms=terms))
    return ValidationAssertion(command, result, digest, sha256(result.encode()))


def _verify_assertion(assertion, command):
    """Reproduce supplied assertions, not just their hashes, without any I/O.

    This validates internal consistency, NOT source authentication or policy
    approval. Those remain trusted-loader responsibilities. Historical builds
    require their own supported decoder/validator; never reinterpret them here.
    """
    _require(command.get('validator_version') == VALIDATOR_VERSION
             and command.get('validator_revision') == VALIDATOR_REVISION,
             'unsupported validator implementation')
    try:
        evidence = tuple(RetainedEvidence(**(item | {
            'content': base64.b64decode(item['content']['base64'], validate=True),
            'received_at': _instant(item['received_at'])})) for item in command['evidence'])
        policy = command['policy']
        identity = PolicyIdentity(**policy['identity'])
        common = dict(assertion_id=command['assertion_id'], evidence=evidence,
                      asserted_at=_instant(command['asserted_at']))
        if command['kind'] == 'phase':
            sources = []
            for source in policy['sources']:
                for field in ('max_source_age', 'max_receipt_age'):
                    _require(type(source[field]) is int, 'integer age microseconds required')
                sources.append(PhaseSourceGrant(**(source | {
                    'max_source_age': timedelta(microseconds=source['max_source_age']),
                    'max_receipt_age': timedelta(microseconds=source['max_receipt_age'])})))
            expected = validate_phase(event=EventBinding(**command['subject']),
                                      policy=PhasePolicy(identity, sources), **common)
        elif command['kind'] == 'settlement':
            expected = validate_settlement(
                contract=ContractBinding(**command['subject']['contract']),
                sportsbook_id=command['subject']['sportsbook_id'],
                policy=SettlementPolicy(identity, tuple(SettlementSourceGrant(**s) for s in policy['sources'])),
                **common)
        else:
            raise ValidationError('unsupported assertion kind')
        _require(expected == assertion, 'assertion does not reproduce from retained command')
    except (KeyError, TypeError, AttributeError, ValueError, OverflowError) as exc:
        raise ValidationError('invalid or non-reproducible assertion') from exc


def validate_phase(*, assertion_id, event, policy, evidence, asserted_at):
    _require(isinstance(event, EventBinding) and isinstance(policy, PhasePolicy), 'phase inputs required')
    evidence, at = _inputs(evidence, asserted_at)
    accepted, diagnostics = [], []
    for item in evidence:
        doc = _json(item.content)
        _require(doc.get('format') == PHASE_FORMAT, 'unsupported phase evidence format')
        provider = _id(doc.get('provider_id'))
        external = _text(doc.get('external_event_id'))
        _require(dict(event.provider_identities).get(provider) == external, 'wrong event/provider binding')
        status = _text(doc.get('status'))
        source_at = _instant(doc.get('source_asserted_at'))
        _require(source_at <= item.received_at, 'source assertion postdates receipt')
        grant = next((s for s in policy.sources if (s.authority, s.source_type, s.provider_id)
                      == (item.authority, item.source_type, provider)), None)
        if grant is None:
            diagnostics.append((item.id, 'unapproved_source'))
            continue
        deadline = min(source_at + grant.max_source_age, item.received_at + grant.max_receipt_age)
        if at > deadline:
            diagnostics.append((item.id, 'expired_evidence'))
            continue
        phase = dict(grant.status_mapping).get(status, 'unknown')
        accepted.append((phase, deadline))
        diagnostics.append((item.id, 'admissible' if phase != 'unknown' else 'unmapped_or_unknown_status'))
    phases = {phase for phase, _ in accepted}
    if len(phases) > 1:
        classification, reason = 'unknown', 'conflicting_phase_evidence'
    elif not phases or phases == {'unknown'}:
        classification, reason = 'unknown', 'insufficient_phase_authority'
    else:
        classification, reason = next(iter(phases)), 'explicit_phase_evidence'
    return _assertion(assertion_id, 'phase', event, policy, evidence, at, classification, reason,
                      diagnostics, at, min((d for _, d in accepted), default=None))


def _terms(value):
    keys = {'structure', 'outcome_labels', 'overtime', 'tie', 'push', 'refund_rule', 'void_rule'}
    _require(isinstance(value, dict) and set(value) == keys, 'complete settlement terms required')
    labels = value['outcome_labels']
    _require(isinstance(labels, list) and all(isinstance(x, str) and x.strip() for x in labels)
             and len(labels) == len(set(labels)), 'distinct settlement labels required')
    _require(value['overtime'] in ('included', 'excluded', 'not_applicable'), 'unknown overtime semantics')
    _require(value['tie'] in ('impossible', 'draw_selection', 'refund', 'loss'), 'unknown tie semantics')
    _require(value['push'] in ('impossible', 'refund', 'split'), 'unknown push semantics')
    _text(value['refund_rule'])
    _text(value['void_rule'])
    structure = value['structure']
    if structure == 'two_way':
        _require(len(labels) == 2 and value['tie'] != 'draw_selection' and value['push'] != 'split',
                 'contradictory two-way rules')
        # A tie settled as a loss on both sides is not an exhaustive binary contract.
        classification = ('no_push_two_way' if value['tie'] == value['push'] == 'impossible'
                          else 'push_capable' if 'refund' in (value['tie'], value['push']) else 'unknown')
    elif structure == 'three_way':
        _require(len(labels) == 3 and value['tie'] == 'draw_selection' and value['push'] == 'impossible',
                 'contradictory three-way rules')
        classification = 'three_way'
    elif structure == 'quarter_line':
        _require(len(labels) == 2 and value['push'] == 'split', 'contradictory quarter-line rules')
        classification = 'quarter_line'
    else:
        raise ValidationError('unsupported rules structure format')
    return value | {'outcome_labels': sorted(labels)}, classification


def validate_settlement(*, assertion_id, contract, sportsbook_id, policy, evidence, asserted_at):
    _require(isinstance(contract, ContractBinding) and isinstance(policy, SettlementPolicy), 'settlement inputs required')
    book = _id(sportsbook_id)
    evidence, at = _inputs(evidence, asserted_at)
    accepted, diagnostics = [], []
    scope = dict(sportsbook_id=book, competition_id=contract.competition_id,
                 market_type=contract.market_type, scope=contract.scope)
    for item in evidence:
        doc = _json(item.content)
        _require(doc.get('format') == RULES_FORMAT, 'unsupported rules evidence format')
        _require(doc.get('binding') == scope, 'wrong sportsbook/competition/market/scope binding')
        _text(doc.get('rules_revision'))
        start = _instant(doc.get('effective_from'))
        end = _instant(doc['effective_until']) if doc.get('effective_until') is not None else None
        _require(end is None or end > start, 'invalid rules applicability interval')
        terms, classification = _terms(doc.get('terms'))
        _require(terms['outcome_labels'] == sorted(label for _, label in contract.outcomes),
                 'rules do not match canonical settlement outcomes')
        grant = SettlementSourceGrant(item.authority, item.source_type, item.content_sha256, **scope)
        if grant not in policy.sources:
            diagnostics.append((item.id, 'unapproved_rules_revision'))
        elif at < start or (end is not None and at >= end):
            diagnostics.append((item.id, 'rules_not_effective'))
        else:
            accepted.append((terms, classification, start, end))
            diagnostics.append((item.id, 'admissible'))
    variants = {canonical(t) for t, _, _, _ in accepted}
    if len(variants) > 1:
        classification, reason, terms = 'unknown', 'conflicting_settlement_evidence', None
    elif not variants:
        classification, reason, terms = 'unknown', 'insufficient_settlement_authority', None
    else:
        terms, classification = accepted[0][:2]
        reason = 'explicit_settlement_rules' if classification != 'unknown' else 'unclassified_settlement_rules'
    ends = [end for _, _, _, end in accepted if end is not None]
    return _assertion(assertion_id, 'settlement', dict(contract=asdict(contract), sportsbook_id=book),
                      policy, evidence, at, classification, reason, diagnostics,
                      max((start for _, _, start, _ in accepted), default=None),
                      min(ends, default=None), terms)


def check_ev_v1_capability(*, phase, settlements, contract, required_sportsbook_ids, at):
    """Separate capability/compatibility gate, not EV calculation or actionability.

    All target/contributing books must be explicitly named by the caller. Missing
    assertions fail closed; duplicate or wrong-subject assertions are errors.
    This does not select books, change snapshots, or wire the production worker.
    """
    _require(isinstance(phase, ValidationAssertion) and isinstance(contract, ContractBinding),
             'phase assertion and contract required')
    at = _time(at)
    phase_result = phase.result
    _require(phase_result['kind'] == 'phase' and phase_result['subject']['event_id'] == contract.event_id,
             'phase assertion event mismatch')
    required = tuple(_id(b) for b in required_sportsbook_ids)
    _require(bool(required) and len(set(required)) == len(required), 'explicit distinct required books needed')
    books, results = set(), []
    for assertion in settlements:
        _require(isinstance(assertion, ValidationAssertion), 'settlement assertion required')
        result = assertion.result
        _require(result['kind'] == 'settlement' and result['subject']['contract'] == _encode(contract),
                 'settlement assertion contract mismatch')
        book = result['subject']['sportsbook_id']
        _require(book in required and book not in books, 'unexpected or duplicate sportsbook assertion')
        books.add(book)
        results.append(result)
    for result in [phase_result, *results]:
        _require(_instant(result['asserted_at']) <= at, 'future assertion cannot authorize capture')
        end = result['valid_until']
        if end is not None and (at > _instant(end) if result['kind'] == 'phase' else at >= _instant(end)):
            return 'assertion_expired'
    if phase_result['classification'] != 'supported_pregame':
        return 'unsupported_phase'
    if books != set(required):
        return 'missing_settlement_assertion'
    if contract.market_type != 'moneyline' or len(contract.outcomes) != 2:
        return 'unsupported_contract'
    if any(r['classification'] != 'no_push_two_way' for r in results):
        return 'unsupported_settlement'
    if len({canonical(r['terms']) for r in results}) != 1:
        return 'incompatible_settlement_rules'
    return None
