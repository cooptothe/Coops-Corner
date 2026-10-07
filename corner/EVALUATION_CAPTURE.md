# Evaluate capture and execution

`corner.evaluation_capture` extends the bounded worker with `evaluate`. `assess`
remains unclaimed. No migration, polling loop, provider integration, automatic
prerequisite wakeup or production phase validator is introduced.

## Explicit intent and validation authority

Evaluate requests require typed `condition_id` and `generation_id`. Their intent
preserves `routing_version` and exact target scope, plus a pinned selector
format/revision and validation-adapter identity:

```python
from corner.evaluation_capture import request_intent, ValidationAdapter
from corner.evaluations import canonical_json
from corner.work import enqueue
from corner.worker import run_once

intent = request_intent(outcome_id=outcome_id, sportsbook_id=sportsbook_id,
                        validation_adapter=trusted_adapter_identity)
request = enqueue(conn, kind="evaluate", namespace=producer_namespace,
                  key=obligation_key,
                  sources={"condition_id": condition_id, "generation_id": generation_id},
                  intent_json=canonical_json(intent))
conn.commit()
validator = ValidationAdapter(trusted_adapter_identity, validate_market)
receipt = run_once(connect_worker, settings=settings, request_id=request["id"],
                   evaluation_validator=validator)
```

The adapter identity is an `ImplementationIdentity(name, version, revision)`.
Its revision must identify immutable validation code/policy. The trusted callback
receives `(read_only_connection, canonical_condition, evaluated_at)` and returns
an explicit `ev_selection.MarketValidation` bound to the event/market. Callbacks
are supplied by trusted runtime code, never dynamically loaded from request JSON.

**There is no production phase/settlement validator here.** Tests use visibly
synthetic evidence. Missing validation capability waits; different identity blocks.
The worker never infers phase or settlement from event status, schedule defaults,
or quote counts. Production use requires the separate trusted evidence contract.
This slice does not establish actionability.

The generation supplies the exact engine/configuration. Compatibility does not
create routing authority: the explicit request does. Completed requests retain
the existing reconciliation assignment `(condition, generation, evaluation)`.

## Transaction boundaries

1. Claim and commit the lease.
2. In a short transaction, validate the fence and load preparation first. If it
   exists, validate/reuse it and skip capture/freezing entirely.
3. Release the execution-row lock; capture in a **read-only** transaction. Validate
   pinned scope/builds, obtain explicit market validation, and call the existing
   selector. Quotes, dispositions and canonical contracts are read in its single
   MVCC SQL statement; no state/freshness filtering is added.
4. Re-lock execution and revalidate owner/token/database wall-clock expiry. Freeze
   through `work.prepare` and commit. If another preparer already committed, validate
   and reuse that command instead of persisting this speculative capture.
5. Execute the frozen command through `work.complete`; evaluation and work completion
   commit atomically under the existing fence.

The execution-row lock is not held during capture. A replacement worker may reclaim
an expired lease while the old selector is stalled. The old worker cannot persist
after losing ownership. No committed preparation permits a newer capture; an
existing preparation forbids recapture regardless of market or disposition changes.

`evaluated_at` is actual database wall-clock time when capture starts, not request
creation time, a past deadline, provider time, or an MVCC visibility cutoff. The
trusted validation adapter has separate evidence authority, preserved in the
command. Its external work needs explicit timeouts. No heartbeat thread is added;
a capture exceeding the lease may be discarded at the final fence.

## Frozen representation

The existing `EvaluationCommand` retains exact EV inputs/configuration. Its context
also includes selector format `corner.ev.selection/1`, selector implementation
digest, pinned validation-adapter identity, full market-validation assertions and
evidence strings, and capture/evaluation time. Existing prepared/evaluation digests
cover this context; no mutable capture table is introduced.

Frozen validation checks scope, supported formats/builds, time, and agreement
between validation and snapshot. It reads historical/canonical references only,
never trusted-current state. A retry needs no validation callback once preparation
exists, but still needs supported frozen serializer/selector/engine code. Unsupported
or malformed evidence blocks; it never triggers replacement. Authority, command
key, timestamps and exact observation IDs stay unchanged.

“Once” means one committed command, not exactly one selector invocation. Concurrent
speculative captures are allowed before preparation commits. Same-token preparers
reload the winner; different-token preparers must pass the active fence. Low-level
`work.prepare` retains its existing changed-command conflict behavior.

## Missing evidence and results

- No validation adapter: `waiting / evaluation_validation_unavailable`.
- No trusted target: `waiting / evaluation_target_missing`; no fake observation or
  evaluation, because the current engine snapshot requires an actual target.
- Route/contract/validation mismatch or malformed format: blocked.
- Unsupported pinned implementation: blocked.
- Stale/inactive targets, missing references, unsupported phase/settlement when a
  snapshot can be assembled: the existing engine decides. `not_evaluable` is a
  successful work result, not a worker failure.

Waiting/blocked work still requires explicit recovery/resume. There is no polling
or automatic prerequisite wakeup. Legacy evaluate intents without selector metadata
are not silently adopted or modified.

## Verification

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:CORNER_TEST_DATABASE='1'
$env:CORNER_TEST_CONCURRENCY='1'
python -m unittest discover -s tests -p test_corner_evaluation_worker.py -v
```

Disposable PostgreSQL tests cover non-owner capture, read-only enforcement, frozen
retries after market movement, real expiry/reclaim during paused selection,
same-token concurrent preparers, crash after preparation, missing evidence,
explicit routing through reconciliation, non-evaluable completion, unsupported
frozen formats, and assessment work remaining unclaimed. No API credits are used.
