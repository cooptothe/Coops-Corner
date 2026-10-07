# Orchestration Decision 5 — bounded polling and shutdown

Status: implemented as an opt-in finite library loop in `polling.py`; not activated
as a service. No background process starts on import.

Update: the explicit routing prerequisite below is now implemented through
`versioned_dispatch.py` and `versioned_reconciliation.py`; see
[VERSIONED_DISPATCH.md](VERSIONED_DISPATCH.md). Original entry points remain
version-pinned. The additional discovery obligations remain deferred.

The poller schedules existing discovery and execution adapters. It never decides
EV, qualification, actionability, generation authority, or episode state. No
notifications, live provider polling, alert delivery, or new tables are in scope.
Production-positive authorization remains disabled.

## Deployment verification (2026-09-28)

The configured main database is local `odds_data_pipeline`, PostgreSQL 18.6.
Inspection found Migration 013's validated transition constraint already present,
including all five v2 authorization/conditioning closure reasons. No DDL was
reapplied and no claim is made about who applied it previously.

The nine existing `corner_*` runtime profiles are NOLOGIN/non-owner and lack
privileged role attributes or schema creation rights. Checks passed for 405
table-level UPDATE/DELETE/TRUNCATE privileges and 135 column-level UPDATE
privileges across 15 immutable ledgers. Analysis, worker and recovery profiles
retain the required assessment/lifecycle INSERT permissions and inherited read
access. Migration 013 requires no new grants. Login credentials and service
membership remain separate deployment work.

The full regression run passed **444/444** with database/concurrency opt-ins:
rollback-only tests used the configured main database, while isolated schema,
role and concurrency suites used disposable databases. No polling was started.

## Dispatch and discovery coverage

Versioned reconciliation covers three obligations: routed evaluation to
qualification, qualified decision to occurrence, and activation to condition
application. The poller uses `versioned_reconciliation.py` and
`versioned_dispatch.py`, not the original v1-only reconciliation/worker entry
points. Existing explicit evaluation/assessment requests are executable through
their pinned handlers; this loop does not invent their discovery obligations.

Before enabling each route, provide a tested version-aware discovery/dispatch
adapter. Dispatch must resolve the exact immutable request intent and, when
present, prepared-command format and pinned revision. Work kind alone cannot
select v1 versus v2. Never send a v2 request through a permissive v1 fallback.
Unavailable formats/builds must be surfaced and, where safely claimable, fenced
as blocked using the existing operational API; do not manufacture domain results.

Additional obligations remain outside the existing three sweeps: evaluation and
qualification arrival application, assessment/deadline discovery, and configured
market-dependency reevaluation. A first bounded loop can prove progress for its
enabled routes and explicit requests, not end-to-end autonomous freshness for
every condition. Expose coverage and disabled routes rather than implying these
gaps disappear because polling exists.

## Bounds and fairness

All values are explicit validated deployment configuration. Suggested *local
test* starting values, not production freshness or throughput guarantees:

| Control | Local default |
| --- | --- |
| Candidate roots per reconciliation page | 25 (existing API supports 1–1000) |
| Pages per sweep/partition visit | 1 |
| Execution attempts per cycle | 5 total, at most one per enabled kind per round |
| Worker concurrency | 1 in the first slice |
| Idle delay | 250 ms initially, capped at 5 s, bounded jitter |
| Sweep revisit interval | configurable; initial local target 5 s |
| Infrastructure-error delay | bounded exponential delay, capped at 30 s |
| Graceful shutdown window | explicit; local starting value 30 s |
| Cycle admission budget | 10 s; an admitted operation may finish afterward |
| Whole page/attempt budget | 30 s, checked at DB boundaries with SQL cancellation |
| Connection / lock timeout | 5 s / 2 s |

Connection, lock/statement, capture and overall attempt deadlines must also be
explicit. A SQL statement timeout is not a bound on a whole page or attempt;
each may issue multiple queries. Bound leaf operations and support cancellation
at safe transaction boundaries. Lease duration/renewal use existing fenced APIs,
with heartbeat cadence comfortably shorter than lease duration when enabled.
No new claim may start after the cycle's admission/time budget is exhausted.

Use a persistent-in-process round-robin position across enabled work kinds,
versions and channel partitions. Do not restart fairness at the first kind when
a cycle budget ends. A busy evaluation queue cannot starve assessment or
lifecycle work. Claim one item immediately before executing it; do not preclaim
a batch whose leases age while it waits locally. Candidate reads are hints;
the existing atomic claim decides ownership. A lost claim race consumes a bounded
inspection attempt, not an unbounded inner retry loop.

Fairness guarantees visits/claim opportunities under finite workloads and bounded
operations, not a global execution order across processes. Per-condition and
channel serialization remains the adapters' responsibility.

## Cycle and discovery traversal

1. Check stop flag and budget.
2. Visit due discovery partitions, one bounded page each. Initial preferred order
   is activation, qualification, occurrence; rotate the starting position on later
   cycles so a time limit cannot permanently starve a later sweep.
3. Commit each page independently. Advance its cursor and publish committed
   counters only after commit. On failure roll back the page and retain/restart
   its traversal position; never skip work because a transaction failed.
4. Give each enabled execution route a bounded turn through its existing worker.
5. Yield/sleep interruptibly when idle or backing off. Do not hold database
   transactions, locks or leased-but-unstarted work while sleeping.

Use process monotonic time for budgets and sleep scheduling. Database wall-clock
time remains the lease authority; domain command/capture times retain their
existing semantics. Deadlines that were missed cause capture at the actual later
time, never at the intended wake-up time.

Cursors are temporary traversal positions, never commit watermarks. Reset on
restart and wrap on completion. To guarantee wrapping under sustained arrivals,
give each pass a fixed candidate-ID ceiling captured at pass start and scan only
through that ceiling. This is a traversal bound, not a claim that all commits
below it were visible. Late commits are found on subsequent passes.
`versioned_reconciliation.pass_ceiling()` and `sweep(through=...)` implement this
bound. Due execution traversal also uses a fixed ceiling per work kind, so new
arrivals cannot indefinitely extend a pass through older versions/channels.

Blocked/invalid candidates advance the scan after their outcome is recorded;
they must not monopolize a partition. Database/connectivity failures abort that
page and back off. Repeatedly scanning a blocked request never creates a new key.

## Waiting, retry and dispatch ownership

- `ready` and due `retryable` work, plus expired leases, use existing claim rules.
- `waiting` is not automatically claimable. A separate explicit prerequisite
  recheck may resume the same request only when its prerequisite is established;
  the first loop may leave this operator-controlled and report it clearly.
- `blocked` requires intervention. Do not auto-resume or create a replacement
  request to evade a frozen preparation or an unavailable implementation.
- Per-item failure classification, retry budget and `available_at` remain owned
  by the worker/work API. The poller only backs off its own infrastructure loop;
  it does not invent a second retry counter or rewrite scheduling fields.
- Persisted preparation always wins. No dispatcher recaptures to upgrade an old
  command, switch authority, or repair an unsupported serializer.
- Successful negative/non-evaluable domain outcomes count as completed work.

## Shutdown and crash recovery

On the first stop signal: stop admitting sweeps, claims and new captures; wake
interruptible sleeps; let an already-owned bounded attempt finish within the
grace window. A signal handler only requests shutdown, never commits, writes
failure metadata or releases a lease itself.

Once a valid completion transaction owns its execution-row fence, it can finish
the atomic domain-write/completion commit under the existing rules. Do not revoke
its token merely because the clock passes lease expiry during that transaction.

If grace expires, cancel/close the active operation through the supported driver
or supervisor boundary and stop. Do not fabricate completion/failure on an
ambiguous commit, expire another worker's lease, or change a frozen command.
Uncommitted work rolls back; an unreleased lease is reclaimed after expiry.
Restart resolves completion/preparation from persisted records. Any graceful
release optimization must use a separately reviewed fenced operation, not direct
updates from the poller; it is unnecessary for the first slice.

No automatic retry of an ambiguous commit outside the established idempotent
worker recovery path. A process crash may lose metrics, never domain authority.

## Observability

The loop's `emit(report)` callback receives cycle counters, elapsed time, planned
sleep and enabled/deferred coverage. `totals` accumulates process-local counters;
traversal state exposes last successful visit/pass times. Claims and reclaims
are counted after claim commit, not inferred from a racing candidate query.
Infrastructure exceptions preserve traversal and increment a separate counter.
These are telemetry, not durable completeness or exactly-once metrics.

Future structured per-item logs should carry cycle ID, route/version, request ID, condition/generation
IDs where applicable, and sanitized reason/error category. Do not log credentials,
raw provider payloads, approval documents, or lease tokens.

Counters: committed pages and candidates; fulfilled/newly_requested/pending/
blocked/invalid obligations; claims, completions, waiting, retryable, blocked,
lease losses and capture/preparation failures. Keep queue and discovery counts
separate; existing requests are not domain completion proof.

Additional deployment instrumentation remains deferred: due runnable backlog and age, waiting/blocked backlog, expired
leases, partition last successful visit/full pass, page/attempt/capture/commit
latencies, supported/disabled route coverage, and shutdown/drain duration.
Metric cardinality uses kind/version/reason, not observation/request IDs. Logs
may identify individual items. Queue age is operational, not market chronology.

## Acceptance before an opt-in loop is enabled

- Bounded calls/work per cycle; deterministic fairness under one continuously
  busy kind and multiple partitions; empty and contested queues do not spin.
- Repeated finite passes find late commits; arrivals cannot prevent wraparound.
- Page rollback/unknown commit does not falsely advance durable completeness;
  rescans converge using existing dedupe identities.
- V1 frozen commands retain v1 dispatch; v2 requests/preparations select their
  exact installed handler; unsupported versions fail closed without recapture.
- Waiting/blocked items remain visible without bypass keys or implicit resumes.
- Signal during sleep, capture, preparation, domain write and commit; bounded
  drain or rollback/reclaim; no partial result or stale-token metadata.
- Multiple pollers converge through existing claims, idempotency and condition
  locks. Restart preserves preparation, command timestamps and original results.
- Tests use synthetic authority and non-owner profiles. No test enables positive
  production assertions, provider polling, notifications or alert delivery.

## Explicit integration

The deployment supplies separate authenticated **non-owner** connection factories
for discovery and execution, plus the existing `WorkerSettings`. Each factory
must accept and enforce `connect_timeout`, return a new transactional READ
COMMITTED connection, and finish authentication within that bound. No owner
credential fallback or production authority catalog is supplied by the poller.

```python
from corner.polling import DatabaseBackend, Poller, PollSettings, Stop

settings = PollSettings()
stop = Stop()
backend = DatabaseBackend(
    discover_connect=discovery_connection_factory,
    execute_connect=worker_connection_factory,
    worker_settings=worker_settings,
    settings=settings,
    stop=stop,
    # source=deployment_owned_evidence_source, only when explicitly configured
)
poller = Poller(backend, settings=settings, stop=stop)
totals = poller.run(max_cycles=100, emit=emit_counters)
```

The hosting main-thread signal handler should only call `stop.request()`; it must
not raise through a committing transaction. Scheduler and backend share the same
stop object and polling settings (mismatches are rejected). No signal handlers
are installed globally by this library. `run_cycle()` is also available for
deterministic supervision/tests. `run()` requires a finite positive cycle count.

SQL is cancelled when the operation budget or shutdown grace expires; boundary
checks prevent recovery from writing misleading failure metadata afterward.
An in-flight completion may drain before grace expires. Cancellation rolls back
its uncommitted domain result and completion together, leaving the original
preparation and an expirable lease for recovery. Capture callbacks must bound
their own external I/O: Python cannot safely preempt arbitrary callback code.
A deployment supervisor remains necessary for a hard process deadline. This
loop does not add heartbeats or automatically resume waiting/blocked work.

Verification: `tests/test_corner_polling.py` has 24 tests covering deterministic
fairness, capped/interruptible backoff, fixed pass ceilings, late commits,
non-owner execution, competing pollers, frozen-command reclaim, graceful drain,
and grace-expiry rollback/reclaim. Tests use disposable databases and synthetic
evidence. Production-positive authorization remains disabled.

The full regression suite passed **489/489** on 2026-09-28 with
`CORNER_TEST_DATABASE=1` and `CORNER_TEST_CONCURRENCY=1`. No new migration or
background service was introduced, and pinned domain implementations were left
unchanged.
