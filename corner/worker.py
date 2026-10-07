"""One bounded execution attempt; no polling, discovery or lifecycle logic.

The connection factory supplies a NEW non-owner connection per transaction with
authenticated runtime authority. This module owns commit/rollback/close. Only
evaluate capture, occurrence, qualification and persisted lifecycle evidence are supported.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

import psycopg2
from psycopg2.extras import RealDictCursor

from corner import assessments as a, channels as ch, evaluations as ev
from corner import lifecycle_store as ls, qualifications as q, work as w
from corner import evaluation_capture as ec

KINDS = ('ensure_occurrence', 'qualify', 'apply_lifecycle', 'evaluate')
TRANSIENT_SQLSTATES = {'40001', '40P01', '55P03', '57014'}


class WaitingForPrerequisite(Exception):
    """Known missing append-only prerequisite, not analytical ineligibility."""


@dataclass(frozen=True)
class WorkerSettings:
    owner: str
    authority: ch.ChannelAuthority
    lease_for: timedelta
    retry_delay: timedelta
    max_retries: int
    statement_timeout: timedelta

    def __post_init__(self):
        ch._text(self.owner)
        ch._authority(self.authority, 'validate-worker-settings')
        for duration in (self.lease_for, self.retry_delay, self.statement_timeout):
            w._duration(duration)
        w._require(self.statement_timeout >= timedelta(milliseconds=1), 'statement timeout must be at least 1ms')
        w._require(type(self.max_retries) is int and self.max_retries >= 0, 'nonnegative retry limit required')


@contextmanager
def _transaction(connect, settings, *, read_only=False):
    conn = connect()
    try:
        w._require(not conn.autocommit, 'worker requires transactional connections')
        with conn.cursor() as cur:
            if read_only:
                cur.execute('SET TRANSACTION READ ONLY')
            cur.execute('SHOW transaction_isolation')
            w._require(cur.fetchone()[0] == 'read committed', 'worker requires READ COMMITTED')
            milliseconds = settings.statement_timeout // timedelta(milliseconds=1)
            cur.execute("SELECT set_config('statement_timeout', %s, true)", (str(milliseconds),))
        yield conn
        conn.commit()
    except BaseException:
        try:
            conn.rollback()
        except psycopg2.Error:
            pass  # Lost connection/acknowledgement is resolved using a fresh connection.
        raise
    finally:
        conn.close()


def _qualification_policy(cur, request):
    """Only pinned immutable policy, never today's current channel generation."""
    w._require(request['condition_id'] and request['generation_id'] and request['engine_evaluation_id'],
               'qualification requires explicit condition/generation/evaluation')
    condition, key = ls._condition(cur, request['condition_id'])
    generation = ls._generation(cur, request['generation_id'], condition)
    fact = ls._evaluation(cur, request['engine_evaluation_id'], key)
    w._require(fact.engine == generation.engine and fact.configuration_identity == generation.engine_configuration_identity,
               'evaluation incompatible with pinned generation')
    config = a._row(cur, 'qualification_channel_generations', generation.id)['configuration_snapshot']['qualification']
    w._require(request['intent_snapshot']['intent'].get('qualification') == config, 'qualification intent/policy mismatch')
    if config['implementation'] != {'name': 'minimum_ev', 'version': '1', 'revision': q.POLICY_REVISION}:
        raise w.WorkBlocked('pinned qualification implementation unavailable')
    policy = config['configuration']
    w._require(policy['policy_name'] == 'minimum_ev' and policy['comparison'] == 'greater_than_or_equal',
               'unsupported qualification policy')
    return q.MinimumEVPolicy(policy['policy_version'], Decimal(policy['minimum_ev_ratio']))


def _lifecycle_source(request):
    kind = request['intent_snapshot']['intent'].get('command_kind')
    w._require(kind in ls._SOURCE_COLUMNS, 'explicit lifecycle command kind required')
    w._require(request['condition_id'] and request['generation_id'], 'lifecycle condition/generation required')
    source = request[ls._SOURCE_COLUMNS[kind]]
    w._require(source is not None, 'missing lifecycle source')
    return kind, source


def _prerequisites(cur, request):
    if request['work_kind'] != 'apply_lifecycle':
        return
    kind, source = _lifecycle_source(request)
    condition, _ = ls._condition(cur, request['condition_id'])
    ls._generation(cur, request['generation_id'], condition)
    if kind != 'generation_activation':
        cur.execute('SELECT 1 FROM corner.lifecycle_applications WHERE condition_id=%s LIMIT 1', (request['condition_id'],))
        if cur.fetchone() is None:
            raise WaitingForPrerequisite('condition_uninitialized')
    if kind in ('qualification', 'assessment'):
        decision_id = source if kind == 'qualification' else a._row(cur, 'actionability_assessments', source)['qualification_decision_id']
        decision = a._row(cur, 'qualification_decisions', decision_id)
        if decision['decision_kind'] == 'qualified':
            cur.execute('SELECT 1 FROM corner.opportunity_occurrences WHERE qualification_decision_id=%s', (decision_id,))
            if cur.fetchone() is None:
                raise WaitingForPrerequisite('qualified_occurrence_missing')


def _build(cur, request):
    """Adapter command construction only. No EV/qualification/lifecycle decisions."""
    kind = request['work_kind']
    if kind == 'ensure_occurrence':
        w._require(request['qualification_decision_id'] is not None, 'occurrence qualification required')
        return request['qualification_decision_id']
    if kind == 'qualify':
        policy = _qualification_policy(cur, request)
        return q.QualificationCommand(request['engine_evaluation_id'], policy, w._now(cur))
    command_kind, source = _lifecycle_source(request)
    # Actual processing time, NOT activation/evaluation time or a past deadline.
    when = w._now(cur) if command_kind in ('qualification', 'generation_activation') else None
    return ls.ApplicationCommand(request['condition_id'], command_kind, source, request['generation_id'], when)


def _validate_prepared(cur, request, prepared):
    document = prepared['command_snapshot']
    w._require(document['work_kind'] == request['work_kind'], 'preparation work-kind mismatch')
    w._bind(cur, request, document)
    if request['work_kind'] == 'evaluate':
        ec.validate_frozen(cur, request, document)
    elif request['work_kind'] == 'qualify':
        policy = _qualification_policy(cur, request)
        w._require(document['payload']['policy'] == {'version': policy.version,
                   'minimum_ev_ratio': ev._decimal(policy.minimum_ev_ratio)}, 'frozen qualification differs from request policy')
    elif request['work_kind'] == 'apply_lifecycle':
        kind, source = _lifecycle_source(request)
        w._require(document['payload']['kind'] == kind and document['payload']['evidence_id'] == source,
                   'frozen lifecycle differs from request intent')


def _prepare(conn, lease, settings):
    request_id = lease['work_request_id']
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        w._fence(cur, request_id, settings.owner, lease['lease_token'])
        request = w._request(cur, request_id)
        frozen = w._prepared(cur, request_id)
        if frozen:
            _validate_prepared(cur, request, frozen)
            return  # Never call _build, regenerate timestamps or change authority/key.
        _prerequisites(cur, request)
        command = _build(cur, request)
    keyed = request['work_kind'] != 'ensure_occurrence'
    w.prepare(conn, request_id=request_id, owner=settings.owner, token=lease['lease_token'], command=command,
              authority=settings.authority if keyed else None,
              domain_key='corner.worker.v1:' + request_id if keyed else None)


def _complete(conn, lease, settings):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        request = w._request(cur, lease['work_request_id'])
        frozen = w._prepared(cur, lease['work_request_id'])
        w._require(frozen is not None, 'missing frozen preparation')
        _validate_prepared(cur, request, frozen)
        _prerequisites(cur, request)
    # The existing adapter takes/rechecks the execution fence and keeps it through
    # domain write + completion. No second worker/domain implementation lives here.
    return w.complete(conn, request_id=lease['work_request_id'], owner=settings.owner, token=lease['lease_token'])


def _prepare_evaluation(connect, lease, settings, validator):
    request_id = lease['work_request_id']
    with _transaction(connect, settings) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            w._fence(cur, request_id, settings.owner, lease['lease_token'])
            request = w._request(cur, request_id)
            frozen = w._prepared(cur, request_id)
            if frozen:
                _validate_prepared(cur, request, frozen)
                return  # No validator invocation, clock regeneration or recapture.
    # Release the row lock BEFORE selecting. An expired lease can now be reclaimed
    # while the old selector is slow. The capture transaction never writes intent.
    with _transaction(connect, settings, read_only=True) as conn:
        command = ec.capture(conn, request=request, validator=validator)
    with _transaction(connect, settings) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            w._fence(cur, request_id, settings.owner, lease['lease_token'])
            frozen = w._prepared(cur, request_id)
            if frozen:
                # A same-token concurrent preparer may have won. Its committed
                # command is authoritative; discard this uncommitted capture.
                _validate_prepared(cur, request, frozen)
                return
        w.prepare(conn, request_id=request_id, owner=settings.owner, token=lease['lease_token'], command=command,
                  authority=settings.authority, domain_key='corner.worker.v1:' + request_id)


def _classification(error, retry_count, settings):
    if isinstance(error, (WaitingForPrerequisite, ec.CaptureWaiting)):
        return 'waiting', str(error)
    code = getattr(error, 'pgcode', None)
    transient = code in TRANSIENT_SQLSTATES or (code and code.startswith('08')) or (
        isinstance(error, psycopg2.OperationalError) and code is None)
    if transient:
        return ('retryable', 'transient_database_error') if retry_count < settings.max_retries else ('blocked', 'retry_limit_reached')
    if isinstance(error, w.WorkBlocked):
        return 'blocked', 'implementation_unavailable'
    if isinstance(error, (ValueError, KeyError, TypeError, ArithmeticError)):
        return 'blocked', 'invalid_command_or_evidence'
    return 'blocked', 'execution_error'


def _recover(connect, settings, lease, error):
    """Only after attempt rollback; never reuse the failed transaction."""
    request_id = lease['work_request_id']
    try:
        with _transaction(connect, settings) as conn:
            # A lost completion acknowledgement is success if the persisted result
            # verifies. Do not rerun the reducer or overwrite completion metadata.
            execution = w.load_execution(conn, request_id=request_id)
            if execution and execution['status'] == 'completed':
                return {'status': 'completed', 'request_id': request_id, 'execution': execution}
            if isinstance(error, w.LeaseLost):
                return {'status': 'lease_lost', 'request_id': request_id}
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                current = w._fence(cur, request_id, settings.owner, lease['lease_token'])
                status, reason = _classification(error, current['retry_count'], settings)
                retry_at = w._now(cur) + settings.retry_delay if status == 'retryable' else None
            # Safe metadata only; do not persist SQL, credentials or raw error text.
            w.record_failure(conn, request_id=request_id, owner=settings.owner, token=lease['lease_token'],
                             status=status, reason=reason, retry_at=retry_at,
                             details_json=ev.canonical_json({'error_type': type(error).__name__,
                                                           'sqlstate': getattr(error, 'pgcode', None)}))
            return {'status': status, 'request_id': request_id, 'reason': reason}
    except w.LeaseLost:
        return {'status': 'lease_lost', 'request_id': request_id}


def run_once(connect, *, settings, request_id=None, evaluation_validator=None):
    """Claim at most one supported request. No sleep, auto-resume or polling loop.

Non-capture work commits claim, preparation, then domain+completion. Evaluate
also uses short precheck and read-only capture transactions before freezing.
Failure recording uses another fresh fenced transaction. A process crash leaves
the lease for later expiry/reclaim; a persisted preparation is always reused.
Connection/recovery failure propagates if durable state cannot be established.
"""
    w._require(isinstance(settings, WorkerSettings), 'validated worker settings required')
    lease = None
    try:
        with _transaction(connect, settings) as conn:
            lease = w.claim(conn, owner=settings.owner, lease_for=settings.lease_for,
                            request_id=request_id, kinds=KINDS)
        if lease is None:
            return {'status': 'idle', 'request_id': request_id}
        if lease['work_kind'] == 'evaluate':
            _prepare_evaluation(connect, lease, settings, evaluation_validator)
        else:
            with _transaction(connect, settings) as conn:
                _prepare(conn, lease, settings)
        with _transaction(connect, settings) as conn:
            execution = _complete(conn, lease, settings)
        return {'status': 'completed', 'request_id': lease['work_request_id'], 'execution': execution}
    except Exception as error:
        if lease is None:
            raise  # No owned intent exists on which to record a failure.
        return _recover(connect, settings, lease, error)
