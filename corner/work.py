"""Durable work storage only; no poll loop, routing, reconciliation or HTTP.

Caller owns short READ COMMITTED transactions and supplies authenticated authority.
Lock order is execution -> condition/channel. After an execution failure, caller
must roll back its transaction before recording failure in a NEW transaction.
"""
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
from pathlib import Path

from psycopg2.extras import Json, RealDictCursor
from corner import channels as ch, evaluations as ev, qualifications as q, assessments as a, lifecycle_store as ls

INTENT_FORMAT='corner.work.intent/1'
COMMAND_FORMAT='corner.work.command/1'
OCCURRENCE_REVISION='sha256:'+hashlib.sha256(Path(ch.__file__).read_bytes()).hexdigest()
SOURCES=('condition_id','generation_id','engine_evaluation_id','qualification_decision_id','actionability_assessment_id',
         'channel_generation_activation_id','trigger_observation_id','trigger_disposition_id')
RESULTS={'evaluate':('engine_evaluations','engine_evaluation_id','evaluation_key'),
         'qualify':('qualification_decisions','qualification_decision_id','qualification_key'),
         'ensure_occurrence':('opportunity_occurrences','opportunity_occurrence_id',None),
         'assess':('actionability_assessments','actionability_assessment_id','assessment_key'),
         'apply_lifecycle':('lifecycle_applications','lifecycle_application_id','application_key')}


class WorkValidationError(ValueError): pass
class WorkConflict(ValueError): pass
class LeaseLost(ValueError): pass
class WorkBlocked(ValueError): pass


def _require(value,message):
    if not value: raise WorkValidationError(message)


def _now(cur):
    cur.execute('SELECT clock_timestamp() AS wall_time')
    return cur.fetchone()['wall_time']


def _duration(value):
    _require(isinstance(value,timedelta) and value>timedelta(0),'positive lease duration required')
    return value


def _request(cur,identity):
    cur.execute('SELECT * FROM corner.work_requests WHERE id=%s',(ch._uuid(identity),))
    row=cur.fetchone()
    _require(row is not None,'unknown work request')
    _require(row['intent_format_version']==INTENT_FORMAT and ev._digest(row['intent_snapshot'])==bytes(row['intent_sha256']),
             'invalid request format/digest')
    _require(row['work_kind']==row['intent_snapshot']['work_kind']
             and all(row[k]==row['intent_snapshot']['sources'][k] for k in SOURCES),'request projection mismatch')
    return row


def enqueue(conn,*,kind,namespace,key,intent_json='{}',sources=None,available_at=None):
    """Duplicate discovery returns original intent AND original scheduling state."""
    ch._text(namespace,key)
    _require(kind in RESULTS,'unsupported work kind')
    sources=sources or {}
    _require(set(sources)<=set(SOURCES),'unknown source reference')
    refs={k:ch._uuid(sources[k]) if sources.get(k) is not None else None for k in SOURCES}
    document={'format':INTENT_FORMAT,'work_kind':kind,'intent':ch._context(intent_json),'sources':refs}
    if available_at is not None: ev._encode(available_at)
    with ch._write(conn,'corner_work_enqueue') as cur:
        cur.execute('SELECT * FROM corner.work_requests WHERE deduplication_namespace=%s AND deduplication_key=%s',(namespace,key))
        existing=cur.fetchone()
        if existing is not None:
            if existing['intent_snapshot']!=document or bytes(existing['intent_sha256'])!=ev._digest(document):
                raise WorkConflict('discovery key identifies different intent')
            return dict(existing)
        cur.execute('SELECT active FROM corner.work_kinds WHERE code=%s',(kind,))
        active=cur.fetchone()
        _require(active and active['active'],'work kind disabled')
        values={'work_kind':kind,'deduplication_namespace':namespace,'deduplication_key':key,**refs,
                'intent_format_version':INTENT_FORMAT,'intent_snapshot':Json(document),'intent_sha256':ev._digest(document)}
        cur.execute('INSERT INTO corner.work_requests ('+','.join(values)+') VALUES ('+','.join(['%s']*len(values))+') '
            'ON CONFLICT (deduplication_namespace,deduplication_key) DO NOTHING RETURNING *',tuple(values.values()))
        row=cur.fetchone()
        if row is None:
            cur.execute('SELECT * FROM corner.work_requests WHERE deduplication_namespace=%s AND deduplication_key=%s',(namespace,key))
            row=cur.fetchone()
            if row is None or row['intent_snapshot']!=document or bytes(row['intent_sha256'])!=ev._digest(document):
                raise WorkConflict('discovery key identifies different intent')
            return dict(row)
        cur.execute('INSERT INTO corner.work_executions(work_request_id,work_kind,available_at) VALUES (%s,%s,%s)',
                    (row['id'],kind,available_at or _now(cur)))
        return dict(row)


def claim(conn,*,owner,lease_for,request_id=None,kinds=None):
    ch._text(owner); _duration(lease_for)
    if kinds is not None:
        _require(not isinstance(kinds,str) and bool(kinds) and set(kinds)<=set(RESULTS),'invalid claim work kinds')
    with ch._write(conn,'corner_work_claim') as cur:
        cur.execute('''SELECT * FROM corner.work_executions
            WHERE ((status IN ('ready','retryable') AND available_at<=clock_timestamp())
                OR (status='leased' AND lease_expires_at<=clock_timestamp()))
            AND (%s::uuid IS NULL OR work_request_id=%s::uuid)
            AND (%s::text[] IS NULL OR work_kind=ANY(%s::text[]))
            ORDER BY COALESCE(available_at,lease_expires_at),work_request_id
            LIMIT 1 FOR UPDATE SKIP LOCKED''',(request_id,request_id,list(kinds) if kinds is not None else None,
                                             list(kinds) if kinds is not None else None))
        row=cur.fetchone()
        if row is None: return None
        cur.execute('''UPDATE corner.work_executions SET status='leased',lease_owner=%s,lease_token=gen_random_uuid(),
            lease_expires_at=clock_timestamp()+%s,claim_count=claim_count+1,updated_at=clock_timestamp()
            WHERE work_request_id=%s RETURNING *''',(owner,lease_for,row['work_request_id']))
        return dict(cur.fetchone())


def _fence(cur,identity,owner,token):
    cur.execute('SELECT * FROM corner.work_executions WHERE work_request_id=%s FOR UPDATE',(ch._uuid(identity),))
    row=cur.fetchone()
    now=_now(cur)  # AFTER acquiring the lock; never transaction-start now().
    if (row is None or row['status']!='leased' or row['lease_owner']!=owner
            or row['lease_token']!=ch._uuid(token) or row['lease_expires_at']<=now):
        raise LeaseLost('execution fence is no longer owned by this attempt')
    return row


def heartbeat(conn,*,request_id,owner,token,lease_for):
    _duration(lease_for)
    with ch._write(conn,'corner_work_heartbeat') as cur:
        _fence(cur,request_id,owner,token)
        cur.execute('''UPDATE corner.work_executions SET lease_expires_at=clock_timestamp()+%s,updated_at=clock_timestamp()
            WHERE work_request_id=%s RETURNING *''',(lease_for,request_id))
        return dict(cur.fetchone())


def _serialize(kind,command,authority,domain_key):
    if kind=='ensure_occurrence':
        _require(authority is None and domain_key is None,'occurrence uses its native qualification identity')
        payload={'qualification_decision_id':ch._uuid(command)}
        implementation=OCCURRENCE_REVISION
        who=None
    else:
        who_kind,who_id,_=ch._authority(authority,domain_key)
        who={'kind':who_kind,'identifier':who_id}
        if kind=='evaluate':
            payload=ev.serialize_command(command); implementation=ev.ENGINE_REVISION
        elif kind=='qualify':
            payload=ev._encode(asdict(command)); payload['context_json']=ev.canonical_json(ch._context(command.context_json))
            payload['engine_evaluation_id']=ch._uuid(command.engine_evaluation_id)
            implementation=q.POLICY_REVISION
        elif kind=='assess':
            payload=a._document(command); implementation=a.IMPLEMENTATION.revision
        elif kind=='apply_lifecycle':
            payload=ls._document(command); implementation=ls.REVISION
        else: raise WorkValidationError('unsupported work kind')
    return {'format':COMMAND_FORMAT,'work_kind':kind,'implementation':implementation,'authority':who,
            'domain_command_key':domain_key,'payload':payload}


def _bind(cur,request,document):
    """Check declared typed intent against the frozen domain command, not current markets."""
    kind,payload=request['work_kind'],document['payload']
    if kind=='evaluate':
        command=ev.deserialize_command(payload)
        target=next((v for v in command.snapshot.quotes if v.observation_id==command.snapshot.target_observation_id),None)
        _require(target is not None,'evaluation target missing')
        if request['condition_id']:
            condition,_=ls._condition(cur,request['condition_id'])
            _require((condition['outcome_id'],condition['target_sportsbook_id'])==(target.outcome_id,target.sportsbook_id),'evaluation intent mismatch')
        if request['generation_id']:
            generation=a._row(cur,'qualification_channel_generations',request['generation_id'])
            a._verify(generation,'configuration_snapshot','configuration_sha256')
            _require(generation['configuration_snapshot']['engine']['configuration']==payload['configuration']
                and generation['configuration_snapshot']['engine']['implementation']==
                    {'name':payload['engine_name'],'version':payload['engine_version'],'revision':payload['engine_revision']},
                'evaluation generation configuration mismatch')
            if request['condition_id']:
                _require(generation['channel_id']==condition['qualification_channel_id'],'evaluation generation belongs to another channel')
    elif kind=='qualify':
        _require(request['engine_evaluation_id']==payload['engine_evaluation_id'],'qualification intent requires its evaluation')
    elif kind=='ensure_occurrence':
        _require(request['qualification_decision_id']==payload['qualification_decision_id'],'occurrence intent requires its qualification')
    elif kind=='assess':
        b=payload['capture']['bindings']
        _require(request['qualification_decision_id']==b['qualification_id'] and request['generation_id']==b['generation_id'],
                 'assessment intent requires its qualification/generation')
        if request['condition_id']:
            condition,key=ls._condition(cur,request['condition_id'])
            ls._generation(cur,b['generation_id'],condition)
            ls._evaluation(cur,b['evaluation_id'],key)
    else:
        _require(request['condition_id']==payload['condition_id'] and request['generation_id']==payload['generation_id'],'lifecycle intent requires condition/generation')
        source=ls._SOURCE_COLUMNS[payload['kind']]
        _require(request[source]==payload['evidence_id'],'lifecycle intent requires matching source evidence')


def _prepared(cur,request_id):
    cur.execute('SELECT * FROM corner.prepared_work_commands WHERE work_request_id=%s',(request_id,))
    row=cur.fetchone()
    if row:
        _require(row['command_format_version']==COMMAND_FORMAT and row['command_snapshot']['format']==COMMAND_FORMAT
                 and bytes(row['command_sha256'])==ev._digest(row['command_snapshot']),'invalid prepared format/digest')
    return row


def prepare(conn,*,request_id,owner,token,command,authority=None,domain_key=None):
    """Capture happens BEFORE this call. Fence is revalidated before freezing."""
    with ch._write(conn,'corner_work_prepare') as cur:
        _fence(cur,request_id,owner,token)
        request=_request(cur,request_id)
        document=_serialize(request['work_kind'],command,authority,domain_key)
        existing=_prepared(cur,request_id)
        if existing:
            if existing['command_snapshot']!=document: raise WorkConflict('preparation is already frozen')
            return dict(existing)
        _bind(cur,request,document)
        cur.execute('''INSERT INTO corner.prepared_work_commands(work_request_id,command_format_version,command_snapshot,command_sha256)
            VALUES (%s,%s,%s,%s) RETURNING *''',(request_id,COMMAND_FORMAT,Json(document),ev._digest(document)))
        return dict(cur.fetchone())


def load_prepared(conn,*,request_id):
    """Read-only recovery; caller must not recapture if this returns a command."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        row=_prepared(cur,request_id)
        return dict(row) if row else None


def load_execution(conn,*,request_id):
    """Read-only recovery after a lost acknowledgement; never rerun domain work."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute('SELECT * FROM corner.work_executions WHERE work_request_id=%s',(ch._uuid(request_id),))
        row=cur.fetchone()
        if row is None: return None
        if row['status']=='completed':
            prepared=_prepared(cur,request_id)
            _require(prepared is not None and prepared['id']==row['prepared_command_id'],'completion preparation mismatch')
            column=RESULTS[row['work_kind']][1]
            _result_matches(cur,prepared['command_snapshot'],{'id':row[column]})
        return dict(row)


def _dispatch(conn,document):
    kind,payload=document['work_kind'],document['payload']
    revisions={'evaluate':ev.ENGINE_REVISION,'qualify':q.POLICY_REVISION,'ensure_occurrence':OCCURRENCE_REVISION,
               'assess':a.IMPLEMENTATION.revision,'apply_lifecycle':ls.REVISION}
    if document['implementation']!=revisions.get(kind): raise WorkBlocked('original frozen implementation is unavailable')
    authority=ch.ChannelAuthority(**document['authority']) if document['authority'] else None
    key=document['domain_command_key']
    if kind=='evaluate':
        return ev.record_evaluation(conn,authority=authority,evaluation_key=key,command=ev.deserialize_command(payload))
    if kind=='qualify':
        policy=payload['policy']
        command=q.QualificationCommand(payload['engine_evaluation_id'],q.MinimumEVPolicy(policy['version'],Decimal(policy['minimum_ev_ratio'])),
            datetime.fromisoformat(payload['decided_at']),payload['context_json'])
        return q.record_qualification(conn,authority=authority,qualification_key=key,command=command)
    if kind=='ensure_occurrence':
        return ch.create_occurrence(conn,qualification_decision_id=payload['qualification_decision_id'])
    if kind=='assess':
        command=a.AssessmentCommand(ev.canonical_json(payload['capture']),datetime.fromisoformat(payload['assessed_at']),ev.canonical_json(payload['context']))
        return a.record_assessment(conn,authority=authority,assessment_key=key,command=command)
    command=ls.ApplicationCommand(payload['condition_id'],payload['kind'],payload['evidence_id'],payload['generation_id'],
        datetime.fromisoformat(payload['transition_at']) if payload['transition_at'] else None,ev.canonical_json(payload['context']))
    return ls.apply_command(conn,authority=authority,application_key=key,command=command)


def _result_matches(cur,document,result):
    kind,payload=document['work_kind'],document['payload']
    table,_,key_field=RESULTS[kind]
    persisted=a._row(cur,table,result['id'])
    if kind=='ensure_occurrence':
        _require(persisted['qualification_decision_id']==payload['qualification_decision_id'],'occurrence belongs to another command')
        return
    authority=document['authority']
    _require((persisted['authority_kind'],persisted['authority_id'],persisted[key_field])==
             (authority['kind'],authority['identifier'],document['domain_command_key']),'result authority/key mismatch')
    a._verify(persisted,'command_snapshot','command_sha256')
    if kind=='qualify':
        snapshot=persisted['command_snapshot']
        _require(snapshot['engine_evaluation_id']==payload['engine_evaluation_id']
            and snapshot['decided_at']==payload['decided_at'] and snapshot['context']==ch._context(payload['context_json'])
            and snapshot['policy']['minimum_ev_ratio']==payload['policy']['minimum_ev_ratio']
            and snapshot['policy']['policy_version']==payload['policy']['version']
            and snapshot['policy']['policy_revision']==document['implementation'],'qualification command mismatch')
    else:
        _require(persisted['command_snapshot']==payload,'result frozen command mismatch')


def complete(conn,*,request_id,owner,token):
    """One bounded transaction: fence -> adapter -> authoritative refs -> completed.

The fence is checked ONCE after lock acquisition. Expiry during this protected
transaction does not revoke the lock holder; reclaimers cannot modify its row.
"""
    with ch._write(conn,'corner_work_complete') as cur:
        execution=_fence(cur,request_id,owner,token)
        request=_request(cur,request_id)
        prepared=_prepared(cur,request_id)
        _require(prepared is not None,'work has no frozen command')
        document=prepared['command_snapshot']
        _require(document['work_kind']==request['work_kind']==execution['work_kind'],'work kind mismatch')
        _bind(cur,request,document)
        result=_dispatch(conn,document)
        _result_matches(cur,document,result)
        result_column=RESULTS[request['work_kind']][1]
        cur.execute('''UPDATE corner.work_executions SET status='completed',completed_at=clock_timestamp(),
            lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,prepared_command_id=%s,
            '''+result_column+'''=%s,updated_at=clock_timestamp() WHERE work_request_id=%s RETURNING *''',
            (prepared['id'],result['id'],request_id))
        return dict(cur.fetchone())


def record_failure(conn,*,request_id,owner,token,status,reason,details_json='{}',retry_at=None):
    """Call in a NEW transaction after rollback of the failed execution attempt."""
    _require(status in {'retryable','waiting','blocked'},'invalid failure state')
    ch._text(reason)
    if status=='retryable': _require(retry_at is not None,'explicit retry schedule required'); ev._encode(retry_at)
    with ch._write(conn,'corner_work_failure') as cur:
        _fence(cur,request_id,owner,token)
        cur.execute('''UPDATE corner.work_executions SET status=%s,available_at=%s,
            lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,waiting_reason=%s,blocked_reason=%s,
            last_error_code=%s,last_error_details=%s,retry_count=retry_count+%s,updated_at=clock_timestamp()
            WHERE work_request_id=%s RETURNING *''',
            (status,retry_at if status=='retryable' else None,reason if status=='waiting' else None,
             reason if status=='blocked' else None,reason,Json(ch._context(details_json)),int(status=='retryable'),request_id))
        return dict(cur.fetchone())


def resume(conn,*,request_id,expected_status,available_at):
    """Administrative/prerequisite resolver operation, not a worker retry loop.

Caller must authorize blocked recovery or establish waiting prerequisites. No
prepared command is edited. No completed work can be revived.
"""
    _require(expected_status in {'waiting','blocked'},'only waiting/blocked may resume')
    ev._encode(available_at)
    with ch._write(conn,'corner_work_resume') as cur:
        cur.execute('''UPDATE corner.work_executions SET status='ready',available_at=%s,waiting_reason=NULL,
            blocked_reason=NULL,updated_at=clock_timestamp() WHERE work_request_id=%s AND status=%s RETURNING *''',
            (available_at,request_id,expected_status))
        row=cur.fetchone()
        if row is None: raise WorkConflict('execution is no longer in the expected recoverable state')
        return dict(row)
