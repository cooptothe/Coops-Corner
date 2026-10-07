"""Explicit-request v2 assessment worker. No polling or implicit lifecycle apply."""
from dataclasses import asdict
from datetime import datetime

from psycopg2.extras import Json, RealDictCursor

from corner import assessments_v2 as assessment, capture_authority as auth, channels
from corner import evaluations as codec, lifecycle_store, work, worker

FORMAT = 'corner.work.assessment/2'


def request_intent(*, evaluation_watermark_id, basis_assessment_id=None):
    return {'format': FORMAT, 'revision': assessment.REVISION,
        'evaluation_watermark_id': channels._uuid(evaluation_watermark_id),
        'basis_assessment_id': channels._uuid(basis_assessment_id) if basis_assessment_id else None}


def _route(cur, request):
    auth.require(request['work_kind'] == 'assess' and request['condition_id'] and request['generation_id']
                 and request['qualification_decision_id'], 'assessment requires explicit routing')
    intent = request['intent_snapshot']['intent']
    auth.require(intent == request_intent(evaluation_watermark_id=intent['evaluation_watermark_id'],
                 basis_assessment_id=intent['basis_assessment_id']), 'unsupported assessment route')
    condition, key = lifecycle_store._condition(cur, request['condition_id'])
    q, _, _, _ = assessment.load(cur, request['generation_id'], request['qualification_decision_id'],
                                 intent['evaluation_watermark_id'], intent['basis_assessment_id'])
    auth.require(key == q.evaluation.condition, 'assessment routing condition mismatch')
    gen, _ = assessment.generation(cur, request['generation_id'])
    auth.require(gen['channel_id'] == condition['qualification_channel_id'], 'assessment channel mismatch')
    return intent


def _prepared(cur, request_id):
    cur.execute('SELECT * FROM corner.prepared_work_commands WHERE work_request_id=%s', (request_id,))
    row = cur.fetchone()
    if row:
        auth.require(row['command_format_version'] == FORMAT and row['command_snapshot']['format'] == FORMAT
            and bytes(row['command_sha256']) == codec._digest(row['command_snapshot']), 'invalid frozen assessment work')
    return dict(row) if row else None


def _verify(cur, request, document):
    auth.require(document['format'] == FORMAT and document['implementation'] == assessment.REVISION
                 and document['work_kind'] == 'assess', 'unsupported assessment worker format/revision')
    intent = _route(cur, request)
    b = document['payload']['capture']['bindings']
    auth.require(b['generation_id'] == request['generation_id'] and b['qualification_id'] == request['qualification_decision_id']
        and b['watermark_id'] == intent['evaluation_watermark_id'] and b['basis_assessment_id'] == intent['basis_assessment_id'],
        'frozen assessment route mismatch')
    assessment.compute(cur, document['payload'])


def prepare_once(connect, *, lease, settings, source=None):
    request_id = lease['work_request_id']
    with worker._transaction(connect, settings) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            work._fence(cur, request_id, settings.owner, lease['lease_token'])
            request = work._request(cur, request_id)
            prior = _prepared(cur, request_id)
            if prior:
                _verify(cur, request, prior['command_snapshot'])
                return prior
            intent = _route(cur, request)
    with worker._transaction(connect, settings, read_only=True) as conn:
        command = assessment.capture_assessment(conn, generation_id=request['generation_id'],
            qualification_decision_id=request['qualification_decision_id'], evaluation_watermark_id=intent['evaluation_watermark_id'],
            basis_assessment_id=intent['basis_assessment_id'], source=source)
    who, identifier, key = channels._authority(settings.authority, 'corner.worker.assess-v2:' + request_id)
    document = {'format': FORMAT, 'work_kind': 'assess', 'implementation': assessment.REVISION,
        'authority': {'kind': who, 'identifier': identifier}, 'domain_command_key': key, 'payload': assessment.document(command)}
    with worker._transaction(connect, settings) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            work._fence(cur, request_id, settings.owner, lease['lease_token'])
            prior = _prepared(cur, request_id)
            if prior:
                _verify(cur, request, prior['command_snapshot'])
                return prior
            _verify(cur, request, document)
            cur.execute('''INSERT INTO corner.prepared_work_commands
                (work_request_id,command_format_version,command_snapshot,command_sha256) VALUES (%s,%s,%s,%s) RETURNING *''',
                (request_id, FORMAT, Json(document), codec._digest(document)))
            return dict(cur.fetchone())


def complete(conn, *, request_id, owner, token):
    with channels._write(conn, 'corner_assess_work_complete') as cur:
        work._fence(cur, request_id, owner, token)
        request = work._request(cur, request_id)
        prepared = _prepared(cur, request_id)
        auth.require(prepared is not None, 'assessment was not prepared')
        document = prepared['command_snapshot']; payload = document['payload']
        _verify(cur, request, document)
        command = assessment.AssessmentCommand(codec.canonical_json(payload['capture']), datetime.fromisoformat(payload['assessed_at']),
                                               codec.canonical_json(payload['context']))
        result = assessment.record_assessment(conn, authority=channels.ChannelAuthority(**document['authority']),
                                              assessment_key=document['domain_command_key'], command=command)
        work._result_matches(cur, document, result)
        cur.execute('''UPDATE corner.work_executions SET status='completed',completed_at=clock_timestamp(),
            lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,prepared_command_id=%s,actionability_assessment_id=%s,
            updated_at=clock_timestamp() WHERE work_request_id=%s RETURNING *''', (prepared['id'], result['id'], request_id))
        return dict(cur.fetchone())


def load_prepared(conn, *, request_id):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        return _prepared(cur, request_id)


def run_once(connect, *, settings, request_id, source=None):
    auth.require(isinstance(settings, worker.WorkerSettings), 'worker settings required')
    lease = None
    try:
        with worker._transaction(connect, settings) as conn:
            lease = work.claim(conn, owner=settings.owner, lease_for=settings.lease_for, request_id=request_id, kinds=('assess',))
        if lease is None: return {'status': 'idle', 'request_id': request_id}
        prepare_once(connect, lease=lease, settings=settings, source=source)
        with worker._transaction(connect, settings) as conn:
            result = complete(conn, request_id=request_id, owner=settings.owner, token=lease['lease_token'])
        return {'status': 'completed', 'request_id': request_id, 'execution': result}
    except Exception as error:
        if lease is None: raise
        with worker._transaction(connect, settings) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute('SELECT * FROM corner.work_executions WHERE work_request_id=%s', (request_id,))
                execution = cur.fetchone()
                if execution and execution['status'] == 'completed':
                    prepared = _prepared(cur, request_id)
                    auth.require(prepared and prepared['id'] == execution['prepared_command_id'], 'completion binding mismatch')
                    _verify(cur, work._request(cur, request_id), prepared['command_snapshot'])
                    work._result_matches(cur, prepared['command_snapshot'], {'id': execution['actionability_assessment_id']})
                    return {'status': 'completed', 'request_id': request_id, 'execution': dict(execution)}
                try: current = work._fence(cur, request_id, settings.owner, lease['lease_token'])
                except work.LeaseLost: return {'status': 'lease_lost', 'request_id': request_id}
                if isinstance(error, auth.UnmetPrerequisite): state, reason = 'waiting', str(error)
                else: state, reason = worker._classification(error, current['retry_count'], settings)
                retry_at = work._now(cur) + settings.retry_delay if state == 'retryable' else None
            work.record_failure(conn, request_id=request_id, owner=settings.owner, token=lease['lease_token'],
                status=state, reason=reason, retry_at=retry_at, details_json=codec.canonical_json({'error_type': type(error).__name__}))
        return {'status': state, 'reason': reason, 'request_id': request_id}
