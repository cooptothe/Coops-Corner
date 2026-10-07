# Runtime roles and durable work — Migration 012

This slice implements Orchestration Decisions 2–3, not the polling worker.
`corner/work.py` provides storage/lease APIs and a bounded dispatcher to the existing
five domain operations. That storage module has no background loop, routing graph,
reconciliation scan, provider request, alert sender or new lifecycle policy.
Discovery-only scans are a separate follow-up module described below.

## Records and identities

- `work_requests`: immutable intent, scoped discovery deduplication key, format/digest,
  and typed optional references for scope/cause. Repeated identical discovery returns
  the original request and does not change its schedule. Changed intent conflicts.
  Work kinds are reference vocabulary; retired kinds reject new intent, not historical
  retries. Producers must define operation-specific dedupe/routing versions; no
  generic condition-level coalescing is performed here.
- `prepared_work_commands`: one immutable command per request. Its versioned snapshot
  retains domain authority/key (except native occurrence identity), complete serialized
  command including actual capture/business times, implementation identity, and digest.
  No UPDATE/DELETE/TRUNCATE. Re-preparing with different evidence is a conflict.
- `work_executions`: mutable status, due time, claim/retry counts, lease tuple, last
  failure summary and typed completion references. This is not an attempt-history
  ledger. The latest failure metadata can remain after successful completion; status
  and the authoritative result are decisive, not absence of earlier error metadata.

The request deduplication key is not the domain command key. Two requests may converge
on one domain result through its own idempotency contract. There is no uniqueness on
prepared domain keys across requests. Domain ledgers never point back into work tables.

Supported work/result relationships are:

| Kind | Result |
| --- | --- |
| evaluate | EngineEvaluation |
| qualify | QualificationDecision |
| ensure_occurrence | OpportunityOccurrence |
| assess | ActionabilityAssessment |
| apply_lifecycle | LifecycleApplication |

Request scope is validated against preparation. Completion reloads the authoritative
result and verifies authority/key and command contents. Occurrence completion verifies
the frozen qualification identity instead. SQL independently enforces typed FKs,
request/kind agreement, request/preparation agreement and exactly the completion
reference allowed for the kind. Adding a future work kind with another result family
requires deliberate dispatcher and result-shape changes, not merely a vocabulary row.

## Transactions and fencing

Use READ COMMITTED and a non-owner worker login with the documented roles. The caller
owns commit/rollback. Each API uses a savepoint to contain failure, not to take over
the surrounding transaction. Commit claims promptly; do not hold locks while making
HTTP requests or capturing evidence outside the database.

1. `enqueue` creates intent and a ready execution atomically.
2. `claim` selects ready/due-retryable or expired-leased work using `FOR UPDATE SKIP
   LOCKED`, changes ownership/token and increments claim_count. Waiting/blocked work
   is never accidentally claimable because a date is old.
3. If `load_prepared` returns nothing, capture/construct the domain command. `prepare`
   then re-locks execution and validates owner/token and **database wall-clock** expiry
   before committing it. A stale capture cannot be frozen after another worker reclaims.
4. `complete` locks execution and checks its fence, loads the frozen command, invokes
   its existing adapter, checks the returned result and marks completion in one transaction.

All paths follow **execution -> condition/channel** lock order. Lease validation uses
`clock_timestamp()` in a separate statement after row-lock acquisition, not transaction
start `now()`. A valid completion keeps the row locked through commit. If wall-clock
expiry passes during that bounded transaction, the lock holder can still commit.
Queue claimers skip the locked row; they cannot reclaim it. A targeted locking writer
would wait and then observe completion. No post-adapter expiry check undoes that
already-acquired fence.

`heartbeat` cannot renew an expired token. `record_failure` requires the original
still-valid fence, so an obsolete worker cannot even overwrite error metadata.

After an execution exception, **roll back the caller transaction**, then use a NEW
short transaction to record retryable/waiting/blocked. Retryable work requires an
explicit retry time. Backoff limits, prerequisite resolution and failure classification
are caller policies, not guessed product defaults in this module.

`resume` is an explicitly authorized prerequisite/admin operation for waiting or
blocked work. It preserves preparation. It cannot revive completed work. Changing a
frozen command/build requires a new request; unsupported builds raise WorkBlocked.

## Crash and outcome semantics

Before preparation commit, a replacement worker may capture at its actual later time.
After preparation commit, it must reuse the exact retained command. Scheduled deadline
is explanatory intent, never a substitute for assessed_at/evaluated_at. Equality at a
freshness deadline remains actionable; future deadline discovery must account for this.

Domain effects and completion commit together or neither commits. A lost response after
commit is recovered through read-only `load_execution`, which validates the completion's
prepared command/result relationship without execution. Calling `complete` with an old
token does not create another completion.

Not-evaluable evaluations, negative qualifications, and ignored/already-reflected
lifecycle receipts are successful work results. They are never automatically converted
into transient failures. Waiting means missing prerequisite; blocked means intervention
is required. No attempt ledger or external delivery/outbox is introduced.

## Authority and remaining operational work

Queue state is not domain truth. A completed work row identifies an authoritative
domain result; it does not itself establish qualification or an open episode.
Runtime DML is trusted service code: SQL protects immutable records and row shapes,
while fencing/semantic ownership/admin authorization are enforced by these APIs.
This is not a SQL stored-procedure sandbox against a malicious worker with direct
UPDATE privileges. Do not expose these tables or caller-supplied authority to members.

Discovery-only reconciliation is now implemented separately in
`corner/reconciliation.py`; see [RECONCILIATION.md](RECONCILIATION.md). Its three
bounded sweeps only enqueue/recover requests. UUID/timestamp cursors cannot
permanently exclude older records from later passes. A completed evaluate request
with versioned condition/generation/target routing is retained as assignment
evidence; no retention/purge policy is added. A bounded executor for occurrence,
qualification, lifecycle work and evaluate capture is now in `corner/worker.py`; see
[EXECUTION_WORKER.md](EXECUTION_WORKER.md). The optional `kinds` claim filter leaves
unsupported assessment capture work untouched. Continuous polling and production
phase validation are still deferred; storage tests alone do not establish eventual
orchestration. See [EVALUATION_CAPTURE.md](EVALUATION_CAPTURE.md).

## Verification

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:CORNER_TEST_DATABASE = '1'
$env:CORNER_TEST_CONCURRENCY = '1'
python -m unittest discover -s tests -p test_corner_work.py -v
```

Tests create isolated NOLOGIN roles and a disposable database with migrations 002–012;
cleanup drops only the generated test database/roles. Cases cover non-owner execution,
dedupe, all five adapters, wrong-result rejection, frozen preparation, waiting/blocking,
wall-clock expiry, stale heartbeats/failure writes, concurrent claims, capture/reclaim
races, completion through expiry, atomic domain rollback and lost acknowledgements.

See [PostgreSQL locking](https://www.postgresql.org/docs/18/sql-select.html#SQL-FOR-UPDATE-SHARE)
and [wall-clock functions](https://www.postgresql.org/docs/18/functions-datetime.html#FUNCTIONS-DATETIME-CURRENT).
