# Bounded execution worker

`corner.worker.run_once()` claims at most one request and executes the existing
work-ledger protocol. No migration, background loop, reconciliation call, polling,
live-provider request, scheduler, alert delivery or new domain policy is added.

Supported kinds are `ensure_occurrence`, `qualify`, `apply_lifecycle`, and now
`evaluate`. Claims filter these kinds inside the existing `FOR UPDATE SKIP LOCKED`
query. `assess` remains untouched. Evaluate has separate versioned, fenced capture
transactions; see [EVALUATION_CAPTURE.md](EVALUATION_CAPTURE.md). The three-step
preparation flow below describes the original non-capture work kinds.

## Invocation and ownership

Supply a connection factory returning a **new**, transactional READ COMMITTED
connection using an explicitly provisioned non-owner worker service login. The
worker owns commit/rollback/close for each connection; do not pass an existing
application transaction or a shared connection. Deployment credentials and login
memberships are still a separate responsibility; the worker never creates them.

```python
from corner.channels import ChannelAuthority
from corner.worker import WorkerSettings, run_once

settings = WorkerSettings(
    owner=worker_instance_id,
    authority=ChannelAuthority("service", authenticated_service_identity),
    lease_for=configured_lease_duration,
    retry_delay=configured_retry_delay,
    max_retries=configured_retry_limit,
    statement_timeout=configured_statement_timeout,
)
receipt = run_once(connect_worker, settings=settings)
# Optional request_id restricts this single attempt to one existing request.
```

Durations and retry limits are explicit operational configuration, not production
defaults selected by this implementation. A positive statement timeout applies
to SQL in each transaction. This is a statement bound, not a hard end-to-end wall
clock bound. The factory must configure connection establishment timeouts. There
is no automatic heartbeat thread or sleeping retry loop in this slice.

## Transaction boundaries

1. Claim a supported ready/due-retryable or expired-leased execution; **commit**.
2. Check the active fence. Load the existing preparation first. If absent, validate
   prerequisites, construct the command, and freeze through `work.prepare`; **commit**.
3. Validate the frozen intent/prerequisites and call `work.complete`; **commit** the
   domain result and work completion together under its existing execution fence.

The domain adapters retain all semantic authority. The worker does not compute EV,
choose qualification results, interpret engine failure reasons as lifecycle events,
or change episode state itself. Existing preparation is never regenerated, including
its implementation, authority, command key and timestamps. First preparation uses
`corner.worker.v1:<work_request_id>` as its domain key under the configured authority;
occurrence creation keeps its native qualification identity and has no such key.
This is independent of the discovery dedupe key.

Crash before preparation commit: the next lease owner may construct a new command.
Crash after preparation commit: the next lease owner reuses it exactly. Lease expiry
before preparation/completion fencing rejects the attempt. Once `work.complete`
has acquired a valid fence, its row lock protects the bounded domain/completion
transaction even if wall-clock expiry passes before commit. No replacement worker
can reclaim the protected execution row.

## Preparation rules

- **Occurrence:** use the request's explicit qualification decision ID. The existing
  adapter enforces qualified-only occurrence creation and native idempotency.
- **Qualification:** require condition, generation, evaluation and the exact
  qualification intent snapshot. Validate the historical evaluation against that
  generation and use its pinned policy/implementation. Never consult the latest
  channel generation or infer a default policy. A preexisting frozen command with
  another threshold is blocked, not rewritten.
- **Lifecycle:** require an explicit `command_kind` and its corresponding typed
  evidence reference. Evaluation, qualification, assessment, and activation commands
  may consume already-persisted evidence. `transition_at` for qualification/activation
  commands is the actual database wall clock at preparation, not a backdated source
  timestamp. Other commands retain the adapter's own chronology semantics.

Qualification `decided_at` is also generated once at preparation. A delayed retry
does not generate a newer timestamp. If a frozen timestamp becomes incompatible
with later lifecycle history, the existing adapter may reject it; the worker never
silently advances the timestamp or substitutes a new command.

## Failure handling

The failed attempt is rolled back and its connection closed **before** opening a
fresh failure-recording transaction. Recovery first checks for a valid completed
result: a lost commit acknowledgement returns that completion without executing
again. Otherwise, failure recording must still own the original unexpired token.
Stale workers cannot replace a newer owner's error metadata.

| Outcome | Worker treatment |
| --- | --- |
| Any valid domain result, including negative/non-evaluable qualification or ignored/already-reflected lifecycle application | `completed` |
| Non-activation lifecycle command before condition initialization | `waiting: condition_uninitialized` |
| Qualification/assessment application missing the qualified decision's occurrence | `waiting: qualified_occurrence_missing` |
| Serialization/deadlock/lock-unavailable/query-cancel error (`40001`, `40P01`, `55P03`, `57014`), connection SQLSTATE class `08`, or unclassified connection `OperationalError` | `retryable`, subject to explicit retry budget |
| Transient error after retry budget is exhausted | `blocked: retry_limit_reached` |
| Unavailable frozen/pinned implementation | `blocked: implementation_unavailable` |
| Invalid command, evidence, policy or bindings | `blocked: invalid_command_or_evidence` |
| Other ordinary execution exception | `blocked: execution_error` |
| Expired/replaced lease token | `lease_lost`, no failure metadata write |

Retry scheduling uses database wall-clock time plus the configured fixed delay.
The retry budget counts recorded transient retries, not all claims or process
crashes. Persisted error details contain only error class and SQLSTATE, never raw
SQL, connection strings or exception text. Connection/recovery failure propagates
when durable state cannot be established; lease expiry remains the recovery path.

`waiting` and `blocked` requests are not automatically resumed. A prerequisite
resolver/operator must explicitly use `work.resume`; the same frozen preparation
is retained. Recovery requiring different immutable meaning needs a new request.
The worker does not create occurrences as a side effect of a waiting lifecycle
application, apply missing activations, repair projections, or reinterpret ignored
applications as retryable failures. Reconciliation remains responsible for finding
missing obligations; it still checks domain completion, not merely queue status.

`run_once` returns `idle` when no matching execution is claimable, otherwise its
request ID plus `completed`, `waiting`, `retryable`, `blocked`, or `lease_lost`.
Completed results include the original work execution receipt. A targeted call on
an already completed request is idle; `work.load_execution` provides read-only
receipt recovery when needed.

## Tests and next boundary

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:CORNER_TEST_DATABASE='1'
$env:CORNER_TEST_CONCURRENCY='1'
python -m unittest discover -s tests -p test_corner_worker.py -v
```

Tests use disposable PostgreSQL and actual non-owner roles/connections. They cover
reconciliation-to-execution convergence, all three supported kinds, crash/reclaim,
frozen-command reuse, stale preparation/completion/failure fences, concurrent
claims, completion past expiry under lock, lost acknowledgement recovery, atomic
rollback, waiting prerequisites, retry budgets, blocked resume, incompatible frozen
policy, and domain no-op/negative results counting as successful completion.

Still deferred: production validation adapters, `assess` capture, process polling loops,
automatic prerequisite wakeups, generation fan-out scheduling, production service
login configuration, deadline/evidence-change orchestration, and alert/UI delivery.
