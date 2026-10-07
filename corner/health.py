"""Read-only current health, not a scheduler or retained telemetry ledger.

Database snapshots own a short REPEATABLE READ, READ ONLY transaction. Domain
metrics use verified journal replay, never disposable projections/current quotes.
Limits fail explicitly rather than presenting partial counts as global health.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math

from psycopg2.extensions import TRANSACTION_STATUS_IDLE
from psycopg2.extras import RealDictCursor

from corner import assessments as a, actionability_v2 as a2, lifecycle_versions as lifecycle


class HealthEvidenceError(ValueError):
    """No trustworthy health snapshot could be established."""


class HealthLimitExceeded(ValueError):
    """Explicit resource bound reached; no partial all-system metrics returned."""


@dataclass(frozen=True)
class HealthLimits:
    max_conditions: int = 100
    max_applications_per_condition: int = 1000
    max_activations_per_channel: int = 1000
    statement_timeout_ms: int = 5000
    connect_timeout_seconds: int = 5

    def __post_init__(self):
        if any(type(v) is not int or v < 1 for v in vars(self).values()):
            raise ValueError('positive integer health limits required')


@dataclass(frozen=True)
class QueueHealth:
    blocked_count: int
    waiting_count: int
    due_retryable_count: int
    expired_lease_count: int
    oldest_waiting_last_updated_at: datetime | None
    oldest_blocked_last_updated_at: datetime | None
    completion_interval_start: datetime
    completion_interval_end: datetime
    completion_count: int
    completion_throughput_per_second: float


@dataclass(frozen=True)
class Deadline:
    kind: str
    evidence_id: str
    at: datetime
    end_inclusive: bool

    def passed(self, at):
        return at > self.at if self.end_inclusive else at >= self.at


@dataclass(frozen=True)
class ConditionHealth:
    condition_id: str
    last_application_id: str | None
    processed_activation_id: str | None
    next_required_activation_id: str | None
    missing_activation_count: int
    oldest_unprocessed_activation_at: datetime | None
    open_episode_id: str | None
    accepted_assessment_id: str | None
    overdue_deadlines: tuple[Deadline, ...]


@dataclass(frozen=True)
class DomainHealth:
    conditions: tuple[ConditionHealth, ...]
    conditions_with_activation_lag: int
    oldest_unprocessed_activation_at: datetime | None
    maximum_missing_activation_count: int
    open_conditions_with_overdue_assessment_deadline: int


@dataclass(frozen=True)
class Coverage:
    assessment_deadline_discovery: str = 'unsupported'
    assessment_deadline_health: str = 'observable_but_not_automatically_reconciled'
    market_dependency_reevaluation: str = 'unsupported'
    market_dependency_health: str = 'not_computed'
    retained_discovery_telemetry: str = 'unsupported'


@dataclass(frozen=True)
class HealthSnapshot:
    database_wall_clock_at: datetime
    queue: QueueHealth
    domain: DomainHealth
    coverage: Coverage = Coverage()
    scope: str = 'all_visible_conditions'
    evidence_basis: str = 'repeatable_read_database_snapshot'


def _instant(value):
    at = datetime.fromisoformat(value)
    if at.tzinfo is None: raise HealthEvidenceError('naive deadline')
    return at.astimezone(timezone.utc)


def assessment_deadlines(row):
    """Decode a previously verified assessment; preserve versioned boundaries.

Authority deadlines already inapplicable at assessment are not new expiry
obligations. A deadline indicates a need to recheck, not a new negative judgment.
"""
    version, result = row['snapshot_format_version'], row['result_snapshot']
    if version not in (a.FORMAT_VERSION, a2.FORMAT):
        raise HealthEvidenceError('unsupported assessment deadline format')
    deadlines = []
    if result['target_deadline'] is not None:
        deadlines.append(Deadline('target', row['id'], _instant(result['target_deadline']), True))
    deadlines.extend(Deadline('reference', item['observation_id'], _instant(item['deadline']), True)
                     for item in result['reference_deadlines'])
    if version == a2.FORMAT:
        if result['quote_deadline_end_inclusive'] is not True:
            raise HealthEvidenceError('unsupported quote deadline boundary')
        for item in result['authority']['deadlines']:
            if item['kind'] not in ('phase', 'rules', 'approval') or type(item['end_inclusive']) is not bool:
                raise HealthEvidenceError('unsupported authority deadline')
            if item['valid_until'] is None: continue
            deadline = Deadline(item['kind'], item.get('approval_id', item.get('record_id', item['stream'])),
                                _instant(item['valid_until']), item['end_inclusive'])
            if item.get('valid_from') and _instant(item['valid_from']) > row['assessed_at']: continue
            if not deadline.passed(row['assessed_at']): deadlines.append(deadline)
    return tuple(sorted(deadlines, key=lambda d: (d.at, d.kind, d.evidence_id)))


def queue_health(cur, at, interval):
    start = at - interval
    cur.execute('''SELECT
        count(*) FILTER (WHERE status='blocked') AS blocked_count,
        count(*) FILTER (WHERE status='waiting') AS waiting_count,
        count(*) FILTER (WHERE status='retryable' AND available_at<=%s) AS due_retryable_count,
        count(*) FILTER (WHERE status='leased' AND lease_expires_at<=%s) AS expired_lease_count,
        min(updated_at) FILTER (WHERE status='waiting') AS oldest_waiting_last_updated_at,
        min(updated_at) FILTER (WHERE status='blocked') AS oldest_blocked_last_updated_at,
        count(*) FILTER (WHERE status='completed' AND completed_at>%s AND completed_at<=%s) AS completion_count
        FROM corner.work_executions''', (at, at, start, at))
    values = dict(cur.fetchone())
    return QueueHealth(**values, completion_interval_start=start, completion_interval_end=at,
                       completion_throughput_per_second=values['completion_count'] / interval.total_seconds())


def _domain(cur, at, limits):
    cur.execute('SELECT id FROM corner.opportunity_conditions ORDER BY id LIMIT %s', (limits.max_conditions + 1,))
    conditions = cur.fetchall()
    if len(conditions) > limits.max_conditions: raise HealthLimitExceeded('condition limit exceeded')
    output = []
    for item in conditions:
        condition, key = lifecycle._condition(cur, item['id'])  # No lock / projection read.
        cur.execute('SELECT count(*) AS n FROM corner.lifecycle_applications WHERE condition_id=%s', (condition['id'],))
        if cur.fetchone()['n'] > limits.max_applications_per_condition:
            raise HealthLimitExceeded('application replay limit exceeded')
        rows, state, post = lifecycle._replay(cur, condition, key)
        cur.execute('''SELECT * FROM corner.channel_generation_activations WHERE channel_id=%s
            ORDER BY activation_sequence LIMIT %s''', (condition['qualification_channel_id'], limits.max_activations_per_channel + 1))
        activations = cur.fetchall()
        if len(activations) > limits.max_activations_per_channel: raise HealthLimitExceeded('activation limit exceeded')
        previous = None
        for seq, activation in enumerate(activations, 1):
            if (activation['activation_sequence'] != seq or activation['expected_previous_generation_id'] !=
                    (previous['new_generation_id'] if previous else None) or
                    (previous is not None and activation['activated_at'] < previous['activated_at'])):
                raise HealthEvidenceError('broken channel activation chain')
            command = lifecycle.ApplicationCommand(condition['id'], 'generation_activation', activation['id'],
                                                   activation['new_generation_id'], activation['activated_at'])
            lifecycle._input(cur, lifecycle._document(command), condition, key)
            previous = activation
        processed = post['activation_id']
        index = next((i + 1 for i, entry in enumerate(activations) if entry['id'] == processed), 0)
        if processed and not index: raise HealthEvidenceError('processed activation absent from channel history')
        pending = activations[index:]
        episode = state.open_episode if state else None
        overdue = ()
        if episode:
            if not post['assessment_id']: raise HealthEvidenceError('open episode without accepted assessment')
            assessment = lifecycle._one(cur, 'actionability_assessments', post['assessment_id'])
            # Replay already validated this evidence through its pinned interpreter.
            overdue = tuple(d for d in assessment_deadlines(assessment) if d.passed(at))
        output.append(ConditionHealth(condition['id'], rows[-1]['id'] if rows else None, processed,
            pending[0]['id'] if pending else None, len(pending), pending[0]['activated_at'] if pending else None,
            episode.id if episode else None, post['assessment_id'], overdue))
    dates = [c.oldest_unprocessed_activation_at for c in output if c.oldest_unprocessed_activation_at is not None]
    return DomainHealth(tuple(output), sum(c.missing_activation_count > 0 for c in output), min(dates) if dates else None,
                        max((c.missing_activation_count for c in output), default=0), sum(bool(c.overdue_deadlines) for c in output))


def read_health(connect, *, completion_interval=timedelta(minutes=5), limits=HealthLimits()):
    """Factory returns a new internal-reader connection; no shared transaction.

The sampled DB clock is distinct from MVCC visibility (this is not an as-of
historical query). Factory must enforce connect_timeout. Errors return no snapshot.
"""
    if not isinstance(completion_interval, timedelta) or completion_interval <= timedelta(0):
        raise ValueError('positive completion interval required')
    conn = connect(connect_timeout=limits.connect_timeout_seconds)
    try:
        if conn.autocommit or conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
            raise ValueError('new idle transactional connection required')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            cur.execute("SET LOCAL TIME ZONE 'UTC'")
            cur.execute("SELECT set_config('statement_timeout',%s,true)", (str(limits.statement_timeout_ms),))
            cur.execute('SELECT clock_timestamp() AS at')
            at = cur.fetchone()['at']
            queue = queue_health(cur, at, completion_interval)
            try:
                domain = _domain(cur, at, limits)
            except (ValueError, KeyError, TypeError, ArithmeticError) as error:
                if isinstance(error, HealthLimitExceeded): raise
                raise HealthEvidenceError('cannot verify authoritative domain health') from error
            return HealthSnapshot(at, queue, domain)
    finally:
        try: conn.rollback()
        finally: conn.close()


@dataclass(frozen=True)
class PartitionTelemetry:
    obligation: str
    channel_id: str | None
    current_process_last_visit_age_seconds: float | None
    current_process_last_scan_completed_age_seconds: float | None
    current_process_completed_passes: int


@dataclass(frozen=True)
class ProcessTelemetry:
    process_instance_id: str
    observed_at: datetime
    current_process_reconciliation_invalid_count: int
    current_process_counters: tuple[tuple[str, int], ...]
    current_process_partition_visit_state: tuple[PartitionTelemetry, ...]
    retention: str = 'ephemeral_process_local'


def process_telemetry(poller, *, process_instance_id):
    """Call on the poller thread BETWEEN cycles; no DB access or global aggregation.

Caller supplies a fresh identity for every process restart/poller reset. Existing
poller clocks are monotonic: report elapsed ages, never invented UTC scan instants.
"""
    if not isinstance(process_instance_id, str) or not process_instance_id.strip(): raise ValueError('process identity required')
    now = poller.clock()
    age = lambda value: max(0, now - value) if value is not None else None
    partitions = tuple(PartitionTelemetry(p.obligation, p.channel_id, age(s.last_visit), age(s.last_pass), s.passes)
                       for p, s in poller.discovery.items())
    return ProcessTelemetry(process_instance_id, datetime.now(timezone.utc), poller.totals['reconciliation_invalid'],
                            tuple(sorted(poller.totals.items())), partitions)


OPERATOR_ACTIONS = {
    'blocked_count': 'Inspect blocked_reason; do not automatically retry or bypass the request.',
    'waiting_count': 'Inspect waiting_reason and the prerequisite; resume only through the reviewed API.',
    'due_retryable_count': 'Inspect worker progress, available_at and retry classification.',
    'expired_lease_count': 'Inspect worker health and reclaim activity; expiry does not prove lock availability.',
    'conditions_with_activation_lag': 'Inspect activation reconciliation and lifecycle application processing.',
    'maximum_missing_activation_count': 'Inspect ordered activation processing; do not skip predecessors.',
    'open_conditions_with_overdue_assessment_deadline': 'Known discovery gap: investigate manually; this signal does not schedule reassessment.',
    'current_process_reconciliation_invalid_count': 'Investigate integrity/routing failures; do not bypass with duplicate work.',
}


@dataclass(frozen=True)
class Threshold:
    signal: str
    warning_at: float
    critical_at: float

    def __post_init__(self):
        if (self.signal not in OPERATOR_ACTIONS or any(isinstance(v, bool) or not math.isfinite(v)
            for v in (self.warning_at, self.critical_at)) or not 0 <= self.warning_at <= self.critical_at):
            raise ValueError('explicit supported threshold required')

    def classify(self, value):
        if not math.isfinite(value) or value < 0: raise ValueError('nonnegative finite signal required')
        return ('critical' if value >= self.critical_at else 'warning' if value >= self.warning_at else 'normal',
                OPERATOR_ACTIONS[self.signal])
