"""Bounded discovery-only reconciliation. No capture, preparation or execution.

Caller owns a short READ COMMITTED transaction and commits the returned requests.
Each cursor is temporary UUID traversal state, scoped to its sweep/partition; an
exhausted page returns None so the next call starts a new pass. Never use it as a
commit watermark. Domain validation failures are isolated per candidate. Database
and programming failures propagate so callers roll back/retry the transaction.
"""
from decimal import Decimal

from psycopg2.extras import RealDictCursor

from corner import assessments as a, channels as ch, evaluations as ev
from corner import lifecycle_store as ls, qualifications as q, work as w

ROUTING_VERSION = 'corner.evaluation.routing/1'
NAMESPACES = {
    'qualification': 'reconcile.qualification.v1',
    'occurrence': 'reconcile.occurrence.v1',
    'activation': 'reconcile.activation.v1',
}


class ReconciliationError(ValueError):
    """Invalid routing, corrupt evidence or inconsistent completion proof."""


def _require(ok, message):
    if not ok:
        raise ReconciliationError(message)


def evaluation_route(*, outcome_id, sportsbook_id):
    """Intent supplied by an explicit evaluation producer, never inferred later."""
    return {'routing_version': ROUTING_VERSION, 'target_scope': {
        'outcome_id': ch._uuid(outcome_id), 'sportsbook_id': ch._uuid(sportsbook_id)}}


def _qualification(cur, row):
    """Validate an existing judgment; do not create one or recalculate EV."""
    a._verify(row, 'command_snapshot', 'command_sha256')
    a._verify(row, 'result_snapshot', 'result_sha256')
    doc = row['command_snapshot']
    _require(row['qualification_snapshot_format_version'] == q.FORMAT_VERSION,
             'unsupported qualification format')
    evaluation, _ = a._evaluation(cur, row['engine_evaluation_id'])
    policy = q.MinimumEVPolicy(doc['policy']['policy_version'], Decimal(doc['policy']['minimum_ev_ratio']))
    command = q.QualificationCommand(evaluation['id'], policy, row['decided_at'], ev.canonical_json(doc['context']))
    _require(q._command_snapshot(command, evaluation) == doc, 'qualification command/evidence mismatch')
    _require(bytes(row['evaluation_result_sha256']) == bytes(evaluation['result_sha256']),
             'qualification evaluation digest mismatch')
    _require(all(row[k] == doc['policy'][k] for k in ('policy_name', 'policy_version', 'policy_revision')),
             'qualification policy projection mismatch')
    result = q._result_snapshot(q.qualify_evaluation(evaluation, policy), doc)
    _require(result == row['result_snapshot'] and all(row[k] == result[k] for k in ('decision_kind', 'reason_code')),
             'qualification contradicts immutable evaluation/policy')
    return doc


def _request(conn, cur, obligation, identity, kind, sources, intent):
    namespace = NAMESPACES[obligation]
    key = ev.canonical_json(identity)
    # Serialize only competing discoveries of this obligation. Namespace is
    # reserved to this reconciler; hash collisions merely serialize extra work.
    lock = int.from_bytes(ev._digest([namespace, key])[:8], 'big', signed=True)
    cur.execute('SELECT pg_advisory_xact_lock(%s)', (lock,))
    cur.execute('SELECT id FROM corner.work_requests WHERE deduplication_namespace=%s AND deduplication_key=%s',
                (namespace, key))
    existed = cur.fetchone() is not None
    request = w.enqueue(conn, kind=kind, namespace=namespace, key=key,
                        sources=sources, intent_json=ev.canonical_json(intent))
    execution = w.load_execution(conn, request_id=request['id'])
    _require(execution is not None, 'request has no execution record')
    # A concurrent domain writer may satisfy an obligation after its initial
    # check. Restart proof on the next sweep; do not label that race corruption.
    if execution['status'] == 'completed':
        return {'status': 'recheck', 'request_id': request['id']}
    return {'status': 'blocked' if execution['status'] == 'blocked' else
            ('pending' if existed else 'newly_requested'), 'request_id': request['id']}


def _evaluation_obligation(conn, cur, identity):
    request = w._request(cur, identity)
    execution = w.load_execution(conn, request_id=identity)
    _require(request['work_kind'] == 'evaluate' and execution and execution['status'] == 'completed',
             'routing requires completed evaluate work')
    _require(request['condition_id'] and request['generation_id'], 'unrouted evaluation: missing condition/generation')
    condition, key = ls._condition(cur, request['condition_id'])
    route = evaluation_route(outcome_id=condition['outcome_id'], sportsbook_id=condition['target_sportsbook_id'])
    intent = request['intent_snapshot']['intent']
    _require(all(intent.get(k) == value for k, value in route.items()), 'unrouted/unsupported evaluation route')
    generation = ls._generation(cur, request['generation_id'], condition)
    prepared = w._prepared(cur, identity)
    w._bind(cur, request, prepared['command_snapshot'])
    evaluation_id = execution['engine_evaluation_id']
    fact = ls._evaluation(cur, evaluation_id, key)
    _require(fact.engine == generation.engine and fact.configuration_identity == generation.engine_configuration_identity,
             'evaluation incompatible with assigned generation')
    config = a._row(cur, 'qualification_channel_generations', generation.id)['configuration_snapshot']['qualification']
    _require(config['implementation'] == {'name': 'minimum_ev', 'version': '1', 'revision': q.POLICY_REVISION},
             'assigned qualification implementation unavailable')
    cur.execute('SELECT * FROM corner.qualification_decisions WHERE engine_evaluation_id=%s ORDER BY id', (evaluation_id,))
    decisions = cur.fetchall()
    matches = []
    for decision in decisions:
        # Both typed identity and snapshot identity can signal an intended match;
        # neither may hide contradictory/corrupt representations of this policy.
        doc_policy = decision['command_snapshot'].get('policy', {})
        policy = config['configuration']
        if ((decision['policy_name'], decision['policy_version'], decision['policy_revision']) !=
                (policy['policy_name'], policy['policy_version'], config['implementation']['revision'])
                and not all(doc_policy.get(k) == v for k, v in policy.items())):
            continue
        doc = _qualification(cur, decision)
        if all(doc['policy'][k] == value for k, value in policy.items()):
            matches.append(decision)
    _require(len({r['decision_kind'] for r in matches}) <= 1, 'contradictory authoritative qualifications')
    if matches:
        return {'status': 'fulfilled', 'result_id': matches[0]['id']}
    return _request(conn, cur, 'qualification', [condition['id'], generation.id, evaluation_id], 'qualify',
                    {'condition_id': condition['id'], 'generation_id': generation.id, 'engine_evaluation_id': evaluation_id},
                    {'routing_version': ROUTING_VERSION, 'qualification': config})


def _occurrence_obligation(conn, cur, identity):
    decision = a._row(cur, 'qualification_decisions', identity)
    _qualification(cur, decision)
    _require(decision['decision_kind'] == 'qualified', 'occurrence requires qualified decision')
    cur.execute('SELECT * FROM corner.opportunity_occurrences WHERE qualification_decision_id=%s', (identity,))
    occurrence = cur.fetchone()
    if occurrence:
        _require(occurrence['qualification_decision_kind'] == 'qualified', 'invalid occurrence binding')
        return {'status': 'fulfilled', 'result_id': occurrence['id']}
    return _request(conn, cur, 'occurrence', [identity], 'ensure_occurrence',
                    {'qualification_decision_id': identity}, {})


def _activation(cur, row, condition, key):
    command = ls.ApplicationCommand(condition['id'], 'generation_activation', row['id'],
                                    row['new_generation_id'], row['activated_at'])
    ls._input(cur, ls._document(command), condition, key)  # validates immutable activation/generation evidence


def _activation_obligation(conn, cur, identity):
    condition, key = ls._condition(cur, identity)
    cur.execute('SELECT * FROM corner.lifecycle_applications WHERE condition_id=%s ORDER BY application_sequence DESC LIMIT 1',
                (identity,))
    head = cur.fetchone()
    previous = None
    if head:
        post = ls._verify_receipt(cur, head)['post_state']
        previous = a._row(cur, 'channel_generation_activations', post['activation_id'])
        _activation(cur, previous, condition, key)
        _require(ls._unpack(post['generation']).id == previous['new_generation_id'], 'processed generation/activation mismatch')
        # A receipt that merely references the activation is not proof. Require
        # its successful establishment and matching resulting markers.
        cur.execute('''SELECT * FROM corner.lifecycle_applications WHERE condition_id=%s
            AND channel_generation_activation_id=%s AND application_outcome='applied'
            AND application_sequence<=%s ORDER BY application_sequence DESC LIMIT 1''',
                    (identity, previous['id'], head['application_sequence']))
        establishing = cur.fetchone()
        _require(establishing is not None, 'processed activation has no establishing receipt')
        established = ls._verify_receipt(cur, establishing)['post_state']
        _require(established['activation_id'] == previous['id'] and
                 ls._unpack(established['generation']).id == previous['new_generation_id'], 'activation not established by receipt')
    sequence = previous['activation_sequence'] if previous else 0
    cur.execute('''SELECT * FROM corner.channel_generation_activations
        WHERE channel_id=%s AND activation_sequence>%s ORDER BY activation_sequence LIMIT 1''',
                (condition['qualification_channel_id'], sequence))
    following = cur.fetchone()
    if following is None:
        return {'status': 'fulfilled', 'result_id': previous['id'] if previous else None}
    _require(following['activation_sequence'] == sequence + 1 and
             following['expected_previous_generation_id'] == (previous['new_generation_id'] if previous else None),
             'activation predecessor gap')
    _activation(cur, following, condition, key)
    return _request(conn, cur, 'activation', [identity, following['id']], 'apply_lifecycle',
                    {'condition_id': identity, 'generation_id': following['new_generation_id'],
                     'channel_generation_activation_id': following['id']},
                    {'command_kind': 'generation_activation'})


_HANDLERS = {'qualification': _evaluation_obligation, 'occurrence': _occurrence_obligation, 'activation': _activation_obligation}


def sweep(conn, *, obligation, after=None, limit=100, channel_id=None):
    """One bounded candidate page; requests only. Cursor wraps on exhaustion.

Optional channel partition applies to qualification/activation, never occurrences
whose existence is independent of routing. Cursor must not be reused across
obligations/partitions. Returned counts/items describe this transaction, not a
durable completeness claim. Pending includes ready/retryable/waiting/leased.
"""
    _require(obligation in _HANDLERS, 'unknown reconciliation obligation')
    _require(type(limit) is int and 1 <= limit <= 1000, 'limit must be 1..1000')
    _require(channel_id is None or obligation != 'occurrence', 'occurrence sweep is not channel scoped')
    after = ch._uuid(after) if after else None
    channel_id = ch._uuid(channel_id) if channel_id else None
    # Keep snapshot semantics explicit: a fresh command may see a late commit;
    # no long REPEATABLE READ transaction may pin many successive sweeps.
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute('SHOW transaction_isolation')
        _require(cur.fetchone()['transaction_isolation'] == 'read committed', 'sweeps require READ COMMITTED')
        if obligation == 'qualification':
            query = '''SELECT r.id FROM corner.work_requests r JOIN corner.work_executions x ON x.work_request_id=r.id
                LEFT JOIN corner.opportunity_conditions c ON c.id=r.condition_id
                WHERE r.work_kind='evaluate' AND x.status='completed'
                AND (%s::uuid IS NULL OR c.qualification_channel_id=%s::uuid)'''
            args = [channel_id, channel_id]
        elif obligation == 'activation':
            query = '''SELECT r.id FROM corner.opportunity_conditions r
                WHERE (%s::uuid IS NULL OR r.qualification_channel_id=%s::uuid)'''
            args = [channel_id, channel_id]
        else:
            query = "SELECT r.id FROM corner.qualification_decisions r WHERE r.decision_kind='qualified'"
            args = []
        cur.execute(query + ' AND (%s::uuid IS NULL OR r.id>%s::uuid) ORDER BY r.id LIMIT %s', args + [after, after, limit + 1])
        rows = cur.fetchall()
    page = rows[:limit]
    report = {'counts': {k: 0 for k in ('fulfilled', 'pending', 'blocked', 'newly_requested', 'invalid')},
              'items': [], 'next_cursor': page[-1]['id'] if len(rows) > limit else None}
    for candidate in page:
        try:
            with ch._write(conn, 'corner_reconcile_candidate') as cur:
                item = _HANDLERS[obligation](conn, cur, candidate['id'])
                if item['status'] == 'recheck':
                    item = _HANDLERS[obligation](conn, cur, candidate['id'])
                    _require(item['status'] != 'recheck', 'completed request does not fulfill its obligation')
        except (ValueError, KeyError, TypeError, ArithmeticError) as error:
            # Corrupt/unsupported serialized evidence is reported and traversal
            # advances. SQL/connectivity/programming runtime failures propagate.
            item = {'status': 'invalid', 'reason': str(error)}
        item = {'candidate_id': candidate['id'], **item}
        report['items'].append(item)
        report['counts'][item['status']] += 1
    return report
