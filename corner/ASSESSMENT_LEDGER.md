# Captured-state actionability assessments

Migration 010 adds only `actionability_assessments` and
`assessment_stream_evidence`. These are append-only evidence/judgment ledgers.
They do not activate a generation, register an occurrence, advance a condition
watermark, or open/continue/close an episode. An assessment is not permission to
apply a lifecycle transition.

## Two separate APIs

```python
capture_json = capture_assessment(
    conn,
    generation_id=generation_id,
    qualification_decision_id=qualified_decision_id,
    evaluation_watermark_id=watermark_evaluation_id,
    basis_assessment_id=previous_assessment_id,  # or None
    phase=validated_phase_evidence,
    phase_provenance_json=phase_provenance_json,
)
command = AssessmentCommand(capture_json, assessed_at, context_json='{}')
# Retain this exact immutable command and key until the outcome is known.
row = record_assessment(
    conn, authority=trusted_authority, assessment_key=issuer_key, command=command,
)
conn.commit()
```

The selector captures present trusted state. The persistence API validates immutable
evidence, computes `lifecycle.assess_actionability`, and derives all database fields.
There are no independently supplied result metrics, reasons, digests or evidence rows.
It neither queries `trusted_current_quotes` nor reruns EV or qualification.

Callers own READ COMMITTED transaction commit/rollback. Capturing is read-only and
can be separated from persistence. Write savepoints make the header and stream rows
atomic even when an exception is caught and earlier caller work is later committed.
Persistence returns before the caller commits; return alone is not durable receipt.

## Generation and upstream compatibility

The registered generation supplies complete engine, qualification and actionability
configuration. Its actionability implementation identity must equal
`corner.assessments.IMPLEMENTATION`. The revision identifies adapter, pure lifecycle,
serializer source and Python runtime. Register real retained build identities, not the
synthetic identities used by some earlier channel tests. Retain immutable deployment
artifacts; a digest does not archive executable code.

The adapter verifies supported snapshot formats, upstream command/result/configuration
digests, typed identity bindings, qualification-to-evaluation linkage, original
observation/input relationships, and matching engine/qualification configurations.
The qualification must be qualified, also enforced by a composite qualified-only FK.
It consumes contributing references from the immutable evaluation result, not every
reference the engine inspected and possibly excluded.

The watermark references an actual evaluation for the same sportsbook/Outcome and
compatible model. Its `(evaluated_at, id)` must not precede the qualified evaluation.
It may be a later not-evaluable evaluation. This does not replace the earlier qualified
analytical evidence with an unsuccessful result or infer threshold loss.

A basis assessment must exist and derive the same condition and generation. No
condition table is introduced. The adapter does not check whether that basis is still
accepted, whether the watermark remains current, or whether the generation is the
active channel head. Those are future LifecycleApplication responsibilities.

## What capture preserves

After loading immutable upstream facts, one SQL statement captures all expected
target/contributing-reference streams from `trusted_current_quotes`, with the same
MVCC visibility for selected and missing-stream evidence. It records database
`statement_timestamp()` and the visibility-snapshot token for diagnostics. The token
does not make a historical query executable after that transaction ends.

Every expected stream receives an explicit row:

```text
assessment_id
stream_role                 target | reference
sportsbook_id
outcome_id
selection_kind              selected_trusted_observation | missing_trusted_observation
selected_observation_id     nullable
selected_disposition_id     nullable
missing_reason              nullable
evidence_snapshot
```

Selected streams retain exact immutable quote values/timestamps and the disposition
identity, decision and timestamps used by the selector (or an explicit no-disposition
assertion). There is no active/freshness filter in selection and no fabricated fallback.

Missing streams retain the absence reason and every observed candidate's latest
rejection at capture. Each expected v1 stream necessarily has at least its evaluated
observation, so persistence requires rejection evidence for that known observation;
an empty assertion that it was never observed is rejected. A missing stream is not
an `unavailable` quote and cannot be represented by dropping an evidence row.

Relational uniqueness is per assessment/book/Outcome, with at most one target. CHECKs
tie selection kind to observation/null/missing-reason shape. FKs protect selected
observation/disposition references. The constructor additionally enforces complete
stream coverage, roles, actual quote-to-stream membership and disposition ownership.
Missing-stream witness details remain in the immutable snapshot and are validated
against the historical ledger, without adding indexes to the observation table.

The v1 missing-stream query can examine substantial history when a stream has no
eligible quote. Its witness size/cost is a known tradeoff to measure before broad
production polling; it is not a claim of bounded historical scan cost.

## Trust and phase provenance boundary

Capture is an internal trusted adapter, not a public endpoint accepting arbitrary
JSON. Persistence can verify referenced observations and disposition decisions exist
and match the retained values. It cannot independently prove that no other row was
visible in an earlier MVCC snapshot without retaining/reexecuting that snapshot.
Negative selection, selection completeness and no-disposition assertions therefore
retain selector provenance and rely on the trusted capture boundary. A content digest
is an integrity check, not a signature authenticating an untrusted caller.

Phase evidence is event-bound and retained with an explicit provenance source. The
adapter does not infer phase from the mutable/default `events.status`. A production
phase validator is still required; tests use clearly labeled synthetic evidence.
This migration does not claim real provider suspension/phase behavior has been verified.

## Time, deadlines and result representation

- `snapshot_captured_at`: database statement time of the present-state capture.
- `assessed_at`: explicit judgment time, at/after capture and watermark evaluation.
- `created_at`: database persistence time.
- `(assessed_at, id)`: deterministic assessment ordering, independent of evaluation
  ordering. Migration 010 does not choose a current accepted assessment.

An `assessed_at` value is not a historical visibility cutoff. This remains present-state
capture, not historical backtesting. Later facts cannot change an existing command.

The existing pure assessor checks exact observation alignment, phase, quote state and
the generation's supplied freshness limits. Deadlines are based on the evaluated
observations, not persistence time. All failed reasons and individual reference
deadlines are preserved. Primary-reason precedence remains the pure model's policy.

`actionable=true` requires a null primary reason; false requires a nonblank reason.
The query projection `target_deadline` is nullable when the current target is missing.
The result still preserves `evaluated_target_deadline` and `deadline_basis` explicitly:
absence does not erase the original analysis's deadline or silently alter pure policy.

## Serialization and retry semantics

Assessment format is `corner.actionability/1`; capture format is
`corner.actionability.capture/1`. Canonical snapshots use the existing exact JSON
serializer, base-10 Decimal strings, UTC microsecond timestamps, explicit nulls and
sorted expected streams/rejection witnesses. Context/provenance arrays retain order.
Formatting and object-key order are not command identity; floating-point JSON context
is rejected. UUIDs and capture fields originate in the canonical selector format.

`UNIQUE(authority_kind, authority_id, assessment_key)` identifies one command. The
persistence API checks an existing key before upstream revalidation or computation.
Same key and canonical command returns the original row/ID/timestamps. Changed captured
evidence, time, phase, bindings or context raises `AssessmentConflict`. A fresh capture
after market movement needs a new key; reusing the old key is not a retry.

Concurrent identical commands produce one header and one complete evidence set.
Concurrent computations with identical commands but different results preserve the
winner and raise `AssessmentDeterminismFailure`. No evidence rows from the losing
writer survive. Stronger transaction isolation may require whole-transaction retries.

Do not recapture before retrying. Restore the retained `AssessmentCommand` instead.
An exact retry returns the historical judgment even after its quotes or dispositions
change; LifecycleApplication must later decide whether it can affect current state.

## Protection and verification

Both tables reject UPDATE, DELETE and TRUNCATE, omit updated_at, and use RESTRICT FKs.
No authoritative relationship points to a lifecycle projection. Provision non-owner
runtime roles with the required SELECT privileges and SELECT/INSERT on these ledgers,
never mutation privileges or owner membership. PUBLIC receives no privileges.
Authentication and deployment-role provisioning remain separate work.

After applying 010, ordinary tests are rollback-only. The disposable pass creates
fresh databases, applies 002-010, runs the constraint matrix and real two-connection
races, and removes its databases. It requires the established local CREATEDB opt-in.

```powershell
$env:CORNER_TEST_DATABASE = '1'
$env:CORNER_TEST_CONCURRENCY = '1'
python -m unittest discover -s tests -p test_corner_assessment_concurrency.py -v
```

Tests cover explicit missing streams, rejection/reinstatement evidence, qualified-only
FKs, compatible basis/watermarks, corruption, snapshot reuse after market changes,
first-write/no-current-query guarantees, deadlines, deterministic races and atomic
rollback. No test or API in this slice mutates an episode or records a lifecycle application.
