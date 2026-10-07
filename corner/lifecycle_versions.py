"""Versioned lifecycle journal (v1 history + v2 assessment interpretation).

Frozen fork of the 011 storage algorithm; old module bytes remain replayable.
Changes are limited to typed evidence/version dispatch and assessment semantics.
Caller owns a READ COMMITTED transaction.

The journal head, never a projection, supplies the execution frontier. Targeted
receipts supply duplicate/consistency context. Full replay is an independent oracle.
No current quote selection, polling, scheduler or implicit channel initialization.
"""
import hashlib
import platform
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from psycopg2.extras import Json, RealDictCursor

from corner import assessments as a, channels as ch, evaluations as c, lifecycle as l, qualifications as q
from corner.ev import QuoteInput
from corner import lifecycle_store as legacy, assessments_v2 as a2, actionability_v2 as policy2
from corner import analytics_versions as analytics, evaluation_capture_v2 as capture2

FORMAT = 'corner.lifecycle.application/2'
STATE_FORMAT = 'corner.lifecycle.frontier/1'
PROJECTION_FORMAT = 'corner.lifecycle.projection/1'
REDUCER_NAME = 'corner.lifecycle'
REDUCER_VERSION = '2'
REVISION = 'sha256:' + c._digest({
    'assessment_v2': a2.REVISION,
    'policy_v2': policy2.IMPLEMENTATION.revision,
    'legacy_adapter': legacy.REVISION,
    'adapter': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'reducer': hashlib.sha256(Path(l.__file__).read_bytes()).hexdigest(),
    'evidence_adapter': hashlib.sha256(Path(a.__file__).read_bytes()).hexdigest(),
    'serializer': hashlib.sha256(Path(c.__file__).read_bytes()).hexdigest(),
    'python': platform.python_version(),
}).hex()


class LifecycleStoreError(ValueError):
    pass


class ApplicationConflict(LifecycleStoreError):
    pass


class HistoryCorruption(LifecycleStoreError):
    pass


@dataclass(frozen=True)
class ApplicationCommand:
    condition_id: str
    kind: str
    evidence_id: str
    generation_id: str
    transition_at: datetime | None = None
    context_json: str = '{}'


# Versioned, closed type registry; never deserialize arbitrary Python names.
_TYPES = {t.__name__: t for t in (
    l.ImplementationIdentity, l.ConditionKey, l.ActionabilityPolicy, l.ChannelGeneration,
    l.EvaluationOrder, l.EvaluationFact, l.EvaluationArrival, l.QualificationFact,
    l.Occurrence, l.JudgmentCommand, l.PhaseEvidence, l.AssessmentRequest,
    l.ActionabilityAssessment, l.Episode, l.LifecycleEvent, l.GenerationChange, QuoteInput)}


def _pack(value):
    if is_dataclass(value):
        return {'type': type(value).__name__, 'fields': {f.name: _pack(getattr(value, f.name)) for f in fields(value)}}
    if isinstance(value, datetime):
        return {'time': c._encode(value)}
    if isinstance(value, timedelta):
        return {'microseconds': c._encode(value)}
    if isinstance(value, Decimal):
        return {'decimal': c._decimal(value)}
    if isinstance(value, tuple):
        return {'tuple': [_pack(v) for v in value]}
    if isinstance(value, dict):
        return {k: _pack(v) for k, v in value.items()}
    return value


def _unpack(value):
    if not isinstance(value, dict):
        return value
    if set(value) == {'type', 'fields'}:
        return _TYPES[value['type']](**{k: _unpack(v) for k, v in value['fields'].items()})
    if set(value) == {'time'}:
        return datetime.fromisoformat(value['time'])
    if set(value) == {'microseconds'}:
        return timedelta(microseconds=value['microseconds'])
    if set(value) == {'decimal'}:
        return Decimal(value['decimal'])
    if set(value) == {'tuple'}:
        return tuple(_unpack(v) for v in value['tuple'])
    return {k: _unpack(v) for k, v in value.items()}


def _require(ok, message):
    if not ok:
        raise HistoryCorruption(message)


def _one(cur, table, identity):
    return a._row(cur, table, identity)


def resolve_condition(conn, *, sportsbook_id, outcome_id, channel_id):
    """Canonical tuple creation; no generation/episode/processing state is created."""
    values = tuple(ch._uuid(v) for v in (sportsbook_id, outcome_id, channel_id))
    with ch._write(conn, 'corner_condition') as cur:
        cur.execute('''INSERT INTO corner.opportunity_conditions
            (opportunity_type,target_sportsbook_id,outcome_id,qualification_channel_id)
            VALUES ('positive_ev',%s,%s,%s) ON CONFLICT DO NOTHING RETURNING *''', values)
        row = cur.fetchone()
        if row is None:
            cur.execute('''SELECT * FROM corner.opportunity_conditions WHERE opportunity_type='positive_ev'
                AND target_sportsbook_id=%s AND outcome_id=%s AND qualification_channel_id=%s''', values)
            row = cur.fetchone()
        _require(row is not None, 'condition outside transaction snapshot')
        return dict(row)


def _condition(cur, identity, lock=False):
    cur.execute('SELECT * FROM corner.opportunity_conditions WHERE id=%s' + (' FOR UPDATE' if lock else ''), (identity,))
    row = cur.fetchone()
    _require(row is not None, 'unknown condition')
    _require(row['opportunity_type'] == 'positive_ev', 'unsupported condition type')
    channel = _one(cur, 'qualification_channels', row['qualification_channel_id'])
    return dict(row), l.ConditionKey('positive_ev', row['target_sportsbook_id'], row['outcome_id'], channel['code'])


def _document(command):
    _require(command.kind in {'evaluation','qualification','assessment','generation_activation'}, 'unknown command kind')
    _require((command.transition_at is not None) == (command.kind in {'qualification','generation_activation'}),
             'explicit transition time required only for qualification/activation commands')
    return {'format': FORMAT, 'condition_id': ch._uuid(command.condition_id), 'kind': command.kind,
            'evidence_id': ch._uuid(command.evidence_id), 'generation_id': ch._uuid(command.generation_id),
            'transition_at': c._encode(command.transition_at), 'context': ch._context(command.context_json)}


def _generation(cur, identity, condition):
    row = _one(cur, 'qualification_channel_generations', identity)
    if row['snapshot_format_version'] == ch.CONFIGURATION_FORMAT:
        return legacy._generation(cur, identity, condition)
    row, config = a2.generation(cur, identity)
    _require(row['channel_id'] == condition['qualification_channel_id'], 'cross-channel generation')
    doc = row['configuration_snapshot']
    channel = _one(cur, 'qualification_channels', row['channel_id'])
    return l.ChannelGeneration(row['id'], channel['code'], config.analytics.engine,
        c._digest(doc['engine']['configuration']).hex(), config.analytics.qualification_implementation,
        c._digest(doc['qualification']['configuration']).hex(), config.analytics.actionability_policy)


def _evaluation(cur, identity, key):
    row = _one(cur, 'engine_evaluations', identity)
    if row['snapshot_format_version'] == c.FORMAT_VERSION:
        return legacy._evaluation(cur, identity, key)
    return a2.evaluation(cur, identity, key)[2]


def _qualification(cur, identity, generation_id, key):
    row = _one(cur, 'qualification_decisions', identity)
    if row['qualification_snapshot_format_version'] == q.FORMAT_VERSION:
        return legacy._qualification(cur, identity, generation_id, key)
    _, _, _, fact, _ = a2.qualification(cur, identity, generation_id, key)
    cur.execute('SELECT id FROM corner.opportunity_occurrences WHERE qualification_decision_id=%s', (identity,))
    occurrence = cur.fetchone()
    _require((occurrence is not None) == (fact.decision_kind == 'qualified'), 'qualified decision requires occurrence')
    return fact, occurrence['id'] if occurrence else None


def _input(cur, doc, condition, key):
    gen = _generation(cur, doc['generation_id'], condition)
    kind, identity = doc['kind'], doc['evidence_id']
    occurrence = None
    if kind == 'evaluation':
        fact = l.EvaluationArrival(gen.id, _evaluation(cur, identity, key))
    elif kind == 'qualification':
        qualified, occurrence = _qualification(cur, identity, gen.id, key)
        fact = l.JudgmentCommand(qualified, occurrence, datetime.fromisoformat(doc['transition_at']))
    elif kind == 'assessment':
        row = _one(cur, 'actionability_assessments', identity)
        if row['snapshot_format_version'] == a.FORMAT_VERSION:
            # An explicitly v1 assessment must pass ALL original validation, not
            # just an actionable boolean or a guessed compatible reason string.
            return legacy._input(cur, doc, condition, key)
        _require(row['snapshot_format_version'] == policy2.FORMAT, 'unsupported assessment version')
        fact = a2.read_fact(cur, identity)
        _require(fact.request.generation_id == gen.id and fact.qualification.evaluation.condition == key
                 and fact.policy == gen.actionability_policy, 'assessment condition/generation mismatch')
        _, occurrence = _qualification(cur, fact.qualification.id, gen.id, key)
    else:
        row = _one(cur, 'channel_generation_activations', identity)
        a._verify(row, 'command_snapshot', 'command_sha256')
        expected = ch.activation_snapshot(ch.ActivationCommand(row['channel_id'], row['new_generation_id'],
            row['expected_previous_generation_id'], row['activated_at'], c.canonical_json(row['command_snapshot']['context'])))
        _require(row['snapshot_format_version'] == ch.ACTIVATION_FORMAT and row['command_snapshot'] == expected
                 and row['channel_id'] == condition['qualification_channel_id'] and row['new_generation_id'] == gen.id,
                 'activation binding mismatch')
        at = datetime.fromisoformat(doc['transition_at'])
        _require(at >= row['activated_at'], 'application precedes activation')
        fact = {'activation_id': row['id'], 'previous_generation_id': row['expected_previous_generation_id'],
                'generation': gen, 'activated_at': row['activated_at'], 'transition_at': at}
    return fact, gen, occurrence


def _frontier(state, activation_id, last_transition_id, opening_id):
    # Execution frontier, NOT a hash of all historical tuples or projection bytes.
    # Historical consistency context is bound separately by the application chain.
    return {'format': STATE_FORMAT, 'generation': _pack(state.generation) if state else None,
        'activation_id': activation_id, 'activated_at': _pack(state.generation_activated_at) if state else None,
        'watermark': _pack(state.watermark) if state else None,
        'threshold_id': state.latest_threshold_qualification_id if state else None,
        'assessment_id': state.current_assessment_id if state else None,
        'open_episode': _pack(state.open_episode) if state else None,
        'opening_transition_id': opening_id,
        'last_event': _pack(state.events[-1]) if state and state.events else None,
        'last_transition_id': last_transition_id}


EMPTY = _frontier(None, None, None, None)


def _verify_receipt(cur, row):
    if row['snapshot_format_version'] == legacy.FORMAT:
        return legacy._verify_receipt(cur, row)
    _require(row['snapshot_format_version']==FORMAT and row['reducer_revision']==REVISION
             and row['reducer_name']==REDUCER_NAME and row['reducer_version']==REDUCER_VERSION, 'unsupported lifecycle format/build')
    a._verify(row, 'command_snapshot', 'command_sha256')
    a._verify(row, 'result_snapshot', 'result_sha256')
    result, doc = row['result_snapshot'], row['command_snapshot']
    _require(c._digest(result['pre_state'])==bytes(row['pre_state_sha256'])
             and c._digest(result['post_state'])==bytes(row['post_state_sha256'])
             and result['application_outcome']==row['application_outcome'] and result['reason_code']==row['reason_code']
             and len(result['outputs'])==row['transition_count'] and doc['condition_id']==row['condition_id']
             and doc['kind']==row['command_kind'], 'receipt projection mismatch')
    for kind, column in _SOURCE_COLUMNS.items():
        _require(row[column] == (doc['evidence_id'] if kind==doc['kind'] else None), 'receipt evidence mismatch')
    cur.execute('SELECT * FROM corner.opportunity_transitions WHERE application_id=%s ORDER BY output_ordinal', (row['id'],))
    stored = cur.fetchall()
    _require(len(stored)==len(result['outputs']), 'missing/extra transition outputs')
    for ordinal, (actual, expected) in enumerate(zip(stored,result['outputs']),1):
        _require(actual['output_ordinal']==ordinal and _transition_doc(actual)==expected, 'transition output mismatch')
    return result


_SOURCE_COLUMNS = {'evaluation':'engine_evaluation_id', 'qualification':'qualification_decision_id',
                   'assessment':'actionability_assessment_id', 'generation_activation':'channel_generation_activation_id'}
_TRANSITION_COLUMNS = ('id','output_ordinal','episode_id','episode_generation_id','transition_kind','reason_code','transition_at',
    'opportunity_occurrence_id','qualification_decision_id','actionability_assessment_id','channel_generation_activation_id')


def _transition_doc(row):
    return {k: c._encode(row[k]) for k in _TRANSITION_COLUMNS}


def _incremental(cur, condition, key, head, fact, gen, kind):
    if head is None:
        return None, EMPTY
    result = _verify_receipt(cur, head)
    pre = result['post_state']
    current_gen, event, episode = (_unpack(pre[k]) for k in ('generation','last_event','open_episode'))
    state = l.LifecycleState(key, (current_gen,), watermark=_unpack(pre['watermark']),
        latest_threshold_qualification_id=pre['threshold_id'], current_assessment_id=pre['assessment_id'],
        generation_activated_at=_unpack(pre['activated_at']), events=(event,) if event else (), episodes=(episode,) if episode else ())
    # Fetch only receipts relevant to the frontier or incoming identity/evaluation.
    qids = [v for v in (pre['threshold_id'], fact.request.qualification_id if kind=='assessment' else None) if v]
    if episode:
        occurrence = _one(cur,'opportunity_occurrences',episode.current_occurrence_id)
        qids.append(occurrence['qualification_decision_id'])
    eid = (fact.evaluation.order.evaluation_id if kind=='evaluation' else
           fact.qualification.evaluation.order.evaluation_id if kind in {'qualification','assessment'} else None)
    aid = fact.request.id if kind=='assessment' else None
    activation_id = fact['activation_id'] if kind=='generation_activation' else None
    cur.execute('''SELECT DISTINCT app.* FROM corner.lifecycle_applications app
        LEFT JOIN corner.qualification_decisions q ON q.id=app.qualification_decision_id
        WHERE app.condition_id=%s AND (app.qualification_decision_id=ANY(%s::uuid[])
            OR q.engine_evaluation_id=%s OR app.engine_evaluation_id=%s
            OR app.actionability_assessment_id=ANY(%s::uuid[]) OR app.channel_generation_activation_id=%s
            OR (app.command_kind='generation_activation' AND app.application_outcome='applied'
                AND app.command_snapshot->>'generation_id'=%s))
        ORDER BY app.application_sequence''', (condition['id'],qids,eid,eid,
            [v for v in (pre['assessment_id'],aid) if v],activation_id,gen.id))
    evaluations, judgments, assessments, changes, occurrences, generations = [],[],[],[],{}, {current_gen.id:current_gen}
    for row in cur.fetchall():
        receipt = _verify_receipt(cur,row)
        old = _unpack(receipt['input_fact'])
        oldkind = row['command_kind']
        reason = receipt['reason_code']
        if oldkind=='evaluation':
            evaluations.append((old,reason))
        elif oldkind=='qualification':
            judgments.append((old,reason))
            if old.occurrence_id:
                occurrences[old.occurrence_id]=l.Occurrence(old.occurrence_id,old.qualification.id)
        elif oldkind=='assessment':
            assessments.append((old,reason))
        else:
            generations[old['generation'].id]=old['generation']
            if old['previous_generation_id'] is not None:
                changes.append((l.GenerationChange(old['activation_id'],old['previous_generation_id'],old['generation'],old['transition_at']),reason))
    # Requests for a known but no-longer-current generation need its immutable policy.
    generations.pop(current_gen.id,None)
    ordered_generations=tuple(generations.values())+(current_gen,)
    return replace(state,generations=ordered_generations,evaluations=tuple(evaluations),judgments=tuple(judgments),
        assessments=tuple(assessments),generation_changes=tuple(changes),occurrences=tuple(occurrences.values())), pre


def _step(state, fact, gen, kind, key, opening_id):
    if state is None:
        _require(kind=='generation_activation', 'condition must be initialized by an activation application')
        # A new condition may join a channel at an explicitly named activation;
        # it need not replay activations before this condition existed.
        return replace(l.initial_state(key,gen),generation_activated_at=fact['activated_at']), 'applied','initialized'
    if kind=='evaluation':
        output=l.process_evaluation(state,fact)
        before,after=state.evaluations,output.evaluations
    elif kind=='qualification':
        output=l.process_judgment(state,fact)
        before,after=state.judgments,output.judgments
    elif kind=='assessment':
        prior=next((assessment for assessment,_ in state.assessments if assessment.request.id==fact.request.id),None)
        if prior is not None:
            opening_id=prior.request.opening_episode_id
        request=replace(fact.request,opening_episode_id=opening_id)
        output=policy2.process_assessment(state,replace(fact,request=request))
        before,after=state.assessments,output.assessments
    else:
        if state.generation.id==gen.id:
            return state,'already_reflected','already_reflected'
        # The nullable predecessor only occurs in genesis, which cannot replace
        # an already initialized condition.
        if fact['previous_generation_id'] is None:
            return state,'ignored','obsolete_binding'
        change=l.GenerationChange(fact['activation_id'],fact['previous_generation_id'],gen,fact['transition_at'])
        output=l.change_generation(state,change)
        before,after=state.generation_changes,output.generation_changes
        if output.generation.id==gen.id:
            output=replace(output,generation_activated_at=fact['activated_at'])
    if len(before)==len(after):
        return output,'already_reflected','already_reflected'
    reason=after[-1][1]
    return output, ('applied' if reason in {'applicable','applied'} else 'ignored'),reason


def _uuid7(cur):
    cur.execute('SELECT uuidv7()::text AS id')
    return cur.fetchone()['id']


def _outputs(events, identities):
    result=[]
    for ordinal,(event,identity) in enumerate(zip(events,identities),1):
        result.append(dict(id=identity,output_ordinal=ordinal,episode_id=event.episode_id,
            episode_generation_id=event.generation_id,transition_kind=event.kind,reason_code=event.reason,
            transition_at=c._encode(event.transition_at),opportunity_occurrence_id=event.occurrence_id,
            qualification_decision_id=event.evidence_id if event.evidence_kind=='qualification' else None,
            actionability_assessment_id=event.evidence_id if event.evidence_kind=='assessment' else None,
            channel_generation_activation_id=event.evidence_id if event.evidence_kind=='generation_change' else None))
    return result


def _reduce(state, pre, fact, gen, kind, key, opening_id, output_ids):
    last_sequence=state.events[-1].sequence if state and state.events else 0
    next_state,outcome,reason=_step(state,fact,gen,kind,key,opening_id)
    events=tuple(e for e in next_state.events if e.sequence>last_sequence)
    identities=output_ids(len(events)) if callable(output_ids) else output_ids
    _require(len(identities)==len(events), 'replay output count differs')
    outputs=_outputs(events,identities)
    activation=(fact['activation_id'] if kind=='generation_activation' and outcome=='applied' else pre['activation_id'])
    opening=pre['opening_transition_id']
    for out in outputs:
        if out['transition_kind']=='opened': opening=out['id']
        elif out['transition_kind']=='closed': opening=None
    post=_frontier(next_state,activation,outputs[-1]['id'] if outputs else pre['last_transition_id'],opening)
    result={'format':FORMAT,'pre_state':pre,'post_state':post,'input_fact':_pack(fact),
            'application_outcome':outcome,'reason_code':reason,'outputs':outputs}
    return next_state,result


def _head(cur,condition_id):
    cur.execute('SELECT * FROM corner.lifecycle_applications WHERE condition_id=%s ORDER BY application_sequence DESC LIMIT 1', (condition_id,))
    return cur.fetchone()


def _retry(cur,row,document):
    _require(row is not None,'concurrent receipt outside transaction snapshot')
    if row['command_snapshot']!=document or bytes(row['command_sha256'])!=c._digest(document):
        raise ApplicationConflict('authority/key identifies a different lifecycle command')
    _verify_receipt(cur,row)
    return dict(row)


def apply_command(conn, *, authority, application_key, command):
    """Append one command and its outputs atomically. Never commits the caller transaction."""
    auth=ch._authority(authority,application_key)
    document=_document(command)
    with ch._write(conn,'corner_lifecycle_apply') as cur:
        condition,key=_condition(cur,document['condition_id'],lock=True)
        cur.execute('SELECT * FROM corner.lifecycle_applications WHERE authority_kind=%s AND authority_id=%s AND application_key=%s',auth)
        existing=cur.fetchone()
        if existing is not None:
            return _retry(cur,existing,document)
        fact,gen,occurrence=_input(cur,document,condition,key)
        head=_head(cur,condition['id'])
        _check_projection(cur,condition['id'],head)
        state,pre=_incremental(cur,condition,key,head,fact,gen,document['kind'])
        # No IDs allocated during replay. An unused opening candidate is harmless
        # and is not authoritative unless an opening output actually commits.
        opening=_uuid7(cur) if document['kind']=='assessment' else None
        _,result=_reduce(state,pre,fact,gen,document['kind'],key,opening,lambda n:[_uuid7(cur) for _ in range(n)])
        sequence=head['application_sequence']+1 if head else 1
        values=dict(condition_id=condition['id'],application_sequence=sequence,
            previous_application_id=head['id'] if head else None,previous_application_sequence=sequence-1 if head else None,
            pre_state_sha256=c._digest(pre),post_state_sha256=c._digest(result['post_state']),
            authority_kind=auth[0],authority_id=auth[1],application_key=auth[2],command_kind=document['kind'],
            **{column:document['evidence_id'] if kind==document['kind'] else None for kind,column in _SOURCE_COLUMNS.items()},
            opportunity_occurrence_id=occurrence if document['kind']=='qualification' else None,
            reducer_name=REDUCER_NAME,reducer_version=REDUCER_VERSION,reducer_revision=REVISION,
            snapshot_format_version=FORMAT,command_snapshot=Json(document),command_sha256=c._digest(document),
            result_snapshot=Json(result),result_sha256=c._digest(result),application_outcome=result['application_outcome'],
            reason_code=result['reason_code'],transition_count=len(result['outputs']))
        cur.execute('INSERT INTO corner.lifecycle_applications ('+','.join(values)+') VALUES ('+','.join(['%s']*len(values))+''')
            ON CONFLICT (authority_kind,authority_id,application_key) DO NOTHING RETURNING *''',tuple(values.values()))
        row=cur.fetchone()
        if row is None:
            cur.execute('SELECT * FROM corner.lifecycle_applications WHERE authority_kind=%s AND authority_id=%s AND application_key=%s',auth)
            return _retry(cur,cur.fetchone(),document)
        for output in result['outputs']:
            values=output | {'application_id':row['id']}
            cur.execute('INSERT INTO corner.opportunity_transitions ('+','.join(values)+') VALUES ('+','.join(['%s']*len(values))+')',tuple(values.values()))
        _verify_receipt(cur,row)
        _project(cur,row)
        _check_projection(cur,condition['id'],row)
        return dict(row)


def _project(cur,row):
    """Incrementally maintain projections. Closed episodes are never discarded."""
    result=row['result_snapshot']; post=result['post_state']
    for out in result['outputs']:
        if out['transition_kind']=='opened':
            cur.execute('''INSERT INTO corner.opportunities
                (id,condition_id,episode_generation_id,opening_transition_id,last_transition_id,current_occurrence_id,opened_at,projection_format_version)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)''', (out['episode_id'],row['condition_id'],out['episode_generation_id'],out['id'],
                    out['id'],out['opportunity_occurrence_id'],out['transition_at'],PROJECTION_FORMAT))
        elif out['transition_kind']=='continued':
            cur.execute('''UPDATE corner.opportunities SET current_occurrence_id=%s,last_transition_id=%s,projected_at=clock_timestamp()
                WHERE id=%s AND condition_id=%s AND closed_at IS NULL''',
                (out['opportunity_occurrence_id'],out['id'],out['episode_id'],row['condition_id']))
            _require(cur.rowcount==1,'episode projection missing or inconsistent; explicit rebuild required')
        else:
            cur.execute('''UPDATE corner.opportunities SET closed_at=%s,close_reason=%s,last_transition_id=%s,projected_at=clock_timestamp()
                WHERE id=%s AND condition_id=%s AND closed_at IS NULL''',
                (out['transition_at'],out['reason_code'],out['id'],out['episode_id'],row['condition_id']))
            _require(cur.rowcount==1,'episode projection missing or inconsistent; explicit rebuild required')
    gen=_unpack(post['generation']); wm=_unpack(post['watermark']); episode=_unpack(post['open_episode'])
    values=dict(condition_id=row['condition_id'],processed_generation_id=gen.id,processed_activation_id=post['activation_id'],
        evaluation_watermark_id=wm.evaluation_id if wm else None,latest_threshold_qualification_id=post['threshold_id'],
        accepted_assessment_id=post['assessment_id'],open_episode_id=episode.id if episode else None,
        open_episode_opening_transition_id=post['opening_transition_id'],last_transition_id=post['last_transition_id'],
        last_application_id=row['id'],last_application_sequence=row['application_sequence'],
        authoritative_post_state_sha256=row['post_state_sha256'],projection_format_version=PROJECTION_FORMAT)
    cur.execute('INSERT INTO corner.condition_processing_projections ('+','.join(values)+') VALUES ('+','.join(['%s']*len(values))+') '
        'ON CONFLICT (condition_id) DO UPDATE SET '+','.join(k+'=EXCLUDED.'+k for k in values if k!='condition_id')+
        ',projected_at=clock_timestamp()',tuple(values.values()))


def _check_projection(cur,condition_id,head):
    """A projection may seed reads, but it may not contradict the journal head."""
    cur.execute('SELECT * FROM corner.condition_processing_projections WHERE condition_id=%s',(condition_id,))
    row=cur.fetchone()
    if head is None:
        _require(row is None,'uninitialized condition has processing projection')
        cur.execute('SELECT 1 FROM corner.opportunities WHERE condition_id=%s LIMIT 1',(condition_id,))
        _require(cur.fetchone() is None,'uninitialized condition has episode projection')
        return
    _require(row is not None,'processing projection missing; explicit rebuild required')
    post=_verify_receipt(cur,head)['post_state']
    gen=_unpack(post['generation']); wm=_unpack(post['watermark']); episode=_unpack(post['open_episode'])
    expected=dict(processed_generation_id=gen.id,processed_activation_id=post['activation_id'],
        evaluation_watermark_id=wm.evaluation_id if wm else None,latest_threshold_qualification_id=post['threshold_id'],
        accepted_assessment_id=post['assessment_id'],open_episode_id=episode.id if episode else None,
        open_episode_opening_transition_id=post['opening_transition_id'],last_transition_id=post['last_transition_id'],
        last_application_id=head['id'],last_application_sequence=head['application_sequence'],projection_format_version=PROJECTION_FORMAT)
    _require(all(row[k]==v for k,v in expected.items())
             and bytes(row['authoritative_post_state_sha256'])==bytes(head['post_state_sha256']),
             'processing projection differs from journal; explicit rebuild required')
    cur.execute('SELECT * FROM corner.opportunities WHERE condition_id=%s AND closed_at IS NULL',(condition_id,))
    rows=cur.fetchall()
    _require(len(rows)==(1 if episode else 0),'open episode projection differs from journal')
    if episode:
        actual=rows[0]
        _require((actual['id'],actual['episode_generation_id'],actual['current_occurrence_id'],actual['opened_at'],
                  actual['opening_transition_id'],actual['last_transition_id'],actual['close_reason'])
            ==(episode.id,episode.generation_id,episode.current_occurrence_id,episode.opened_at,
               post['opening_transition_id'],post['last_transition_id'],None),'episode projection differs from journal')


def _replay(cur,condition,key):
    cur.execute('SELECT * FROM corner.lifecycle_applications WHERE condition_id=%s ORDER BY application_sequence',(condition['id'],))
    rows=cur.fetchall(); state=None; pre=EMPTY; previous=None
    for seq,row in enumerate(rows,1):
        expected=_verify_receipt(cur,row)
        _require(row['application_sequence']==seq and row['previous_application_id']==(previous['id'] if previous else None)
                 and row['previous_application_sequence']==(seq-1 if previous else None)
                 and expected['pre_state']==pre,'broken application chain')
        fact,gen,occurrence=_input(cur,row['command_snapshot'],condition,key)
        _require(row['opportunity_occurrence_id']==(occurrence if row['command_kind']=='qualification' else None), 'receipt occurrence mismatch')
        outputs=expected['outputs']
        opening=next((o['episode_id'] for o in outputs if o['transition_kind']=='opened'),None)
        reduce = legacy._reduce if row['snapshot_format_version'] == legacy.FORMAT else _reduce
        state,actual=reduce(state,pre,fact,gen,row['command_kind'],key,opening,[o['id'] for o in outputs])
        _require(c.canonical_json(actual)==c.canonical_json(expected),'incremental/full replay divergence')
        pre=actual['post_state']; previous=row
    if state:
        _require(state.episodes==l.project_episodes(state.events),'incremental episode projector diverges from full oracle')
    return rows,state,pre


def verify_history(conn, *, condition_id):
    with ch._write(conn,'corner_lifecycle_verify') as cur:
        condition,key=_condition(cur,ch._uuid(condition_id),lock=True)
        rows,_,post=_replay(cur,condition,key)
        return {'applications':len(rows),'post_state':post,'post_state_sha256':c._digest(post).hex()}


def rebuild_projections(conn, *, condition_id):
    """Recovery only: validate/replay first, then replace BOTH projections atomically."""
    with ch._write(conn,'corner_lifecycle_rebuild') as cur:
        condition,key=_condition(cur,ch._uuid(condition_id),lock=True)
        rows,state,post=_replay(cur,condition,key)
        cur.execute('DELETE FROM corner.condition_processing_projections WHERE condition_id=%s',(condition['id'],))
        cur.execute('DELETE FROM corner.opportunities WHERE condition_id=%s',(condition['id'],))
        for row in rows:
            _project(cur,row)
        _check_projection(cur,condition['id'],rows[-1] if rows else None)
        if state:
            cur.execute('SELECT * FROM corner.opportunities WHERE condition_id=%s ORDER BY opened_at,id',(condition['id'],))
            actual=cur.fetchall()
            expected=sorted(state.episodes,key=lambda e:(e.opened_at,e.id))
            _require(len(actual)==len(expected),'episode projection cardinality mismatch')
            for row,episode in zip(actual,expected):
                _require((row['id'],row['episode_generation_id'],row['opened_at'],row['current_occurrence_id'],row['closed_at'],row['close_reason'])
                    ==(episode.id,episode.generation_id,episode.opened_at,episode.current_occurrence_id,episode.closed_at,episode.close_reason),
                    'rebuilt episode projection mismatch')
        return {'applications':len(rows),'post_state':post,'post_state_sha256':c._digest(post).hex()}
