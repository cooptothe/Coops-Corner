"""Synchronous immutable EV ledger. Caller owns commit/rollback (READ COMMITTED).

Accepts one domain command; calculates internally so typed results, snapshots and
input links cannot be independently supplied. No authentication or job queue here.
Keep the exact engine source/runtime artifacts identified by ENGINE_BUILD for replay.
"""

import hashlib
import json
import platform
import decimal
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from enum import Enum
from pathlib import Path
from uuid import UUID

from psycopg2.extras import Json, RealDictCursor

from corner import ev


FORMAT_VERSION = 'corner.ev.snapshot/1'
ENGINE_BUILD = {
    'source_sha256': hashlib.sha256(Path(ev.__file__).read_bytes()).hexdigest(),
    'python_implementation': platform.python_implementation(),
    'python_version': platform.python_version(),
    'decimal_version': decimal.__version__,
    'libmpdec_version': decimal.__libmpdec_version__,
}


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


ENGINE_REVISION = 'sha256:' + hashlib.sha256(canonical_json(ENGINE_BUILD).encode('utf-8')).hexdigest()


def _decimal(value):
    if not value.is_finite():
        raise ValueError('nonfinite Decimal cannot be serialized as evidence')
    if value == 0:
        return '0'
    text = format(value, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


_UUID_FIELDS = {'observation_id', 'target_observation_id', 'market_id', 'competition_id',
                'outcome_id', 'participant_id', 'sportsbook_id'}


def _encode(value, field=None, *, identifiers=True):
    if value is None:
        return None
    if identifiers and field in _UUID_FIELDS:
        return str(UUID(str(value)))
    if isinstance(value, Decimal):
        return _decimal(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('snapshot timestamps must include timezone')
        return value.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')
    if isinstance(value, timedelta):
        return (value.days * 86400 + value.seconds) * 1_000_000 + value.microseconds
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ValueError('JSON object keys must be strings')
        return {key: _encode(item, key, identifiers=identifiers) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_encode(item, identifiers=identifiers) for item in value]
    if isinstance(value, (str, int, bool)):
        return value
    raise ValueError(f'unsupported snapshot value: {type(value).__name__}; floats are prohibited')


@dataclass(frozen=True)
class EvaluationAuthority:
    kind: str
    identifier: str


@dataclass(frozen=True)
class EvaluationCommand:
    snapshot: ev.EVSnapshot
    configuration: ev.EVConfiguration
    # Immutable JSON text at this boundary. Object formatting is not command identity.
    context_json: str = '{}'


class EvaluationConflict(ValueError):
    pass


class DeterminismFailure(RuntimeError):
    pass


def serialize_command(command):
    snapshot = _encode(asdict(command.snapshot))
    snapshot['quotes'].sort(key=lambda q: q['observation_id'])
    snapshot['contract']['outcomes'].sort(key=lambda o: o['outcome_id'])
    config = _encode(asdict(command.configuration))
    config['reference_sportsbook_ids'] = sorted(str(UUID(x)) for x in config['reference_sportsbook_ids'])
    context = json.loads(command.context_json,
                         parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    if not isinstance(context, dict):
        raise ValueError('evaluation context must be a JSON object')
    return {
        'snapshot_format_version': FORMAT_VERSION,
        'engine_name': ev.ENGINE_NAME, 'engine_version': ev.ENGINE_VERSION,
        'engine_revision': ENGINE_REVISION, 'engine_build': dict(ENGINE_BUILD),
        'snapshot': snapshot, 'configuration': config, 'context': _encode(context, identifiers=False),
    }


def deserialize_command(document):
    """Rebuild immutable engine inputs without consulting current domain tables."""
    if document['snapshot_format_version'] != FORMAT_VERSION:
        raise ValueError('unsupported snapshot format')
    if (document['engine_name'], document['engine_version'], document['engine_revision']) != (
            ev.ENGINE_NAME, ev.ENGINE_VERSION, ENGINE_REVISION):
        raise ValueError('snapshot requires its original engine build/runtime')
    snap = document['snapshot']
    contract = dict(snap['contract'])
    contract['outcomes'] = tuple(ev.OutcomeContract(o['outcome_id'], o['participant_id'],
                                                  Decimal(o['point']) if o['point'] is not None else None)
                                 for o in contract['outcomes'])
    quotes = tuple(ev.QuoteInput(q['observation_id'], q['market_id'], q['outcome_id'], q['sportsbook_id'],
        Decimal(q['decimal_odds']) if q['decimal_odds'] is not None else None, q['quote_state'],
        datetime.fromisoformat(q['observed_at']),
        datetime.fromisoformat(q['provider_updated_at']) if q['provider_updated_at'] else None)
        for q in snap['quotes'])
    snapshot = ev.EVSnapshot(datetime.fromisoformat(snap['evaluated_at']), snap['event_phase'],
        snap['phase_evidence'], ev.MarketContract(**contract), snap['target_observation_id'], quotes)
    config = dict(document['configuration'])
    for key in ('target_max_age', 'reference_max_age', 'max_input_skew', 'provider_max_age'):
        config[key] = timedelta(microseconds=config[key]) if config[key] is not None else None
    config['provider_time_policy'] = ev.ProviderTimePolicy(config['provider_time_policy'])
    return EvaluationCommand(snapshot, ev.EVConfiguration(**config), canonical_json(document['context']))


def serialize_result(result):
    estimates = []
    for item in result.reference_estimates:
        estimates.append({
            'sportsbook_id': str(UUID(item.sportsbook_id)),
            'observation_ids': sorted(str(UUID(i)) for i in item.observation_ids),
            'outcome_probabilities': sorted(
                [[str(UUID(outcome)), _decimal(prob)] for outcome, prob in item.outcome_probabilities]),
        })
    exclusions = [{
        'sportsbook_id': str(UUID(item.sportsbook_id)),
        'observation_ids': sorted(str(UUID(i)) for i in item.observation_ids),
        'issue': item.issue.value,
    } for item in result.reference_exclusions]
    return {
        'result_kind': 'evaluated' if result.reason is None else 'not_evaluable',
        'non_evaluation_reason': result.reason.value if result.reason else None,
        'fair_probability': _decimal(result.fair_probability) if result.fair_probability is not None else None,
        'ev_ratio': _decimal(result.ev_ratio) if result.ev_ratio is not None else None,
        'reference_book_count': len(estimates),
        'reference_estimates': sorted(estimates, key=lambda item: item['sportsbook_id']),
        'reference_exclusions': sorted(exclusions, key=lambda item: item['sportsbook_id']),
    }


def _digest(document):
    return hashlib.sha256(canonical_json(document).encode('utf-8')).digest()


def _check_command(existing, document):
    if bytes(existing['command_sha256']) != _digest(document) or existing['command_snapshot'] != document:
        raise EvaluationConflict('evaluation key already identifies a different command')


def _validate_evidence(cur, command):
    snapshot = command.snapshot
    quotes = {q.observation_id: q for q in snapshot.quotes}
    if len(quotes) != len(snapshot.quotes) or snapshot.target_observation_id not in quotes:
        raise ValueError('evaluation requires distinct supplied observations including its target')
    cur.execute('''SELECT o.id, o.outcome_id, o.sportsbook_id, o.decimal_odds,
                         o.observed_at, o.provider_updated_at, s.code AS state,
                         oc.market_id, e.competition_id
                  FROM corner.odds_observations o
                  JOIN corner.quote_states s ON s.id=o.quote_state_id
                  JOIN corner.outcomes oc ON oc.id=o.outcome_id
                  JOIN corner.markets m ON m.id=oc.market_id
                  JOIN corner.events e ON e.id=m.event_id
                  WHERE o.id=ANY(%s::uuid[])''', (list(quotes),))
    rows = cur.fetchall()
    if len(rows) != len(quotes):
        raise ValueError('input observation does not exist')
    for row in rows:
        q = quotes[row['id']]
        if (q.outcome_id, q.sportsbook_id, q.decimal_odds, q.observed_at,
            q.provider_updated_at, q.quote_state, q.market_id) != (
            row['outcome_id'], row['sportsbook_id'], row['decimal_odds'], row['observed_at'],
            row['provider_updated_at'], row['state'], row['market_id']):
            raise ValueError('snapshot quote contradicts authoritative observation')
        if row['market_id'] != snapshot.contract.market_id or row['competition_id'] != snapshot.contract.competition_id:
            raise ValueError('snapshot contract contradicts canonical references')


def record_evaluation(conn, *, authority: EvaluationAuthority, evaluation_key: str,
                      command: EvaluationCommand):
    """Evaluate/persist one command atomically; return original row on an exact retry.

    Authority comes from trusted execution context. This API never accepts separate
    metrics, result JSON, digests, or input links. Callers must retain the same key,
    snapshot, configuration, engine build, and evaluation time across retries.
    """
    if authority.kind not in {'human', 'service'} or not authority.identifier.strip() or not evaluation_key.strip():
        raise ValueError('valid authority and nonblank evaluation key required')
    document = serialize_command(command)
    normalized = deserialize_command(document)
    key = (authority.kind, authority.identifier, evaluation_key)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute('''SELECT * FROM corner.engine_evaluations
                       WHERE authority_kind=%s AND authority_id=%s AND evaluation_key=%s''', key)
        existing = cur.fetchone()
        if existing:
            _check_command(existing, document)
            return dict(existing)

        # Preserve caller's earlier work, but never leave a header without its input links.
        cur.execute('SAVEPOINT corner_evaluation_write')
        try:
            _validate_evidence(cur, normalized)
            result = ev.evaluate_ev(normalized.snapshot, normalized.configuration)
            output = serialize_result(result)
            with localcontext(Context(prec=max(40, normalized.configuration.calculation_precision), rounding=ROUND_HALF_EVEN)):
                probability = result.fair_probability.quantize(Decimal('.0000000001')) if result.fair_probability is not None else None
                ev_ratio = result.ev_ratio.quantize(Decimal('.00000001')) if result.ev_ratio is not None else None
            cur.execute('''INSERT INTO corner.engine_evaluations
                (authority_kind, authority_id, evaluation_key, evaluated_at,
                 engine_name, engine_version, engine_revision, configuration_version, snapshot_format_version,
                 target_observation_id, market_id, competition_id,
                 result_kind, non_evaluation_reason, fair_probability, ev_ratio, reference_book_count,
                 command_snapshot, command_sha256, result_snapshot, result_sha256)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT ON CONSTRAINT engine_evaluations_command_key DO NOTHING RETURNING *''',
                key + (normalized.snapshot.evaluated_at, result.engine_name, result.engine_version,
                       document['engine_revision'], normalized.configuration.version, FORMAT_VERSION,
                       normalized.snapshot.target_observation_id, normalized.snapshot.contract.market_id,
                       normalized.snapshot.contract.competition_id, output['result_kind'], output['non_evaluation_reason'],
                       probability, ev_ratio, output['reference_book_count'],
                       Json(document), _digest(document), Json(output), _digest(output)))
            inserted = cur.fetchone()
            if inserted:
                cur.executemany('''INSERT INTO corner.engine_evaluation_inputs
                    (evaluation_id, observation_id, role) VALUES (%s,%s,%s)''',
                    [(inserted['id'], q.observation_id,
                      'target' if q.observation_id == normalized.snapshot.target_observation_id else 'reference')
                     for q in normalized.snapshot.quotes])
                stored = dict(inserted)
            else:
                cur.execute('''SELECT * FROM corner.engine_evaluations
                    WHERE authority_kind=%s AND authority_id=%s AND evaluation_key=%s''', key)
                existing = cur.fetchone()
                if existing is None:
                    raise RuntimeError('retry transaction: concurrent command is outside snapshot')
                _check_command(existing, document)
                if bytes(existing['result_sha256']) != _digest(output) or existing['result_snapshot'] != output:
                    raise DeterminismFailure('same command produced a different result; original retained')
                stored = dict(existing)
            cur.execute('RELEASE SAVEPOINT corner_evaluation_write')
            return stored
        except Exception:
            cur.execute('ROLLBACK TO SAVEPOINT corner_evaluation_write')
            cur.execute('RELEASE SAVEPOINT corner_evaluation_write')
            raise
