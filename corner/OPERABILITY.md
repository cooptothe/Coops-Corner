# Operability Decision 1 — read-only health

`health.py` observes; it does not discover work, resume requests, assess markets,
apply lifecycle commands, rebuild projections, or deliver alerts. No schema or
telemetry migration, dashboard, service activation or production approval is added.

## Three different evidence boundaries

| API/data | What it establishes | What it cannot establish |
| --- | --- | --- |
| `read_health()` | Current visible database state and verified lifecycle history | Historical queue state durations or system-wide discovery coverage |
| `process_telemetry()` | This poller instance's counters and partition traversal | Previous processes, durable incidents, system-wide last successful scan |
| Future retained telemetry | Not implemented | Trends, incident histories and duration SLOs are not claimed today |

All returned snapshot dataclasses are frozen. Use `dataclasses.asdict` if a caller
needs a serialization projection; preserve explicit UTC timestamps and provenance.

## Queue definitions

A single database `clock_timestamp()` sample supplies every time comparison.

| Signal | Predicate / meaning |
| --- | --- |
| `blocked_count` | Current status is blocked |
| `waiting_count` | Current status is waiting |
| `due_retryable_count` | Retryable and available_at <= sampled database time |
| `expired_lease_count` | Leased and lease_expires_at <= sampled database time |
| `oldest_waiting_last_updated_at` | Minimum updated_at among current waiting rows |
| `oldest_blocked_last_updated_at` | Minimum updated_at among current blocked rows |
| `completion_count` | Completed rows whose completed_at lies in (interval_start, interval_end] |
| `completion_throughput_per_second` | completion_count / configured interval seconds |

Completion is counted by execution, not distinct domain result: two completed
operational requests may legitimately resolve to one idempotent domain result.
This is derived from retained current execution rows, not a separate attempt or
status-transition ledger. Retention/removal or exceptional administrative changes
would limit what it can prove. The default rolling interval is five minutes and
is explicitly returned with the count/rate.

Last update is **not** entry into a status. Expired is **not** immediately
reclaimable: a completing worker may hold the row lock. No zero-valued age is
invented when a category is empty; its timestamp is null.

## Domain progress

For every visible canonical condition, the reader verifies/replays the immutable
application chain and declared transition outputs through the existing versioned
adapter. It deliberately does not call the locking `verify_history` public writer
entry point or read either projection. No IDs are allocated during replay.

The channel activation chain is verified separately, including pending entries,
predecessor continuity and nondecreasing activation times.
The processed activation comes from the verified post-state, not the presence
of an activation-referencing command or its creation timestamp. Remaining
successors yield:

- `conditions_with_activation_lag`
- `oldest_unprocessed_activation_at`
- `maximum_missing_activation_count`
- Per-condition next required activation, processed activation and last receipt.

A registered, uninitialized condition can have activation lag without any receipt.
An activation is pending until its processing is proven, even if a queue request
is completed or an ignored receipt references it. These metrics do not enqueue
activation work.

Only an episode that remains open in replay contributes deadline risk. Its
**accepted** assessment determines the basis, not the newest persisted assessment
or an obsolete assessment/application. V1 quote deadlines use strict `now > end`;
v2 also decodes phase, approval and rules deadlines, preserving their individual
inclusive/exclusive boundaries. Authority windows already inapplicable at the
assessment are not counted as newly expiring obligations. Retained active windows
that expire are reasons to recheck authority, not proof of a new negative judgment.
The health reader never resolves today's authorities or recaptures quotes.

`open_conditions_with_overdue_assessment_deadline` counts conditions, not deadline
rows. Per-condition detail retains episode ID, accepted assessment ID, and overdue
deadline kind/evidence/time/boundary. Closed episodes and superseded bases contribute
no current deadline risk. Absence of overdue deadlines is **not** proof of current
actionability: quotes, trust or approvals could have changed since assessment.

Coverage is explicit:

```text
assessment_deadline_discovery = unsupported
assessment_deadline_health = observable_but_not_automatically_reconciled
market_dependency_reevaluation = unsupported
market_dependency_health = not_computed
retained_discovery_telemetry = unsupported
```

## Read-only transaction and limits

```python
from datetime import timedelta
from corner.health import read_health, HealthLimits

snapshot = read_health(
    reader_connection_factory,
    completion_interval=timedelta(minutes=5),
    limits=HealthLimits(),
)
```

Supply a **new idle transactional connection** authenticated with the existing
internal `reader` profile; the factory accepts/enforces `connect_timeout`. This
is an internal operational API, not a member-facing evidence endpoint. The reader
owns REPEATABLE READ / READ ONLY, then rolls back and closes, including on failure.
The transaction sets its local time zone to UTC so returned timestamps do not
depend on the connection's default zone.
No row/advisory writer locks or projection dependencies are introduced. A coherent
MVCC snapshot and its sampled database clock are not a historical as-of guarantee.
An activation committed during a read is visible on the next snapshot, not halfway
through this one.

Defaults cap conditions at 100, applications per condition at 1,000, activations
per channel at 1,000, and each SQL statement at five seconds. Full verified replay
is intentionally a bounded v1 health implementation, not an incremental production
dashboard optimization. Total latency can exceed a statement timeout. Deployment
must choose an appropriate scrape frequency and request/process budget.

Exceeding a size limit raises `HealthLimitExceeded`; it never returns partial
global counts. Corrupt/unsupported history raises `HealthEvidenceError`; connection,
permission and SQL timeout errors propagate. Treat a failed health read as
**unknown/error**, never replace it with a green/zero snapshot. The all-visible
scope assumes the standard internal reader privileges, not an RLS-restricted role.

## Ephemeral telemetry and thresholds

Call `process_telemetry(poller, process_instance_id=...)` on the poller thread
**between cycles**, e.g. inside its reporting callback. Give each restart or poller
reset a new instance identity. Counts and partition pass/visit state are copied;
they are not stored or combined with previous processes.

The existing poller records monotonic times, so this API reports elapsed seconds
since the current process's last visit/completed partition pass. It does not
fabricate UTC `last_scan_completed_at` timestamps from them. Null means no visit
or completed pass in this instance. `observed_at` is only the export sampling time.
`current_process_reconciliation_invalid_count` counts invalid encounters, not
unique corrupt obligations: repeated scans can count the same candidate again.

`Threshold(signal, warning_at, critical_at)` is optional external configuration
for the listed count signals, with inclusive comparisons and no implicit defaults.
It returns a level and operator action; it sends no alert and changes no data.
Duration/SLO thresholds are not invented from missing status-entry telemetry.

| Condition | Operator action |
| --- | --- |
| Blocked work | Inspect blocked_reason; do not auto-retry or create bypass keys |
| Waiting work | Investigate prerequisite; resume only through the reviewed API |
| Due retries / expired leases | Inspect worker progress, health and reclaim activity |
| Activation lag | Inspect reconciliation and ordered application processing |
| Overdue assessment | Known discovery gap; investigate manually |
| Reconciliation invalid | Investigate integrity/routing; do not bypass with duplicate work |

## Verification

`tests/test_corner_health.py` uses synthetic evidence and disposable PostgreSQL
with the non-owner reader role. It covers exact queue/window boundaries, locked
expired leases, activation lag without projections, accepted versus obsolete
assessment evidence, v1/v2 deadlines, negative closure, read-only/no-XID behavior,
concurrent-commit snapshot isolation, explicit errors/limits, and process resets.
No real source is authorized by these tests.

Verified on 2026-09-30: **18/18 health tests**, **507/507 full regression tests**
with database and concurrency opt-ins enabled. Existing pinned domain/reducer
implementations remain unchanged.
