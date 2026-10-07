# Discovery-only reconciliation — Orchestration Decision 4

`corner.reconciliation.sweep()` discovers three obligations using existing tables.
It only calls `work.enqueue`: no claims, preparation, capture, domain writes,
projection updates, scheduling loop, notification delivery, or live API calls.
There is no new migration. Use the existing `work_producer` runtime profile.

## Routing authority

A completed `evaluate` request is the durable routing assignment, not an engine
configuration match. Its immutable typed sources must contain `condition_id` and
`generation_id`; its intent must contain:

```json
{
  "routing_version": "corner.evaluation.routing/1",
  "target_scope": {
    "outcome_id": "canonical-outcome-uuid",
    "sportsbook_id": "canonical-sportsbook-uuid"
  }
}
```

Explicit producers can construct this intent with `evaluation_route()`. The
completed execution identifies the evaluation. Discovery validates the frozen
preparation, completion ownership, target, channel, exact engine implementation,
and full configuration before accepting the assignment. Historical references
are checked; current quotes are never selected.

Manual evaluations without completed routing requests are not scan candidates.
Completed requests lacking the required route are reported invalid/unrouted.
Do not edit old requests to adopt evaluations or assign them to today's generation.
An explicit adoption mechanism is deferred. Retain completed evaluation requests,
preparations and completion references: they now carry recovery routing evidence.

## Obligations

| Sweep | Candidate | Dedupe identity | Completion proof |
| --- | --- | --- | --- |
| `qualification` | Completed routed evaluate request | condition + generation + evaluation | Valid qualification using exact evaluation result digest and generation qualification configuration/implementation |
| `occurrence` | Every qualified decision | qualification decision | Its unique qualified-only occurrence |
| `activation` | Registered condition | condition + next activation | Verified receipt establishes processed activation and generation; verified head retains/advances that authority |

Namespaced keys are canonical JSON arrays in `reconcile.qualification.v1`,
`reconcile.occurrence.v1`, and `reconcile.activation.v1`. These namespaces are
reserved for this reconciler. They identify obligations, not domain commands.
New work contains immutable source/configuration intent but no generated domain
key or command timestamp; future preparation establishes those once.

Qualification discovery includes non-evaluable evaluations. It validates existing
judgments against persisted full-precision evidence (no EV recomputation); a
contradictory/corrupt judgment is invalid, never resolved by timestamp. Different
thresholds do not satisfy the assigned policy. Valid manually-created domain
results can fulfill obligations without a completed queue request.

Occurrences are global historical facts: no generation/freshness/episode filters.
They do not depend on an evaluation routing assignment.

Activation discovery reads verified journal receipts and their post-state markers,
including the receipt that successfully established the processed activation.
It does not read condition/episode projections. Referencing an activation in an
ignored command is not completion. New conditions request activation sequence 1;
initialized conditions request only the immediate successor. Missing predecessor
history is invalid. Discovery never skips straight to the latest generation.
An explicit later bootstrap already established by the lifecycle adapter remains
authoritative; this reconciler itself never creates such a bootstrap shortcut.

## Calls, traversal and transactions

```python
from corner.reconciliation import sweep

# One page only; the caller owns connection configuration and commit/rollback.
report = sweep(conn, obligation="qualification", limit=100,
               after=previous_cursor, channel_id=channel_id)
conn.commit()
next_cursor = report["next_cursor"]
```

`channel_id` optionally partitions qualification/activation sweeps. Occurrences
are not channel-scoped. `limit` is 1..1000 candidate roots, not a bound on all
dependent evidence reads or wall-clock time. Start with small pages. The first
version uses existing indexes; measure query plans and fan-out before tuning.

Each candidate has an isolated savepoint. Corrupt/unsupported evidence is reported
and scanning advances; database/connectivity failures propagate to the caller.
Run short READ COMMITTED transactions, commit each page, and roll back on failures.
Discovery acquires an advisory transaction lock per dedupe identity to serialize
concurrent reconciler enqueue/check operations; database uniqueness is still the
final deduplication backstop. No condition lock or runtime worker permission is
needed. Domain completion racing discovery may leave an unnecessary pending
request, which later idempotent execution can safely satisfy.

The returned cursor is temporary traversal state for exactly one sweep/partition.
At exhaustion it is `None`: the next invocation starts again. UUID ordering here
is pagination only, not commit chronology. A row committed behind a cursor appears
on a later pass. Cursor loss simply repeats inspection. No durable high-water mark
or `created_at > cursor` correctness assumption exists. Eventual coverage requires
the caller to repeatedly complete/wrap passes; no background process does that yet.

Counts and per-candidate items distinguish:

- `fulfilled`: authoritative evidence proves the obligation.
- `newly_requested`: this serialized discovery created its work request.
- `pending`: existing ready/retryable/waiting/leased work accounts for it.
- `blocked`: existing blocked work needs intervention; no replacement key is made.
- `invalid`: incompatible routing, malformed evidence, inconsistent completion,
  contradictory qualification, or activation history failure.

Counts describe the current transaction, not a durable guarantee. A blocked
request does not prevent scanning later candidates. A completed request is not
proof by itself: ownership is checked and authoritative completion is rechecked
before declaring a mismatch invalid. Discovery neither resumes blocked work nor
changes existing scheduling/preparation. Ordinary domain completion remains the
responsibility of the domain adapters and the future executor.

## Verification and deferred work

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:CORNER_TEST_DATABASE='1'
$env:CORNER_TEST_CONCURRENCY='1'
python -m unittest discover -s tests -p test_corner_reconciliation.py -v
```

Tests use disposable PostgreSQL and isolated roles. They exercise repeated scans,
all three concurrent discovery paths, real late commit behind a cursor, blocked
and invalid traversal, non-owner producer permissions, exact policy matching,
unrouted evaluations, duplicate explicit routes, missing projections, and ignored
out-of-order activations. Domain execution in fixture setup is test-only.

Still deferred: evaluation-arrival lifecycle discovery, qualification/assessment
application discovery, evidence-change routing graph, deadline reassessment,
polling, assessment capture, service login provisioning, and alert/UI delivery.
Deadline capture and lifecycle application will be separate future obligations.
The first bounded execution worker now handles occurrence, qualification and
lifecycle requests independently; see [EXECUTION_WORKER.md](EXECUTION_WORKER.md).
Evaluate capture is now a separate worker path with pinned validation authority;
see [EVALUATION_CAPTURE.md](EVALUATION_CAPTURE.md).
