"""Immutable captured-state assessment, NOT lifecycle application.

Capture reads trusted current state once. Persistence only validates immutable
references and the retained capture; it never reselects current state. Phase and
negative-selection assertions must originate in trusted internal adapters, not
untrusted API JSON. Caller owns READ COMMITTED commit/rollback.
"""

import hashlib
import json
import platform
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from functools import wraps
from pathlib import Path

from psycopg2.extras import Json, RealDictCursor

from corner import channels, evaluations as codec, lifecycle, qualifications
from corner.ev import QuoteInput


FORMAT_VERSION = 'corner.actionability/1'
CAPTURE_FORMAT = 'corner.actionability.capture/1'
BUILD = {
    'adapter_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'lifecycle_sha256': hashlib.sha256(Path(lifecycle.__file__).read_bytes()).hexdigest(),
    'serializer_sha256': hashlib.sha256(Path(codec.__file__).read_bytes()).hexdigest(),
    'python_version': platform.python_version(),
}
IMPLEMENTATION = lifecycle.ImplementationIdentity('corner.actionability', '1', 'sha256:' + codec._digest(BUILD).hex())


class AssessmentValidationError(ValueError):
    pass


class AssessmentConflict(ValueError):
    pass


class AssessmentDeterminismFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class AssessmentAuthority:
    kind: str
    identifier: str


@dataclass(frozen=True)
class AssessmentCommand:
    # Immutable selector output. Formatting is not identity; snapshot contents are.
    capture_json: str
    assessed_at: datetime
    context_json: str = '{}'


def _validation_boundary(function):
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (AssessmentValidationError, AssessmentConflict):
            raise
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            raise AssessmentValidationError('invalid or unsupported assessment evidence') from error
    return call


def _require(condition, message):
    if not condition:
        raise AssessmentValidationError(message)


def _row(cur, table, identity):
    # Table names are module constants, never caller strings.
    cur.execute(f'SELECT * FROM corner.{table} WHERE id=%s', (channels._uuid(identity),))
    row = cur.fetchone()
    _require(row is not None, f'missing {table} evidence')
    return dict(row)


def _verify(row, snapshot, digest):
    _require(codec._digest(row[snapshot]) == bytes(row[digest]), f'{snapshot} digest mismatch')


def _quote(doc):
    return QuoteInput(doc['observation_id'], doc['market_id'], doc['outcome_id'], doc['sportsbook_id'],
        Decimal(doc['decimal_odds']) if doc['decimal_odds'] is not None else None, doc['quote_state'],
        datetime.fromisoformat(doc['observed_at']),
        datetime.fromisoformat(doc['provider_updated_at']) if doc['provider_updated_at'] is not None else None)


def _evaluation(cur, identity):
    row = _row(cur, 'engine_evaluations', identity)
    _verify(row, 'command_snapshot', 'command_sha256')
    qualifications.validate_evaluation(row)
    command = codec.deserialize_command(row['command_snapshot'])
    doc = row['command_snapshot']
    _require(row['snapshot_format_version'] == codec.FORMAT_VERSION
             and all(row[key] == doc[key] for key in ('engine_name', 'engine_version', 'engine_revision'))
             and row['configuration_version'] == command.configuration.version
             and row['market_id'] == command.snapshot.contract.market_id
             and row['competition_id'] == command.snapshot.contract.competition_id,
             'evaluation identity projection mismatch')
    _require(command.snapshot.evaluated_at == row['evaluated_at']
             and command.snapshot.target_observation_id == row['target_observation_id'], 'evaluation projection mismatch')
    codec._validate_evidence(cur, command)  # Historical records only, never the trusted view.
    cur.execute('SELECT observation_id, role FROM corner.engine_evaluation_inputs WHERE evaluation_id=%s', (row['id'],))
    expected = {(q.observation_id, 'target' if q.observation_id == row['target_observation_id'] else 'reference')
                for q in command.snapshot.quotes}
    _require({(r['observation_id'], r['role']) for r in cur.fetchall()} == expected, 'evaluation input links mismatch')
    return row, command


def _load(cur, generation_id, qualification_id, watermark_id, basis_id):
    generation = _row(cur, 'qualification_channel_generations', generation_id)
    _verify(generation, 'configuration_snapshot', 'configuration_sha256')
    _verify(generation, 'registration_command_snapshot', 'registration_command_sha256')
    config = generation['configuration_snapshot']
    _require(config['snapshot_format_version'] == channels.CONFIGURATION_FORMAT
             and generation['snapshot_format_version'] == channels.CONFIGURATION_FORMAT, 'unsupported generation format')
    _require(generation['registration_command_snapshot']['configuration'] == config, 'generation snapshot mismatch')
    registration = generation['registration_command_snapshot']
    _require(registration['snapshot_format_version'] == channels.REGISTRATION_FORMAT
             and registration['channel_id'] == generation['channel_id']
             and registration['configuration_sha256'] == bytes(generation['configuration_sha256']).hex(),
             'generation registration binding mismatch')
    _require(config['lifecycle']['implementation'] == asdict(IMPLEMENTATION), 'unsupported actionability implementation')
    for part, prefix in (('engine', 'engine'), ('qualification', 'qualification'), ('lifecycle', 'lifecycle')):
        _require(all(config[part]['implementation'][field] == generation[prefix + '_' + field]
                     for field in ('name', 'version', 'revision')), 'generation identity projection mismatch')
    q = _row(cur, 'qualification_decisions', qualification_id)
    _require(q['decision_kind'] == 'qualified', 'assessment requires a qualified decision')
    _require(q['qualification_snapshot_format_version'] == qualifications.FORMAT_VERSION, 'unsupported qualification format')
    _verify(q, 'command_snapshot', 'command_sha256')
    _verify(q, 'result_snapshot', 'result_sha256')
    _require(q['result_snapshot']['decision_kind'] == 'qualified', 'qualification result projection mismatch')
    _require(q['command_snapshot']['qualification_snapshot_format_version'] == qualifications.FORMAT_VERSION
             and q['result_snapshot']['reason_code'] == q['reason_code']
             and q['command_snapshot']['decided_at'] == codec._encode(q['decided_at']), 'qualification command projection mismatch')
    evaluation, command = _evaluation(cur, q['engine_evaluation_id'])
    _require(bytes(evaluation['result_sha256']) == bytes(q['evaluation_result_sha256'])
             and q['command_snapshot']['evaluation_result_sha256'] == bytes(evaluation['result_sha256']).hex()
             and q['command_snapshot']['engine_evaluation_id'] == evaluation['id'], 'qualification evaluation binding mismatch')
    policy = q['command_snapshot']['policy']
    _require(codec._digest(policy).hex() == q['command_snapshot']['policy_sha256'], 'qualification policy digest mismatch')
    expected_policy = config['qualification']['configuration']
    _require({key: policy[key] for key in expected_policy} == expected_policy, 'qualification configuration mismatch')
    _require(policy['policy_name'] == q['policy_name'] == config['qualification']['implementation']['name']
             and policy['policy_version'] == q['policy_version']
             and policy['policy_revision'] == q['policy_revision'] == config['qualification']['implementation']['revision'],
             'qualification implementation mismatch')
    _require(q['result_snapshot']['engine_evaluation_id'] == evaluation['id']
             and q['result_snapshot']['evaluation_result_sha256'] == bytes(evaluation['result_sha256']).hex()
             and q['result_snapshot']['decided_at'] == q['command_snapshot']['decided_at']
             and all(q['result_snapshot'][key] == policy[key] for key in
                     ('policy_name', 'policy_version', 'policy_revision', 'minimum_ev_ratio', 'comparison'))
             and Decimal(q['result_snapshot']['compared_ev']) == Decimal(evaluation['result_snapshot']['ev_ratio']),
             'qualification result evidence mismatch')
    watermark, watermark_command = _evaluation(cur, watermark_id)
    for record in (evaluation, watermark):
        doc = record['command_snapshot']
        _require(config['engine']['implementation'] == {
            'name': doc['engine_name'], 'version': doc['engine_version'], 'revision': doc['engine_revision']}
            and config['engine']['configuration'] == doc['configuration'], 'engine configuration/implementation mismatch')
    quotes = {quote.observation_id: quote for quote in command.snapshot.quotes}
    target = quotes[evaluation['target_observation_id']]
    wm_target = next(quote for quote in watermark_command.snapshot.quotes if quote.observation_id == watermark['target_observation_id'])
    _require((target.outcome_id, target.sportsbook_id, target.market_id) ==
             (wm_target.outcome_id, wm_target.sportsbook_id, wm_target.market_id), 'watermark belongs to another condition')
    order = lifecycle.EvaluationOrder(evaluation['evaluated_at'], evaluation['id'])
    wm_order = lifecycle.EvaluationOrder(watermark['evaluated_at'], watermark['id'])
    _require(wm_order >= order, 'watermark is behind qualified evaluation')
    cur.execute('SELECT event_id FROM corner.markets WHERE id=%s', (target.market_id,))
    event_id = cur.fetchone()['event_id']
    cur.execute('SELECT code FROM corner.qualification_channels WHERE id=%s', (generation['channel_id'],))
    channel_code = cur.fetchone()['code']
    refs = []
    for estimate in evaluation['result_snapshot']['reference_estimates']:
        for observation_id in estimate['observation_ids']:
            _require(observation_id in quotes and quotes[observation_id].sportsbook_id == estimate['sportsbook_id'],
                     'contributing reference is not supplied evidence')
            refs.append(quotes[observation_id])
    condition = lifecycle.ConditionKey('positive_ev', target.sportsbook_id, target.outcome_id, channel_code)
    fact = lifecycle.EvaluationFact(order, condition, lifecycle.ImplementationIdentity(**config['engine']['implementation']),
        codec._digest(config['engine']['configuration']).hex(), event_id, evaluation['result_kind'], target, tuple(refs))
    qualified = lifecycle.QualificationFact(q['id'], generation['id'], fact,
        lifecycle.ImplementationIdentity(**config['qualification']['implementation']),
        codec._digest(expected_policy).hex(), 'qualified')
    if basis_id is not None:
        basis = _row(cur, 'actionability_assessments', basis_id)
        _verify(basis, 'command_snapshot', 'command_sha256')
        _verify(basis, 'result_snapshot', 'result_sha256')
        cur.execute('''SELECT e.target_observation_id, o.outcome_id, o.sportsbook_id
            FROM corner.qualification_decisions q JOIN corner.engine_evaluations e ON e.id=q.engine_evaluation_id
            JOIN corner.odds_observations o ON o.id=e.target_observation_id WHERE q.id=%s''', (basis['qualification_decision_id'],))
        b = cur.fetchone()
        _require(basis['channel_generation_id'] == generation['id']
                 and (b['outcome_id'], b['sportsbook_id']) == (target.outcome_id, target.sportsbook_id),
                 'basis assessment belongs to another condition/generation')
    ages = config['lifecycle']['configuration']
    policy = lifecycle.ActionabilityPolicy(IMPLEMENTATION, timedelta(microseconds=ages['target_max_age_microseconds']),
                                         timedelta(microseconds=ages['reference_max_age_microseconds']))
    bindings = {'generation_id': generation['id'], 'generation_sha256': bytes(generation['configuration_sha256']).hex(),
        'qualification_id': q['id'], 'qualification_result_sha256': bytes(q['result_sha256']).hex(),
        'evaluation_id': evaluation['id'], 'evaluation_result_sha256': bytes(evaluation['result_sha256']).hex(),
        'watermark_id': watermark['id'], 'watermark_evaluated_at': codec._encode(watermark['evaluated_at']),
        'watermark_result_sha256': bytes(watermark['result_sha256']).hex(),
        'basis_assessment_id': channels._uuid(basis_id) if basis_id is not None else None}
    return qualified, policy, wm_order, bindings


# All current-stream selection and missing-stream witnesses share ONE MVCC statement.
# A missing stream retains every currently recorded observation's latest rejection.
_CAPTURE_SQL = '''
WITH expected AS (SELECT * FROM unnest(%s::uuid[], %s::uuid[], %s::text[])
    AS e(outcome_id, sportsbook_id, stream_role))
SELECT statement_timestamp() AS captured_at, pg_current_snapshot()::text AS visibility_snapshot,
    e.*, q.observation_id, q.decimal_odds, s.code AS quote_state, q.observed_at, q.provider_updated_at,
    oc.market_id, q.latest_disposition_id, q.latest_disposition_code,
    q.disposition_decided_at, q.disposition_created_at,
    CASE WHEN q.observation_id IS NULL THEN (
        SELECT COALESCE(jsonb_agg(jsonb_build_object('observation_id', o.id,
            'disposition_id', d.id, 'disposition', k.code,
            'decided_at', d.decided_at, 'created_at', d.created_at) ORDER BY o.id), '[]'::jsonb)
        FROM corner.odds_observations o LEFT JOIN LATERAL (
            SELECT * FROM corner.observation_dispositions d WHERE d.observation_id=o.id
            ORDER BY d.decided_at DESC, d.id DESC LIMIT 1
        ) d ON TRUE LEFT JOIN corner.disposition_types k ON k.id=d.disposition_type_id
        WHERE o.outcome_id=e.outcome_id AND o.sportsbook_id=e.sportsbook_id
    ) ELSE '[]'::jsonb END AS missing_witnesses
FROM expected e JOIN corner.outcomes oc ON oc.id=e.outcome_id
LEFT JOIN corner.trusted_current_quotes q ON q.outcome_id=e.outcome_id AND q.sportsbook_id=e.sportsbook_id
LEFT JOIN corner.quote_states s ON s.id=q.quote_state_id
ORDER BY e.outcome_id, e.sportsbook_id
'''


def _trust(disposition_id, kind, decided_at, created_at):
    return {'disposition_id': disposition_id, 'disposition': kind,
            'decided_at': codec._encode(datetime.fromisoformat(decided_at) if isinstance(decided_at, str) else decided_at),
            'created_at': codec._encode(datetime.fromisoformat(created_at) if isinstance(created_at, str) else created_at)}


@_validation_boundary
def capture_assessment(conn, *, generation_id, qualification_decision_id, evaluation_watermark_id,
                       phase: lifecycle.PhaseEvidence, phase_provenance_json: str, basis_assessment_id=None):
    """Return immutable JSON capture; no persistence, clock cutoff or lifecycle action."""
    provenance = channels._context(phase_provenance_json)
    _require(isinstance(provenance.get('source'), str) and provenance['source'].strip(), 'phase provenance source required')
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        q, _, _, bindings = _load(cur, generation_id, qualification_decision_id, evaluation_watermark_id, basis_assessment_id)
        _require(phase.event_id == q.evaluation.event_id, 'phase evidence belongs to another event')
        expected = [('target', q.evaluation.target)] + [('reference', quote) for quote in q.evaluation.contributing_references]
        cur.execute(_CAPTURE_SQL, ([quote.outcome_id for _, quote in expected],
            [quote.sportsbook_id for _, quote in expected], [role for role, _ in expected]))
        rows = cur.fetchall()
    _require(len(rows) == len(expected), 'capture did not cover every expected stream')
    streams = []
    for row in rows:
        selected = row['observation_id'] is not None
        quote = QuoteInput(row['observation_id'], row['market_id'], row['outcome_id'], row['sportsbook_id'],
            row['decimal_odds'], row['quote_state'], row['observed_at'], row['provider_updated_at']) if selected else None
        witnesses = [{'observation_id': item['observation_id'], **_trust(item['disposition_id'], item['disposition'],
                      item['decided_at'], item['created_at'])} for item in row['missing_witnesses']]
        streams.append({'stream_role': row['stream_role'], 'outcome_id': row['outcome_id'], 'sportsbook_id': row['sportsbook_id'],
            'selection_kind': 'selected_trusted_observation' if selected else 'missing_trusted_observation',
            'quote': codec._encode(asdict(quote)) if quote else None,
            'trust': _trust(row['latest_disposition_id'], row['latest_disposition_code'],
                            row['disposition_decided_at'], row['disposition_created_at']) if selected else None,
            'missing_reason': None if selected else ('all_observations_rejected' if witnesses else 'no_observations'),
            'missing_witnesses': witnesses})
    return codec.canonical_json({'capture_format_version': CAPTURE_FORMAT, 'selector_revision': IMPLEMENTATION.revision,
        'snapshot_captured_at': codec._encode(rows[0]['captured_at']), 'visibility_snapshot': rows[0]['visibility_snapshot'],
        'bindings': bindings, 'phase': asdict(phase), 'phase_provenance': provenance, 'streams': streams})


def _document(command):
    capture = channels._context(command.capture_json)
    _require(capture.get('capture_format_version') == CAPTURE_FORMAT, 'unsupported capture format')
    _require(capture.get('selector_revision') == IMPLEMENTATION.revision, 'unsupported capture implementation')
    # Expected streams and rejection witnesses are sets; phase/context arrays are not.
    capture['streams'].sort(key=lambda s: (s['outcome_id'], s['sportsbook_id']))
    for stream in capture['streams']:
        stream['missing_witnesses'].sort(key=lambda w: w['observation_id'])
    assessed = codec._encode(command.assessed_at)
    captured = datetime.fromisoformat(capture['snapshot_captured_at'])
    _require(captured.tzinfo is not None and command.assessed_at >= captured, 'assessment cannot precede capture')
    return {'snapshot_format_version': FORMAT_VERSION, 'implementation': asdict(IMPLEMENTATION),
            'build': BUILD, 'capture': capture, 'assessed_at': assessed, 'context': channels._context(command.context_json)}


def _validate_streams(cur, capture, q):
    original_observations = {(quote.outcome_id, quote.sportsbook_id): quote.observation_id
        for quote in (q.evaluation.target,) + q.evaluation.contributing_references}
    expected = {(quote.outcome_id, quote.sportsbook_id): role for role, quote in
        [('target', q.evaluation.target)] + [('reference', quote) for quote in q.evaluation.contributing_references]}
    streams = capture['streams']
    _require(len(streams) == len(expected) and {(s['outcome_id'], s['sportsbook_id']) for s in streams} == set(expected),
             'every expected stream must be explicit exactly once')
    captured = datetime.fromisoformat(capture['snapshot_captured_at'])
    selected = []
    for stream in streams:
        slot = stream['outcome_id'], stream['sportsbook_id']
        _require(stream['stream_role'] == expected[slot], 'stream role mismatch')
        if stream['selection_kind'] == 'selected_trusted_observation':
            quote = _quote(stream['quote'])
            _require((quote.outcome_id, quote.sportsbook_id) == slot and quote.observed_at <= captured,
                     'selected observation has wrong stream/time')
            _require(stream['missing_reason'] is None and not stream['missing_witnesses'], 'selected stream cannot be missing')
            witnesses = [{'observation_id': quote.observation_id, **stream['trust']}]
            selected.append(quote)
        else:
            _require(stream['selection_kind'] == 'missing_trusted_observation' and stream['quote'] is None
                     and stream['trust'] is None, 'invalid selection kind/shape')
            witnesses = stream['missing_witnesses']
            _require(stream['missing_reason'] == ('all_observations_rejected' if witnesses else 'no_observations'),
                     'invalid missing-stream reason')
            _require(len({w['observation_id'] for w in witnesses}) == len(witnesses), 'duplicate missing evidence')
            # Every expected v1 stream was observed in the qualified evaluation.
            # A missing stream must at least explain why that known evidence is rejected.
            _require(original_observations[slot] in {w['observation_id'] for w in witnesses},
                     'missing-stream evidence omits rejection of evaluated observation')
        for witness in witnesses:
            obs = _row(cur, 'odds_observations', witness['observation_id'])
            _require((obs['outcome_id'], obs['sportsbook_id']) == slot and obs['created_at'] <= captured,
                     'observation does not support captured stream')
            if stream['quote'] is not None:
                cur.execute('''SELECT oc.market_id, s.code FROM corner.outcomes oc
                    JOIN corner.quote_states s ON s.id=%s WHERE oc.id=%s''', (obs['quote_state_id'], obs['outcome_id']))
                meta = cur.fetchone()
                actual = QuoteInput(obs['id'], meta['market_id'], obs['outcome_id'], obs['sportsbook_id'],
                    obs['decimal_odds'], meta['code'], obs['observed_at'], obs['provider_updated_at'])
                _require(actual == quote, 'selected quote contradicts immutable observation')
            did = witness['disposition_id']
            if did is None:
                _require(stream['quote'] is not None and all(witness[key] is None for key in ('disposition', 'decided_at', 'created_at')),
                         'missing streams require rejection evidence')
            else:
                disposition = _row(cur, 'observation_dispositions', did)
                cur.execute('SELECT code FROM corner.disposition_types WHERE id=%s', (disposition['disposition_type_id'],))
                kind = cur.fetchone()['code']
                actual = _trust(did, kind, disposition['decided_at'], disposition['created_at'])
                _require(disposition['observation_id'] == obs['id'] and disposition['created_at'] <= captured
                         and actual == {key: witness[key] for key in actual}, 'disposition evidence mismatch')
                _require(kind == ('reinstated' if stream['quote'] is not None else 'rejected'), 'invalid captured eligibility')
    return tuple(selected)


def _compute(cur, document):
    capture = document['capture']
    b = capture['bindings']
    q, policy, watermark, actual = _load(cur, b['generation_id'], b['qualification_id'], b['watermark_id'], b['basis_assessment_id'])
    _require(actual == b, 'captured upstream bindings mismatch')
    channels._text(capture['phase_provenance'].get('source'))
    quotes = _validate_streams(cur, capture, q)
    phase = lifecycle.PhaseEvidence(**capture['phase'])
    request = lifecycle.AssessmentRequest('unpersisted-assessment', b['generation_id'],
        datetime.fromisoformat(document['assessed_at']), watermark, b['qualification_id'], b['basis_assessment_id'], quotes, phase)
    result = lifecycle.assess_actionability(request, q, policy)
    target_present = any(s['stream_role'] == 'target' and s['quote'] is not None for s in capture['streams'])
    return {'actionable': result.actionable, 'primary_reason': result.reasons[0] if result.reasons else None,
        'reasons': list(result.reasons),
        'target_deadline': codec._encode(result.target_deadline) if target_present else None,
        'evaluated_target_deadline': codec._encode(result.target_deadline),
        'reference_deadlines': [{'observation_id': oid, 'deadline': codec._encode(when)}
                                for oid, when in sorted(result.reference_deadlines)],
        'deadline_basis': 'evaluated_observations', 'implementation': asdict(IMPLEMENTATION)}


def _retry(row, document):
    _require(row is not None, 'concurrent row outside snapshot; retry transaction')
    if bytes(row['command_sha256']) != codec._digest(document) or row['command_snapshot'] != document:
        raise AssessmentConflict('assessment key identifies a different captured command')
    return dict(row)


@_validation_boundary
def record_assessment(conn, *, authority: AssessmentAuthority, assessment_key: str, command: AssessmentCommand):
    key = channels._authority(authority, assessment_key)
    try:
        document = _document(command)
        with channels._write(conn, 'corner_assessment_write') as cur:
            cur.execute('''SELECT * FROM corner.actionability_assessments
                WHERE authority_kind=%s AND authority_id=%s AND assessment_key=%s''', key)
            existing = cur.fetchone()
            if existing is not None:
                return _retry(existing, document)  # No selection, validation requery, or computation on exact retry.
            output = _compute(cur, document)
            capture, b = document['capture'], document['capture']['bindings']
            cur.execute('''INSERT INTO corner.actionability_assessments
                (channel_generation_id, qualification_decision_id, evaluation_watermark_id, basis_assessment_id,
                 snapshot_captured_at, assessed_at, authority_kind, authority_id, assessment_key,
                 implementation_name, implementation_version, implementation_revision, snapshot_format_version,
                 actionable, primary_reason, target_deadline, command_snapshot, command_sha256, result_snapshot, result_sha256)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT ON CONSTRAINT actionability_assessments_command_key DO NOTHING RETURNING *''',
                (b['generation_id'], b['qualification_id'], b['watermark_id'], b['basis_assessment_id'],
                 capture['snapshot_captured_at'], command.assessed_at) + key
                + (IMPLEMENTATION.name, IMPLEMENTATION.version, IMPLEMENTATION.revision, FORMAT_VERSION,
                   output['actionable'], output['primary_reason'], output['target_deadline'], Json(document),
                   codec._digest(document), Json(output), codec._digest(output)))
            inserted = cur.fetchone()
            if inserted is not None:
                for stream in capture['streams']:
                    quote, trust = stream['quote'], stream['trust']
                    cur.execute('''INSERT INTO corner.assessment_stream_evidence
                        (assessment_id, stream_role, sportsbook_id, outcome_id, selection_kind,
                         selected_observation_id, selected_disposition_id, missing_reason, evidence_snapshot)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                        (inserted['id'], stream['stream_role'], stream['sportsbook_id'], stream['outcome_id'],
                         stream['selection_kind'], quote['observation_id'] if quote else None,
                         trust['disposition_id'] if trust else None, stream['missing_reason'], Json(stream)))
                return dict(inserted)
            cur.execute('''SELECT * FROM corner.actionability_assessments
                WHERE authority_kind=%s AND authority_id=%s AND assessment_key=%s''', key)
            stored = _retry(cur.fetchone(), document)
            if bytes(stored['result_sha256']) != codec._digest(output) or stored['result_snapshot'] != output:
                raise AssessmentDeterminismFailure('same captured command produced different result; original retained')
            return stored
    except (KeyError, TypeError, qualifications.QualificationValidationError) as error:
        raise AssessmentValidationError('malformed assessment/upstream evidence') from error
