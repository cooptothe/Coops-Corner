"""V2 assessment capture/ledger over exact conditional evaluations.

Fresh authorization is acquired only at capture. Execution/replay validate the
retained proof and immutable ledgers, never current quotes or current approvals.
"""
from dataclasses import asdict
from datetime import datetime, timedelta
import hashlib
from pathlib import Path
from uuid import uuid4

from psycopg2.extras import Json, RealDictCursor

from corner import actionability_v2 as policy, analytics_versions as analytics
from corner import assessments as old, capture_authority as authority, channels
from corner import evaluation_capture_v2 as evaluation_capture, evaluations as codec
from corner import lifecycle, qualifications, work

FORMAT = policy.FORMAT
CAPTURE_FORMAT = policy.CAPTURE_FORMAT
IMPLEMENTATION = policy.IMPLEMENTATION
REVISION = 'sha256:' + codec._digest({'source': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'policy': IMPLEMENTATION.revision, 'capture': evaluation_capture.REVISION}).hex()
require = authority.require
AssessmentCommand = old.AssessmentCommand


def generation(cur, identity):
    row = old._row(cur, 'qualification_channel_generations', identity)
    old._verify(row, 'configuration_snapshot', 'configuration_sha256')
    old._verify(row, 'registration_command_snapshot', 'registration_command_sha256')
    doc = row['configuration_snapshot']
    config = evaluation_capture._decode_configuration(doc)
    require(row['snapshot_format_version'] == evaluation_capture.CHANNEL_FORMAT
        and row['registration_command_snapshot']['snapshot_format_version'] == evaluation_capture.REGISTRATION_FORMAT
        and row['registration_command_snapshot']['configuration'] == doc
        and row['registration_command_snapshot']['channel_id'] == row['channel_id']
        and row['registration_command_snapshot']['configuration_sha256'] == bytes(row['configuration_sha256']).hex(),
        'generation registration mismatch')
    require(config.analytics.actionability_policy.identity == IMPLEMENTATION, 'generation is not v2-assessment compatible')
    for part in ('engine', 'qualification', 'lifecycle'):
        require(all(row[part + '_' + k] == doc[part]['implementation'][k] for k in ('name', 'version', 'revision')),
                'generation projection mismatch')
    return row, config


def evaluation(cur, identity, key):
    row = old._row(cur, 'engine_evaluations', identity)
    old._verify(row, 'command_snapshot', 'command_sha256')
    analytics.decode_evaluation(row)
    require(row['snapshot_format_version'] == analytics.EVALUATION_FORMAT, 'v2 evaluation required')
    command = analytics.deserialize_command(row['command_snapshot'])
    doc = row['command_snapshot']
    require(all(row[k] == doc[k] for k in ('engine_name', 'engine_version', 'engine_revision'))
        and row['configuration_version'] == command.configuration.version
        and row['evaluated_at'] == command.snapshot.evaluated_at
        and row['target_observation_id'] == command.snapshot.target_observation_id
        and row['market_id'] == command.snapshot.contract.market_id
        and row['competition_id'] == command.snapshot.contract.competition_id, 'evaluation projection mismatch')
    codec._validate_evidence(cur, command)
    cur.execute('SELECT observation_id,role FROM corner.engine_evaluation_inputs WHERE evaluation_id=%s', (row['id'],))
    require({(r['observation_id'], r['role']) for r in cur.fetchall()} == {
        (q.observation_id, 'target' if q.observation_id == row['target_observation_id'] else 'reference')
        for q in command.snapshot.quotes}, 'evaluation input links mismatch')
    quotes = {q.observation_id: q for q in command.snapshot.quotes}
    target = quotes[row['target_observation_id']]
    require((target.outcome_id, target.sportsbook_id) == (key.outcome_id, key.target_sportsbook_id), 'evaluation condition mismatch')
    refs = []
    for estimate in row['result_snapshot']['reference_estimates']:
        for oid in estimate['observation_ids']:
            require(oid in quotes and quotes[oid].sportsbook_id == estimate['sportsbook_id'], 'invalid contributing evidence')
            refs.append(quotes[oid])
    cur.execute('SELECT event_id FROM corner.markets WHERE id=%s', (row['market_id'],))
    fact = lifecycle.EvaluationFact(lifecycle.EvaluationOrder(row['evaluated_at'], row['id']), key,
        lifecycle.ImplementationIdentity(row['engine_name'], row['engine_version'], row['engine_revision']),
        codec._digest(doc['configuration']).hex(), cur.fetchone()['event_id'], row['result_kind'], target, tuple(refs))
    return row, command, fact


def qualification(cur, identity, generation_id, key):
    q = old._row(cur, 'qualification_decisions', identity)
    old._verify(q, 'command_snapshot', 'command_sha256'); old._verify(q, 'result_snapshot', 'result_sha256')
    doc = q['command_snapshot']
    require(q['qualification_snapshot_format_version'] == analytics.QUALIFICATION_FORMAT
        and doc['qualification_snapshot_format_version'] == analytics.QUALIFICATION_FORMAT, 'unsupported qualification version')
    row, command, fact = evaluation(cur, q['engine_evaluation_id'], key)
    gen, config = generation(cur, generation_id)
    expected_policy = analytics.qualification_policy_snapshot(config.analytics.qualification_policy)
    require(doc['policy'] == expected_policy and doc['policy_sha256'] == codec._digest(expected_policy).hex(),
            'qualification policy mismatch')
    require(doc['engine_evaluation_id'] == row['id'] and doc['evaluation_snapshot_format_version'] == analytics.EVALUATION_FORMAT
        and doc['evaluation_result_sha256'] == bytes(row['result_sha256']).hex()
        and bytes(q['evaluation_result_sha256']) == bytes(row['result_sha256'])
        and doc['decided_at'] == codec._encode(q['decided_at'])
        and all(q[k] == expected_policy[k] for k in ('policy_name', 'policy_version', 'policy_revision')),
        'qualification binding/projection mismatch')
    judgment = analytics.qualify_evaluation(row, config.analytics.qualification_policy)
    expected_result = qualifications._result_snapshot(judgment, doc) | {'calculation_basis': analytics.v2.BASIS}
    require(q['result_snapshot'] == expected_result and q['decision_kind'] == judgment.decision_kind
        and q['reason_code'] == judgment.reason_code, 'qualification result mismatch')
    require(command.configuration == config.analytics.engine_configuration, 'qualified evaluation generation mismatch')
    qualified = lifecycle.QualificationFact(q['id'], gen['id'], fact, analytics.QUALIFIER,
        codec._digest(expected_policy).hex(), q['decision_kind'])
    return q, row, command, qualified, config


def load(cur, generation_id, qualification_id, watermark_id, basis_id):
    qrow = old._row(cur, 'qualification_decisions', qualification_id)
    genrow, config = generation(cur, generation_id)
    erow = old._row(cur, 'engine_evaluations', qrow['engine_evaluation_id'])
    cur.execute('SELECT outcome_id,sportsbook_id FROM corner.odds_observations WHERE id=%s', (erow['target_observation_id'],))
    target = cur.fetchone()
    channel = old._row(cur, 'qualification_channels', genrow['channel_id'])
    key = lifecycle.ConditionKey('positive_ev', target['sportsbook_id'], target['outcome_id'], channel['code'])
    qrow, erow, command, qualified, config = qualification(cur, qualification_id, generation_id, key)
    require(qualified.decision_kind == 'qualified', 'assessment requires qualified judgment')
    wmrow, wmcommand, watermark = evaluation(cur, watermark_id, key)
    require(watermark.order >= qualified.evaluation.order and wmcommand.configuration == command.configuration,
            'watermark chronology/configuration mismatch')
    if basis_id:
        basis = old._row(cur, 'actionability_assessments', basis_id)
        old._verify(basis, 'command_snapshot', 'command_sha256'); old._verify(basis, 'result_snapshot', 'result_sha256')
        require(basis['snapshot_format_version'] == FORMAT and basis['channel_generation_id'] == generation_id,
                'basis assessment version/generation mismatch')
        basis_key = basis['command_snapshot']['capture']['condition']
        require(basis_key == asdict(key), 'basis assessment condition mismatch')
    bindings = {'generation_id': generation_id, 'generation_sha256': bytes(genrow['configuration_sha256']).hex(),
        'qualification_id': qrow['id'], 'qualification_result_sha256': bytes(qrow['result_sha256']).hex(),
        'evaluation_id': erow['id'], 'evaluation_result_sha256': bytes(erow['result_sha256']).hex(),
        'watermark_id': wmrow['id'], 'watermark_evaluated_at': codec._encode(wmrow['evaluated_at']),
        'watermark_result_sha256': bytes(wmrow['result_sha256']).hex(), 'basis_assessment_id': basis_id}
    return qualified, config, erow, bindings


def _inventories(catalog, authority_policy, binding, books, at):
    common = {'competition_id': binding['competition_id'], 'jurisdiction': authority_policy['jurisdiction'],
              'offering': authority_policy['offering'], 'event_id': binding['event_id']}
    scopes = {'phase': common | {'kind': 'phase'}} | {b: common | {'kind': 'settlement', 'sportsbook_id': b,
        'market_id': binding['market_id'], 'market_type': binding['market_type'], 'scope': binding['scope'],
        'outcome_ids': binding['outcome_ids']} for b in books}
    result = {}
    for stream, scope in scopes.items():
        artifacts, _ = policy._artifacts(catalog, authority_policy, scope['kind'], scope)
        sources = {a['source_id'] for a in artifacts}
        if stream == 'phase': sources |= {s['authority'] for s in authority_policy['phase_validation_policy']['sources']}
        result[stream] = authority.inventory(catalog, scope, sources, at)
    return result


def capture_assessment(conn, *, generation_id, qualification_decision_id, evaluation_watermark_id, source=None,
                       basis_assessment_id=None):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        q, config, historical, bindings = load(cur, generation_id, qualification_decision_id, evaluation_watermark_id, basis_assessment_id)
        if config.authority.document['environment'] != 'synthetic' or source is None:
            raise authority.UnmetPrerequisite('production_assessment_authority_not_installed')
        require(type(source) is authority.SyntheticEvidenceStore, 'unsupported assessment loader')
        binding = evaluation_capture._binding(cur, q.evaluation.target.outcome_id)
        expected = [('target', q.evaluation.target)] + [('reference', quote) for quote in q.evaluation.contributing_references]
        cur.execute(old._CAPTURE_SQL, ([quote.outcome_id for _, quote in expected],
            [quote.sportsbook_id for _, quote in expected], [role for role, _ in expected]))
        rows = cur.fetchall()
    require(len(rows) == len(expected), 'incomplete trusted stream capture')
    streams = []
    for row in rows:
        selected = row['observation_id'] is not None
        quote = ev_quote(row) if selected else None
        witnesses = [{'observation_id': item['observation_id'], **old._trust(item['disposition_id'], item['disposition'],
            item['decided_at'], item['created_at'])} for item in row['missing_witnesses']]
        streams.append({'stream_role': row['stream_role'], 'outcome_id': row['outcome_id'], 'sportsbook_id': row['sportsbook_id'],
            'selection_kind': 'selected_trusted_observation' if selected else 'missing_trusted_observation',
            'quote': codec._encode(asdict(quote)) if quote else None,
            'trust': old._trust(row['latest_disposition_id'], row['latest_disposition_code'], row['disposition_decided_at'],
                                row['disposition_created_at']) if selected else None,
            'missing_reason': None if selected else ('all_observations_rejected' if witnesses else 'no_observations'),
            'missing_witnesses': witnesses})
    captured_at = rows[0]['captured_at']
    catalog = source.capture(captured_at)
    decoded_catalog = authority._catalog(catalog, captured_at)
    books = sorted({quote.sportsbook_id for _, quote in expected})
    capture = {'capture_format_version': CAPTURE_FORMAT, 'implementation': asdict(IMPLEMENTATION), 'adapter_revision': REVISION,
        'snapshot_captured_at': codec._encode(captured_at), 'visibility_snapshot': rows[0]['visibility_snapshot'],
        'bindings': bindings, 'condition': asdict(q.evaluation.condition), 'streams': streams,
        'expected_observations': sorted(codec._encode([asdict(quote) for _, quote in expected]), key=lambda v: v['observation_id']),
        'historical_basis': policy.historical_basis(historical), 'canonical_binding': binding,
        'authority_policy': config.authority.document, 'catalog': catalog,
        'assertion_ids': {'phase': str(uuid4()), **{book: str(uuid4()) for book in books}},
        'inventories': _inventories(decoded_catalog, config.authority.document, binding, books, captured_at)}
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        assessed_at = work._now(cur)  # Actual completion of capture; NEVER a past deadline.
    capture['authorization'] = policy.authorization(capture, assessed_at)
    return AssessmentCommand(codec.canonical_json(capture), assessed_at)


def ev_quote(row):
    from corner.ev import QuoteInput
    return QuoteInput(row['observation_id'], row['market_id'], row['outcome_id'], row['sportsbook_id'], row['decimal_odds'],
                      row['quote_state'], row['observed_at'], row['provider_updated_at'])


def document(command):
    capture = channels._context(command.capture_json)
    require(capture['capture_format_version'] == CAPTURE_FORMAT and capture['adapter_revision'] == REVISION,
            'unsupported assessment capture adapter/format')
    capture['streams'].sort(key=lambda s: (s['outcome_id'], s['sportsbook_id']))
    for stream in capture['streams']: stream['missing_witnesses'].sort(key=lambda w: w['observation_id'])
    return {'snapshot_format_version': FORMAT, 'implementation': asdict(IMPLEMENTATION), 'adapter_revision': REVISION,
            'capture': capture, 'assessed_at': codec._encode(command.assessed_at), 'context': channels._context(command.context_json)}


def compute(cur, doc):
    require(doc['snapshot_format_version'] == FORMAT and doc['implementation'] == asdict(IMPLEMENTATION)
            and doc['adapter_revision'] == REVISION, 'unsupported assessment implementation/format')
    cap = doc['capture']; b = cap['bindings']
    q, config, historical, actual = load(cur, b['generation_id'], b['qualification_id'], b['watermark_id'], b['basis_assessment_id'])
    require(actual == b and cap['historical_basis'] == policy.historical_basis(historical)
            and cap['authority_policy'] == config.authority.document and cap['condition'] == asdict(q.evaluation.condition),
            'assessment historical/configuration bindings mismatch')
    analytical = analytics.deserialize_command(historical['command_snapshot'])
    binding, contract = cap['canonical_binding'], analytical.snapshot.contract
    require(binding['event_id'] == q.evaluation.event_id and binding['market_id'] == contract.market_id
        and binding['competition_id'] == contract.competition_id and binding['market_type'] == contract.market_type
        and binding['scope'] == contract.scope
        and binding['outcome_ids'] == sorted(o.outcome_id for o in contract.outcomes), 'canonical assertion binding mismatch')
    for provider_id, external_id in binding['provider_identities']:
        cur.execute('SELECT 1 FROM corner.event_provider_identities WHERE event_id=%s AND provider_id=%s AND external_id=%s',
                    (binding['event_id'], provider_id, external_id))
        require(cur.fetchone() is not None, 'unknown retained event provider identity')
    old._validate_streams(cur, cap, q)  # Checks immutable evidence, not current selection.
    output = policy.assess(cap, datetime.fromisoformat(doc['assessed_at']), q, config.analytics.actionability_policy)
    require(codec.canonical_json(output['authority']) == codec.canonical_json(cap['authorization']),
            'frozen authorization assertions/resolutions mismatch')
    # Normalize nested tuple/list representations before JSONB round trips and
    # concurrent determinism comparisons; the semantic JSON is the contract.
    return channels._context(codec.canonical_json(output)), q, config.analytics.actionability_policy


def record_assessment(conn, *, authority: old.AssessmentAuthority, assessment_key, command):
    key = channels._authority(authority, assessment_key)
    doc = document(command)
    fields = ('authority_kind', 'authority_id', 'assessment_key')
    with channels._write(conn, 'corner_v2_assessment') as cur:
        existing = analytics._existing(cur, 'actionability_assessments', fields, key, doc)
        if existing: return existing
        output, _, _ = compute(cur, doc)
        cap = doc['capture']; b = cap['bindings']
        values = dict(zip(fields, key)) | dict(channel_generation_id=b['generation_id'], qualification_decision_id=b['qualification_id'],
            evaluation_watermark_id=b['watermark_id'], basis_assessment_id=b['basis_assessment_id'],
            snapshot_captured_at=cap['snapshot_captured_at'], assessed_at=command.assessed_at,
            implementation_name=IMPLEMENTATION.name, implementation_version=IMPLEMENTATION.version,
            implementation_revision=IMPLEMENTATION.revision, snapshot_format_version=FORMAT,
            actionable=output['actionable'], primary_reason=output['primary_reason'], target_deadline=output['target_deadline'],
            command_snapshot=Json(doc), command_sha256=codec._digest(doc), result_snapshot=Json(output), result_sha256=codec._digest(output))
        row, inserted = analytics._insert(cur, 'actionability_assessments', values, fields, key, doc)
        if inserted:
            for stream in cap['streams']:
                quote, trust = stream['quote'], stream['trust']
                cur.execute('''INSERT INTO corner.assessment_stream_evidence
                    (assessment_id,stream_role,sportsbook_id,outcome_id,selection_kind,selected_observation_id,
                     selected_disposition_id,missing_reason,evidence_snapshot) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                    (row['id'], stream['stream_role'], stream['sportsbook_id'], stream['outcome_id'], stream['selection_kind'],
                     quote['observation_id'] if quote else None, trust['disposition_id'] if trust else None,
                     stream['missing_reason'], Json(stream)))
        return row


def read_fact(cur, identity):
    row = old._row(cur, 'actionability_assessments', identity)
    old._verify(row, 'command_snapshot', 'command_sha256'); old._verify(row, 'result_snapshot', 'result_sha256')
    require(row['snapshot_format_version'] == FORMAT, 'unsupported v2 assessment format')
    output, q, policy_config = compute(cur, row['command_snapshot'])
    require(output == row['result_snapshot'], 'assessment result mismatch')
    doc, cap = row['command_snapshot'], row['command_snapshot']['capture']; b = cap['bindings']
    require(row['channel_generation_id'] == b['generation_id'] and row['qualification_decision_id'] == b['qualification_id']
        and row['evaluation_watermark_id'] == b['watermark_id'] and row['basis_assessment_id'] == b['basis_assessment_id']
        and codec._encode(row['snapshot_captured_at']) == cap['snapshot_captured_at']
        and codec._encode(row['assessed_at']) == doc['assessed_at'] and row['actionable'] == output['actionable']
        and row['primary_reason'] == output['primary_reason']
        and codec._encode(row['target_deadline']) == output['target_deadline']
        and (row['implementation_name'],row['implementation_version'],row['implementation_revision']) ==
            (IMPLEMENTATION.name, IMPLEMENTATION.version, IMPLEMENTATION.revision), 'assessment projection mismatch')
    cur.execute('SELECT evidence_snapshot FROM corner.assessment_stream_evidence WHERE assessment_id=%s ORDER BY outcome_id,sportsbook_id', (identity,))
    require([r['evidence_snapshot'] for r in cur.fetchall()] == cap['streams'], 'assessment stream links mismatch')
    request = lifecycle.AssessmentRequest(row['id'], b['generation_id'], row['assessed_at'],
        lifecycle.EvaluationOrder(datetime.fromisoformat(b['watermark_evaluated_at']), b['watermark_id']),
        q.id, b['basis_assessment_id'], tuple(old._quote(s['quote']) for s in cap['streams'] if s['quote']),
        lifecycle.PhaseEvidence(cap['assertion_ids']['phase'], q.evaluation.event_id, 'retained_v2', 'explicit v2 authorization proof'))
    return lifecycle.ActionabilityAssessment(request, policy_config, q, datetime.fromisoformat(output['evaluated_target_deadline']),
        tuple((d['observation_id'], datetime.fromisoformat(d['deadline'])) for d in output['reference_deadlines']), tuple(output['reasons']))
