"""Minimum-EV policy and immutable qualification persistence.

Reads only EngineEvaluation. No current quotes, no phase/freshness checks, no EV
recalculation. Callers own READ COMMITTED transaction commit/rollback and provide
authority from trusted execution context. This module does not authenticate users.
"""

import hashlib
import json
import platform
import re
import decimal
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID

from psycopg2.extras import Json, RealDictCursor

from corner import evaluations as serialization


FORMAT_VERSION = 'corner.qualification.snapshot/1'
POLICY_BUILD = {
    'qualification_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'serialization_source_sha256': hashlib.sha256(Path(serialization.__file__).read_bytes()).hexdigest(),
    'python_version': platform.python_version(),
    'python_implementation': platform.python_implementation(),
    'decimal_version': decimal.__version__,
    'libmpdec_version': decimal.__libmpdec_version__,
}
POLICY_REVISION = 'sha256:' + serialization._digest(POLICY_BUILD).hex()


class QualificationValidationError(ValueError):
    """Corrupt/unsupported evidence or invalid command, not a domain decision."""


class QualificationConflict(ValueError):
    pass


class QualificationDeterminismFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class QualificationAuthority:
    kind: str
    identifier: str


@dataclass(frozen=True)
class MinimumEVPolicy:
    version: str
    minimum_ev_ratio: Decimal

    def __post_init__(self):
        if not isinstance(self.version, str) or not self.version.strip():
            raise QualificationValidationError('policy version is required')
        value = self.minimum_ev_ratio
        if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
            raise QualificationValidationError('minimum EV must be a finite strictly positive Decimal')


@dataclass(frozen=True)
class QualificationCommand:
    engine_evaluation_id: str
    policy: MinimumEVPolicy
    decided_at: datetime
    context_json: str = '{}'


@dataclass(frozen=True)
class QualificationResult:
    decision_kind: str
    reason_code: str
    compared_ev: Decimal | None
    minimum_ev_ratio: Decimal
    comparison: str = 'greater_than_or_equal'


def _decimal_string(value, name):
    # Format 1 specifies base-10 strings, not floats, special values or exponents.
    if not isinstance(value, str) or not re.fullmatch(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?', value):
        raise QualificationValidationError(f'missing/malformed {name}')
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise QualificationValidationError(f'malformed {name}') from error
    if not result.is_finite():
        raise QualificationValidationError(f'nonfinite {name}')
    return result


def _decode_result_v1(evaluation):
    doc = evaluation['result_snapshot']
    if not isinstance(doc, dict):
        raise QualificationValidationError('result snapshot must be an object')
    kind = doc.get('result_kind')
    if kind != evaluation['result_kind']:
        raise QualificationValidationError('result kind contradicts typed projection')
    reason = doc.get('non_evaluation_reason')
    if reason != evaluation['non_evaluation_reason']:
        raise QualificationValidationError('reason contradicts typed projection')
    if kind == 'not_evaluable':
        if (not isinstance(reason, str) or not reason.strip()
                or 'ev_ratio' not in doc or doc['ev_ratio'] is not None
                or 'fair_probability' not in doc or doc['fair_probability'] is not None
                or evaluation['ev_ratio'] is not None or evaluation['fair_probability'] is not None):
            raise QualificationValidationError('invalid non-evaluation evidence')
        return None
    if kind != 'evaluated' or reason is not None:
        raise QualificationValidationError('invalid evaluation result kind/reason')
    value = _decimal_string(doc.get('ev_ratio'), 'full-precision EV')
    probability = _decimal_string(doc.get('fair_probability'), 'full-precision probability')
    if probability < 0 or probability > 1:
        raise QualificationValidationError('invalid fair probability')
    if evaluation['ev_ratio'] is None or evaluation['fair_probability'] is None:
        raise QualificationValidationError('missing typed metric projection')
    return value


_RESULT_DECODERS = {'corner.ev.snapshot/1': _decode_result_v1}


def validate_evaluation(evaluation):
    decoder = _RESULT_DECODERS.get(evaluation.get('snapshot_format_version'))
    if decoder is None:
        raise QualificationValidationError('unsupported evaluation snapshot format')
    try:
        digest = serialization._digest(evaluation['result_snapshot'])
        recorded = bytes(evaluation['result_sha256'])
    except (KeyError, TypeError, ValueError) as error:
        raise QualificationValidationError('invalid result evidence/digest') from error
    if digest != recorded:
        raise QualificationValidationError('evaluation result digest mismatch')
    try:
        return decoder(evaluation)
    except (KeyError, TypeError) as error:
        raise QualificationValidationError('incomplete/malformed evaluation evidence') from error


def qualify_evaluation(evaluation, policy: MinimumEVPolicy) -> QualificationResult:
    """Pure decision using the format-specific, digest-verified persisted EV."""
    value = validate_evaluation(evaluation)
    if value is None:
        return QualificationResult('not_qualifiable', 'evaluation_not_evaluable', None, policy.minimum_ev_ratio)
    qualifies = value >= policy.minimum_ev_ratio
    return QualificationResult('qualified' if qualifies else 'not_qualified',
        'ev_threshold_met' if qualifies else 'below_minimum_ev', value, policy.minimum_ev_ratio)


def _context(text):
    try:
        value = json.loads(text, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        if not isinstance(value, dict):
            raise QualificationValidationError('context must be a JSON object')
        return serialization._encode(value, identifiers=False)
    except (TypeError, ValueError) as error:
        raise QualificationValidationError('context must be a JSON object without floating-point numbers') from error


def _command_snapshot(command, evaluation):
    policy = {'policy_name': 'minimum_ev', 'policy_version': command.policy.version,
              'policy_revision': POLICY_REVISION, 'policy_build': dict(POLICY_BUILD),
              'minimum_ev_ratio': serialization._decimal(command.policy.minimum_ev_ratio),
              'comparison': 'greater_than_or_equal'}
    return {
        'qualification_snapshot_format_version': FORMAT_VERSION,
        'engine_evaluation_id': str(UUID(command.engine_evaluation_id)),
        'evaluation_snapshot_format_version': evaluation['snapshot_format_version'],
        'evaluation_result_sha256': bytes(evaluation['result_sha256']).hex(),
        'policy': policy, 'policy_sha256': serialization._digest(policy).hex(),
        'decided_at': serialization._encode(command.decided_at), 'context': _context(command.context_json),
    }


def _result_snapshot(result, document):
    return {key: document[key] for key in (
        'engine_evaluation_id', 'evaluation_result_sha256', 'decided_at')} | {
        'decision_kind': result.decision_kind, 'reason_code': result.reason_code,
        'compared_ev': serialization._decimal(result.compared_ev) if result.compared_ev is not None else None,
        'minimum_ev_ratio': serialization._decimal(result.minimum_ev_ratio),
        'comparison': result.comparison, 'policy_name': document['policy']['policy_name'],
        'policy_version': document['policy']['policy_version'],
        'policy_revision': document['policy']['policy_revision'],
    }


def _check_retry(existing, document):
    if (bytes(existing['command_sha256']) != serialization._digest(document)
            or existing['command_snapshot'] != document):
        raise QualificationConflict('qualification key already identifies a different command')


def record_qualification(conn, *, authority: QualificationAuthority,
                         qualification_key: str, command: QualificationCommand):
    if (authority.kind not in {'human', 'service'} or not authority.identifier.strip()
            or not qualification_key.strip()):
        raise QualificationValidationError('valid authority and qualification key required')
    if command.decided_at.tzinfo is None or command.decided_at.utcoffset() is None:
        raise QualificationValidationError('decided_at must include timezone')
    evaluation_id = str(UUID(command.engine_evaluation_id))
    key = (authority.kind, authority.identifier, qualification_key)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute('SELECT * FROM corner.engine_evaluations WHERE id=%s', (evaluation_id,))
        evaluation = cur.fetchone()
        if evaluation is None:
            raise QualificationValidationError('evaluation does not exist')
        validate_evaluation(evaluation)
        document = _command_snapshot(command, evaluation)
        cur.execute('''SELECT * FROM corner.qualification_decisions
            WHERE authority_kind=%s AND authority_id=%s AND qualification_key=%s''', key)
        existing = cur.fetchone()
        if existing:
            _check_retry(existing, document)
            return dict(existing)
        result = qualify_evaluation(evaluation, command.policy)
        output = _result_snapshot(result, document)
        cur.execute('SAVEPOINT corner_qualification_write')
        try:
            cur.execute('''INSERT INTO corner.qualification_decisions
                (engine_evaluation_id, evaluation_result_sha256,
                 authority_kind, authority_id, qualification_key,
                 policy_name, policy_version, policy_revision, qualification_snapshot_format_version,
                 decision_kind, reason_code, decided_at,
                 command_snapshot, command_sha256, result_snapshot, result_sha256)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT ON CONSTRAINT qualification_decisions_command_key DO NOTHING RETURNING *''',
                (evaluation_id, bytes(evaluation['result_sha256'])) + key + (
                    'minimum_ev', command.policy.version, POLICY_REVISION, FORMAT_VERSION,
                    result.decision_kind, result.reason_code, command.decided_at,
                    Json(document), serialization._digest(document), Json(output), serialization._digest(output)))
            inserted = cur.fetchone()
            if inserted is not None:
                stored = dict(inserted)
            else:
                cur.execute('''SELECT * FROM corner.qualification_decisions
                    WHERE authority_kind=%s AND authority_id=%s AND qualification_key=%s''', key)
                existing = cur.fetchone()
                if existing is None:
                    raise RuntimeError('retry transaction: concurrent command is outside snapshot')
                _check_retry(existing, document)
                if bytes(existing['result_sha256']) != serialization._digest(output) or existing['result_snapshot'] != output:
                    raise QualificationDeterminismFailure('same command produced different judgment; original retained')
                stored = dict(existing)
            cur.execute('RELEASE SAVEPOINT corner_qualification_write')
            return stored
        except Exception:
            cur.execute('ROLLBACK TO SAVEPOINT corner_qualification_write')
            cur.execute('RELEASE SAVEPOINT corner_qualification_write')
            raise
