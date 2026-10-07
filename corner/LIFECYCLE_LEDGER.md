# Lifecycle persistence and replay — Migration 011

Implements Opportunity Decisions 4–7. This slice persists existing reducer semantics;
it does not schedule work, fan out activations, select current quotes, deliver alerts,
or accept user dismissals. The legacy pipeline and migrations 001–010 are unchanged.

## Authority and transaction ownership

`opportunity_conditions` is a stable canonical identity registry. The required key
is `(positive_ev, target_sportsbook_id, outcome_id, qualification_channel_id)`.
Generation, observation, price, evaluation and episode are not identity dimensions.
This single-target identity is not a commitment about future arbitrage/middle keys.

`lifecycle_applications` and `opportunity_transitions` are authoritative append-only
ledgers. Runtime mutation/TRUNCATE is prohibited, triggers provide defense in depth,
and all history FKs use RESTRICT. Neither ledger references a projection.

`condition_processing_projections` and `opportunities` are disposable. Closed episodes
are retained alongside the current open episode. Only an explicit rebuild replaces
that condition's complete projected episode set; ordinary commands update incrementally.

The caller supplies trusted authority, owns a READ COMMITTED transaction, and commits
or rolls back. Savepoints contain failed commands. Successful condition row locks
remain held until the caller ends the transaction. Do not batch locks in arbitrary
condition order across a long transaction. At stricter isolation levels retry the
whole transaction after serialization failures using the original command/key.

## Public API

```python
from corner.lifecycle_store import (
    ApplicationCommand, resolve_condition, apply_command,
    verify_history, rebuild_projections,
)

condition = resolve_condition(
    conn, sportsbook_id=book_id, outcome_id=outcome_id, channel_id=channel_id,
)
receipt = apply_command(
    conn, authority=trusted_authority, application_key=stable_issuer_key,
    command=ApplicationCommand(
        condition['id'], 'generation_activation', activation_id, generation_id,
        transition_at=explicit_processing_time,
    ),
)
conn.commit()
```

Kinds: `generation_activation`, `evaluation`, `qualification`, `assessment`.
Each carries exactly one typed source reference. Qualifications resolve the unique
already-persisted occurrence if qualified; no occurrence is synthesized for other
judgments. Assessments are persisted Migration 010 evidence, not a request to recapture.

Qualification/activation commands require a timezone-aware `transition_at`, retained
across retries. Assessment transition time comes from the assessment; evaluation
arrivals have no transition time. No database clock substitutes for business time.

The first application must explicitly reference a valid activation. A condition may
join an existing channel at an explicitly identified activation; no implicit lookup
of today's current generation establishes lifecycle state. Later changes honor the
activation predecessor and reset markers. Generation activation time governs the
new generation's evaluation cutoff; explicit application transition time governs
closure and must not precede prior transitions. Merely registering a condition
creates no processing projection.

## Retry, ordering, and outputs

Global `(authority_kind, authority_id, application_key)` uniqueness identifies one
intentional command. The canonical command includes its condition and generation.
Same key and same command returns the original receipt and its exact ordered output
IDs without reducer execution or testing today's state. Changed time, context,
condition or evidence conflicts. A new key with already-processed evidence appends
a new `already_reflected` receipt with zero outputs.

`application_sequence` is positive and continuous per condition across generations
and episodes. Under the condition row lock, allocation reads the journal head—not a
cached projection counter. Composite self-FKs bind predecessor ID, condition,
sequence and post-state digest to the next receipt's pre-state digest. Genesis has
neither predecessor field; subsequent predecessors are exactly sequence minus one.

Application outcomes are `applied`, `ignored`, `already_reflected`. Detailed reasons
preserve the pure reducer's vocabulary. Validation errors, incompatible serialization
formats, corruption and inconsistent authoritative judgments roll back without receipts.

Transition identity is `(application_id, output_ordinal)`. Ordinals are positive,
unique, and writer/verifier-checked contiguous. The result snapshot commits to every
ordered output, including its UUID, episode UUID, timestamps, generation and typed
evidence. A partial unique index permits exactly one opening per episode UUID.
Continuation/closure reuse that UUID. IDs allocated for an opening become authoritative
only upon commit, and replay never regenerates them.

An episode's generation remains its opening generation. On rollover, a closure
records the old episode generation and separately references the new activation.
Output ordering is application sequence then ordinal. Equal transition timestamps
are valid; decreasing timestamps fail the command.

## Incremental context, not projection authority

Normal processing verifies the immutable journal head and takes its execution
frontier as the source of markers. Projection rows are checked against that frontier;
missing or inconsistent projections require an explicit rebuild rather than being
silently accepted. Relevant earlier receipts are loaded for:

- the accepted assessment and incoming assessment identity;
- the threshold and open episode's qualified evidence;
- earlier evaluation/judgment receipts for the incoming evaluation;
- incoming generation/activation history and duplicate detection.

The context loader uses typed evidence joins and condition-scoped access indexes.
It does not replay the full journal or load every closed episode. The reducer's
transition helper updates the supplied current episode incrementally. The independent
`project_episodes()` full-history projector remains the oracle. Large conditions and
the combined context query still require EXPLAIN/production measurements; this is not
a throughput claim or a constant-time complexity guarantee.

`corner.lifecycle.frontier/1` hashes the processed generation/activation, cutoff,
watermark, threshold, accepted assessment, current open episode, last event and
immutable opening/last-transition IDs. It deliberately excludes historical tuples,
projection timestamps, application sequence and persistence metadata. Earlier command
history remains separately authoritative and linked by the journal; equal frontier
digests do not mean two histories are identical. This separation makes targeted
incremental loading and full replay produce byte-identical canonical receipts.

## Verification and rebuild

`verify_history` locks the condition, validates receipts/output rows, reloads retained
upstream evidence, replays commands in application order under the supported exact
reducer build, and compares complete canonical results (not only final projections).
It also compares incremental episode state to `project_episodes(all_events)`.

`rebuild_projections` performs the same verification first, then replaces both
projections in one transaction and verifies the result. It never queries today's
trusted quotes, appends a receipt/output, chooses new episode IDs, or skips invalid
history. Failure anywhere restores the pre-rebuild projections through rollback.

The versioned result contains typed dataclass snapshots through a closed decoder
registry, canonical Decimal strings and UTC timestamps. Source evidence and snapshots
are digest-checked; hashes are integrity checks, not signatures against a schema owner.
Keep exact source/runtime artifacts: only the current supported reducer/evaluation/
assessment formats and build revisions can be replayed by this implementation.

## Projection constraints

The processing projection structurally binds its application ID, condition, sequence
and digest to one receipt, and its processed activation to its actual new generation.
Its open-episode anchors are all-or-none. Episode identity/generation and constant
`opened` kind reference the claimed opening transition. Closure facts represent state;
there is no separately mutable status. One open episode per condition is enforced.
Remaining semantic cross-row relationships are verified in the adapter, not a second
SQL implementation of the state machine.

## Deployment and testing

Use a non-owner runtime role. Grant schema USAGE, required evidence SELECT, condition
SELECT/INSERT plus a narrow column UPDATE privilege needed for `SELECT FOR UPDATE`
(the identity trigger still rejects actual updates), ledger SELECT/INSERT, and
projection SELECT/INSERT/UPDATE. Give projection DELETE only to an explicit recovery
role or controlled recovery entry point. Never grant ledger UPDATE/DELETE/TRUNCATE,
trigger disabling, ownership, or migration-role membership. Authority must come from
authenticated execution context. Role provisioning remains deployment work.

Run the disposable PostgreSQL 18 tests (requires CREATEDB and configured credentials):

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:CORNER_TEST_DATABASE = '1'
$env:CORNER_TEST_CONCURRENCY = '1'
python -m unittest discover -s tests -p test_corner_lifecycle_store.py -v
```

The harness applies migrations 002–011 to a uniquely named disposable database,
rolls normal fixtures back, exercises committed concurrent writers, and drops only
that database during cleanup. Tests cover initialization, zero-output knowledge,
opening/continuation/closure/reopening, generation rollover, stale expiry races,
uncertainty, duplicates, exact retries, structural keys, rollback, projection
corruption, and full-replay equivalence. No live provider calls or API credits.
