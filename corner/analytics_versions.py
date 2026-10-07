"""Explicit v1/v2 analytics boundary; v1 modules and build hashes stay intact.

V2 uses the existing ledgers, not production capture or lifecycle orchestration.
Caller owns READ COMMITTED transactions and authenticated authority. Unknown
formats/builds are errors, never instructions to run today's implementation.
"""
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
import hashlib
import json
from pathlib import Path
from uuid import UUID

from psycopg2.extras import Json

from corner import channels as ch, evaluations as v1, qualifications as q1
from corner import ev_conditional as v2
from corner.lifecycle import ImplementationIdentity, ActionabilityPolicy

EVALUATION_FORMAT = 'corner.ev.snapshot/2'
QUALIFICATION_FORMAT = 'corner.qualification.snapshot/2'
CHANNEL_FORMAT = 'corner.channel.configuration/2'
REGISTRATION_FORMAT = 'corner.channel.registration/2'
BUILD = dict(v1.ENGINE_BUILD) | {
    'conditional_source_sha256': hashlib.sha256(Path(v2.__file__).read_bytes()).hexdigest(),
    'version_adapter_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'serializer_sha256': hashlib.sha256(Path(v1.__file__).read_bytes()).hexdigest(),
    'qualification_helpers_sha256': hashlib.sha256(Path(q1.__file__).read_bytes()).hexdigest(),
    'channel_helpers_sha256': hashlib.sha256(Path(ch.__file__).read_bytes()).hexdigest(),
}
REVISION = 'sha256:' + v1._digest(BUILD).hex()
ENGINE = ImplementationIdentity(v2.ENGINE_NAME, v2.ENGINE_VERSION, REVISION)
QUALIFIER = ImplementationIdentity('minimum_conditional_ev', '2', REVISION)
LEGACY_BASIS = 'legacy_v1_unspecified'


class BasisMismatch(q1.QualificationValidationError):
    pass


def configuration_snapshot(config):
    v2.require(type(config) is v2.Configuration, 'conditional configuration required')
    result = v1._encode(asdict(config))
    result['pricing'].pop('settlement_policy')  # Kernel label is not v2 settlement authority.
    result['pricing']['reference_sportsbook_ids'] = sorted(str(UUID(x)) for x in result['pricing']['reference_sportsbook_ids'])
    return result


def serialize_command(command):
    if type(command) is v1.EvaluationCommand:
        return v1.serialize_command(command)
    v2.require(type(command) is v2.EvaluationCommand, 'supported evaluation command required')
    base = v1.serialize_command(v1.EvaluationCommand(command.snapshot, command.configuration.pricing,
                                                    command.context_json))
    return base | {'snapshot_format_version': EVALUATION_FORMAT, 'engine_version': v2.ENGINE_VERSION,
                   'engine_revision': REVISION, 'engine_build': BUILD,
                   'configuration': configuration_snapshot(command.configuration),
                   'settlements': v1._encode([asdict(s) for s in command.settlements])}


def deserialize_command(document):
    if document.get('snapshot_format_version') == v1.FORMAT_VERSION:
        return v1.deserialize_command(document)
    v2.require(document.get('snapshot_format_version') == EVALUATION_FORMAT, 'unsupported evaluation format')
    v2.require((document.get('engine_name'), document.get('engine_version'), document.get('engine_revision')) ==
               (ENGINE.name, ENGINE.version, ENGINE.revision) and document.get('engine_build') == BUILD,
               'original conditional engine build/runtime unavailable')
    config = dict(document['configuration'])
    pricing = config.pop('pricing') | {'settlement_policy': 'two_way_no_push'}
    legacy = v1.deserialize_command({
        'snapshot_format_version': v1.FORMAT_VERSION, 'engine_name': v1.ev.ENGINE_NAME,
        'engine_version': v1.ev.ENGINE_VERSION, 'engine_revision': v1.ENGINE_REVISION,
        'engine_build': v1.ENGINE_BUILD, 'snapshot': document['snapshot'],
        'configuration': pricing, 'context': document['context']})
    config['settlement'] = v2.SettlementPolicy(**config['settlement'])
    command = v2.EvaluationCommand(legacy.snapshot, v2.Configuration(pricing=legacy.configuration, **config),
        tuple(v2.SettlementEvidence(**s) for s in document['settlements']), legacy.context_json)
    v2.require(serialize_command(command) == document, 'noncanonical or contradictory conditional command')
    return command


def evaluate_command(command):
    if type(command) is v1.EvaluationCommand:
        return v1.ev.evaluate_ev(command.snapshot, command.configuration)
    v2.require(type(command) is v2.EvaluationCommand, 'supported evaluation command required')
    return v2.evaluate(command)


def serialize_result(result):
    output = v1.serialize_result(result)
    if result.engine_version == v1.ev.ENGINE_VERSION:
        return output
    v2.require(result.engine_version == v2.ENGINE_VERSION, 'unsupported result version')
    probability, ratio = output.pop('fair_probability'), output.pop('ev_ratio')
    return output | {'snapshot_format_version': EVALUATION_FORMAT,
        'calculation_basis': v2.BASIS, 'fair_probability_basis': v2.PROBABILITY_BASIS,
        'conditional_fair_probability': probability, 'conditional_ev_ratio': ratio,
        'invalidation_probability_model': 'none', 'unconditional_ev_ratio': None}


@dataclass(frozen=True)
class DecodedEvaluation:
    calculation_basis: str
    fair_probability_basis: str
    fair_probability: Decimal | None
    ev_ratio: Decimal | None


def _rounded(value, scale):
    if value is None:
        return None
    with localcontext(Context(prec=max(40, len(value.as_tuple().digits) + 20), rounding=ROUND_HALF_EVEN)):
        return value.quantize(Decimal(scale))


def _decode_evaluation(row):
    """Basis-aware result reader. No v1 probability is retroactively relabeled."""
    if row.get('snapshot_format_version') == v1.FORMAT_VERSION:
        value = q1.validate_evaluation(row)
        prob = row['result_snapshot'].get('fair_probability')
        return DecodedEvaluation(LEGACY_BASIS, LEGACY_BASIS, Decimal(prob) if prob is not None else None, value)
    v2.require(row.get('snapshot_format_version') == EVALUATION_FORMAT, 'unsupported evaluation result format')
    doc = row['result_snapshot']
    v2.require(v1._digest(doc) == bytes(row['result_sha256']), 'evaluation result digest mismatch')
    v2.require(doc.get('snapshot_format_version') == EVALUATION_FORMAT and
        doc.get('calculation_basis') == v2.BASIS and doc.get('fair_probability_basis') == v2.PROBABILITY_BASIS and
        doc.get('invalidation_probability_model') == 'none' and 'unconditional_ev_ratio' in doc and
        doc['unconditional_ev_ratio'] is None, 'invalid conditional result basis/model')
    v2.require(doc['result_kind'] == row['result_kind'] and
        doc['non_evaluation_reason'] == row['non_evaluation_reason'], 'result projection mismatch')
    v2.require(type(doc['reference_book_count']) is int and doc['reference_book_count'] >= 0 and
               doc['reference_book_count'] == row['reference_book_count'], 'invalid reference count')
    if doc['result_kind'] == 'not_evaluable':
        v2.require(isinstance(doc['non_evaluation_reason'], str) and bool(doc['non_evaluation_reason'].strip())
            and doc['conditional_fair_probability'] is None and doc['conditional_ev_ratio'] is None
            and row['fair_probability'] is None and row['ev_ratio'] is None, 'invalid non-evaluation shape')
        return DecodedEvaluation(v2.BASIS, v2.PROBABILITY_BASIS, None, None)
    v2.require(doc['result_kind'] == 'evaluated' and doc['non_evaluation_reason'] is None, 'invalid result kind')
    probability = q1._decimal_string(doc['conditional_fair_probability'], 'conditional probability')
    ratio = q1._decimal_string(doc['conditional_ev_ratio'], 'conditional EV')
    v2.require(0 <= probability <= 1 and _rounded(probability, '.0000000001') == row['fair_probability']
        and _rounded(ratio, '.00000001') == row['ev_ratio'], 'conditional typed metric mismatch')
    return DecodedEvaluation(v2.BASIS, v2.PROBABILITY_BASIS, probability, ratio)


def decode_evaluation(row):
    try:
        return _decode_evaluation(row)
    except (KeyError, TypeError, AttributeError, ArithmeticError) as exc:
        raise q1.QualificationValidationError('malformed versioned evaluation evidence') from exc


def _existing(cur, table, key_fields, key, document, prefix=''):
    # Table/column names are module constants from the three callers below.
    cur.execute('SELECT * FROM corner.' + table + ' WHERE ' +
                ' AND '.join(field + '=%s' for field in key_fields), key)
    row = cur.fetchone()
    if row:
        if row[prefix + 'command_snapshot'] != document or bytes(row[prefix + 'command_sha256']) != v1._digest(document):
            raise v1.EvaluationConflict('authority/key identifies a different versioned command')
        return dict(row)
    return None


def _insert(cur, table, values, key_fields, key, document, prefix=''):
    cur.execute('INSERT INTO corner.' + table + ' (' + ','.join(values) + ') VALUES (' +
                ','.join(['%s'] * len(values)) + ') ON CONFLICT (' + ','.join(key_fields) +
                ') DO NOTHING RETURNING *', tuple(values.values()))
    inserted = cur.fetchone()
    if inserted:
        return dict(inserted), True
    row = _existing(cur, table, key_fields, key, document, prefix)
    if row is None:
        raise RuntimeError('concurrent command outside snapshot; retry transaction')
    if 'result_snapshot' in values and (row['result_snapshot'] != values['result_snapshot'].adapted or
                                      bytes(row['result_sha256']) != values['result_sha256']):
        raise v1.DeterminismFailure('same versioned command produced different result; original retained')
    return row, False


def record_evaluation(conn, *, authority, evaluation_key, command):
    if type(command) is v1.EvaluationCommand:
        return v1.record_evaluation(conn, authority=authority, evaluation_key=evaluation_key, command=command)
    key = ch._authority(authority, evaluation_key)
    document = serialize_command(command)
    normalized = deserialize_command(document)
    fields = ('authority_kind', 'authority_id', 'evaluation_key')
    with ch._write(conn, 'corner_conditional_evaluation') as cur:
        existing = _existing(cur, 'engine_evaluations', fields, key, document)
        if existing:
            return existing
        v1._validate_evidence(cur, normalized)
        result = evaluate_command(normalized)
        output = serialize_result(result)
        values = dict(zip(fields, key)) | dict(
            evaluated_at=normalized.snapshot.evaluated_at, engine_name=ENGINE.name,
            engine_version=ENGINE.version, engine_revision=REVISION, configuration_version=normalized.configuration.version,
            snapshot_format_version=EVALUATION_FORMAT, target_observation_id=normalized.snapshot.target_observation_id,
            market_id=normalized.snapshot.contract.market_id, competition_id=normalized.snapshot.contract.competition_id,
            result_kind=output['result_kind'], non_evaluation_reason=output['non_evaluation_reason'],
            fair_probability=_rounded(result.fair_probability, '.0000000001'),
            ev_ratio=_rounded(result.ev_ratio, '.00000001'), reference_book_count=output['reference_book_count'],
            command_snapshot=Json(document), command_sha256=v1._digest(document),
            result_snapshot=Json(output), result_sha256=v1._digest(output))
        row, inserted = _insert(cur, 'engine_evaluations', values, fields, key, document)
        if inserted:
            cur.executemany('INSERT INTO corner.engine_evaluation_inputs (evaluation_id,observation_id,role) VALUES (%s,%s,%s)',
                [(row['id'], q.observation_id, 'target' if q.observation_id == normalized.snapshot.target_observation_id
                  else 'reference') for q in normalized.snapshot.quotes])
        return row


@dataclass(frozen=True)
class ConditionalEVPolicy:
    version: str
    minimum_ev_ratio: Decimal
    expected_calculation_basis: str = v2.BASIS

    def __post_init__(self):
        q1.MinimumEVPolicy(self.version, self.minimum_ev_ratio)
        v2.require(self.expected_calculation_basis == v2.BASIS, 'unsupported qualification basis')


@dataclass(frozen=True)
class QualificationCommand:
    engine_evaluation_id: str
    policy: ConditionalEVPolicy
    decided_at: datetime
    context_json: str = '{}'


def qualify_evaluation(row, policy):
    decoded = decode_evaluation(row)
    if type(policy) is q1.MinimumEVPolicy:
        if decoded.calculation_basis != LEGACY_BASIS:
            raise BasisMismatch('v1 policy cannot interpret conditional EV')
        return q1.qualify_evaluation(row, policy)
    v2.require(type(policy) is ConditionalEVPolicy, 'supported qualification policy required')
    if decoded.calculation_basis != policy.expected_calculation_basis:
        raise BasisMismatch('qualification calculation basis mismatch')
    if decoded.ev_ratio is None:
        return q1.QualificationResult('not_qualifiable', 'evaluation_not_evaluable', None, policy.minimum_ev_ratio)
    passed = decoded.ev_ratio >= policy.minimum_ev_ratio
    return q1.QualificationResult('qualified' if passed else 'not_qualified',
        'ev_threshold_met' if passed else 'below_minimum_ev', decoded.ev_ratio, policy.minimum_ev_ratio)


def qualification_policy_snapshot(policy):
    v2.require(type(policy) is ConditionalEVPolicy, 'conditional qualification policy required')
    return {'policy_name': QUALIFIER.name, 'policy_version': policy.version,
        'policy_revision': REVISION, 'policy_build': BUILD, 'comparison': 'greater_than_or_equal',
        'minimum_ev_ratio': v1._decimal(policy.minimum_ev_ratio),
        'expected_calculation_basis': policy.expected_calculation_basis}


def record_qualification(conn, *, authority, qualification_key, command):
    if type(command) is q1.QualificationCommand:
        return q1.record_qualification(conn, authority=authority, qualification_key=qualification_key, command=command)
    v2.require(type(command) is QualificationCommand, 'supported qualification command required')
    key = ch._authority(authority, qualification_key)
    fields = ('authority_kind', 'authority_id', 'qualification_key')
    with ch._write(conn, 'corner_conditional_qualification') as cur:
        cur.execute('SELECT * FROM corner.engine_evaluations WHERE id=%s', (str(UUID(command.engine_evaluation_id)),))
        evaluation = cur.fetchone()
        v2.require(evaluation is not None, 'evaluation does not exist')
        policy = qualification_policy_snapshot(command.policy)
        document = {'qualification_snapshot_format_version': QUALIFICATION_FORMAT,
            'engine_evaluation_id': evaluation['id'], 'evaluation_snapshot_format_version': evaluation['snapshot_format_version'],
            'evaluation_result_sha256': bytes(evaluation['result_sha256']).hex(), 'policy': policy,
            'policy_sha256': v1._digest(policy).hex(), 'decided_at': v1._encode(command.decided_at),
            'context': q1._context(command.context_json)}
        existing = _existing(cur, 'qualification_decisions', fields, key, document)
        if existing:
            return existing
        result = qualify_evaluation(evaluation, command.policy)
        output = q1._result_snapshot(result, document) | {'calculation_basis': v2.BASIS}
        values = dict(zip(fields, key)) | dict(
            engine_evaluation_id=evaluation['id'], evaluation_result_sha256=bytes(evaluation['result_sha256']),
            policy_name=QUALIFIER.name, policy_version=command.policy.version, policy_revision=REVISION,
            qualification_snapshot_format_version=QUALIFICATION_FORMAT, decision_kind=result.decision_kind,
            reason_code=result.reason_code, decided_at=command.decided_at, command_snapshot=Json(document),
            command_sha256=v1._digest(document), result_snapshot=Json(output), result_sha256=v1._digest(output))
        return _insert(cur, 'qualification_decisions', values, fields, key, document)[0]


@dataclass(frozen=True)
class GenerationConfiguration:
    engine: ImplementationIdentity
    engine_configuration: v2.Configuration
    qualification_implementation: ImplementationIdentity
    qualification_policy: ConditionalEVPolicy
    settlement_policy: v2.SettlementPolicy
    actionability_policy: ActionabilityPolicy

    def __post_init__(self):
        v2.require(self.engine == ENGINE and self.qualification_implementation == QUALIFIER,
                   'incompatible engine/qualifier implementation tuple')
        v2.require(type(self.engine_configuration) is v2.Configuration and
                   type(self.qualification_policy) is ConditionalEVPolicy and
                   type(self.settlement_policy) is v2.SettlementPolicy and
                   type(self.actionability_policy) is ActionabilityPolicy, 'incompatible generation policy types')
        v2.require(self.engine_configuration.calculation_basis == self.qualification_policy.expected_calculation_basis
                   == self.settlement_policy.calculation_basis and
                   self.engine_configuration.settlement == self.settlement_policy, 'incompatible generation basis/settlement tuple')


def generation_snapshot(config):
    if type(config) is ch.GenerationConfiguration:
        v2.require(config.engine != ENGINE and config.qualification_implementation != QUALIFIER,
                   'v2 implementation cannot use a legacy generation contract')
        return ch.configuration_snapshot(config)
    v2.require(type(config) is GenerationConfiguration, 'supported generation configuration required')
    return {'snapshot_format_version': CHANNEL_FORMAT,
        'engine': {'implementation': asdict(config.engine), 'configuration': configuration_snapshot(config.engine_configuration)},
        'qualification': {'implementation': asdict(config.qualification_implementation),
                          'configuration': qualification_policy_snapshot(config.qualification_policy)},
        'settlement': v1._encode(asdict(config.settlement_policy)),
        'lifecycle': {'implementation': asdict(config.actionability_policy.identity), 'configuration': {
            'target_max_age_microseconds': v1._encode(config.actionability_policy.target_max_age),
            'reference_max_age_microseconds': v1._encode(config.actionability_policy.reference_max_age)}}}


def register_generation(conn, *, authority, registration_key, command):
    if type(command.configuration) is ch.GenerationConfiguration:
        generation_snapshot(command.configuration)
        return ch.register_generation(conn, authority=authority, registration_key=registration_key, command=command)
    key = ch._authority(authority, registration_key)
    config = generation_snapshot(command.configuration)
    document = {'snapshot_format_version': REGISTRATION_FORMAT, 'channel_id': ch._uuid(command.channel_id),
        'configuration': config, 'configuration_sha256': v1._digest(config).hex(), 'context': ch._context(command.context_json)}
    fields = ('registration_authority_kind', 'registration_authority_id', 'registration_key')
    with ch._write(conn, 'corner_conditional_generation') as cur:
        existing = _existing(cur, 'qualification_channel_generations', fields, key, document, 'registration_')
        if existing:
            return existing
        values = dict(zip(fields, key)) | dict(channel_id=document['channel_id'], snapshot_format_version=CHANNEL_FORMAT,
            configuration_snapshot=Json(config), configuration_sha256=v1._digest(config),
            registration_command_snapshot=Json(document), registration_command_sha256=v1._digest(document))
        for part in ('engine', 'qualification', 'lifecycle'):
            for field in ('name', 'version', 'revision'):
                values[part + '_' + field] = config[part]['implementation'][field]
        return _insert(cur, 'qualification_channel_generations', values, fields, key, document, 'registration_')[0]
