# Pure canonical EV engine v1

`corner.ev.evaluate_ev(snapshot, config)` is a pure function. It reads no database,
wall clock, environment, provider API, or global sportsbook list. It does not
persist results, create Opportunities, select historical alternatives, or size stakes.

## Input responsibilities

- The adapter supplies an immutable snapshot of already-selected trusted current
  quotes, an explicit timezone-aware evaluation time, and the target observation ID.
- Supply one canonical Market contract with its exact expected Outcome IDs and
  participant IDs. V1 requires moneyline, two distinct participants, no line points,
  and explicitly validated `two_way_no_push` settlement. Missing draw quotes do not
  establish this contract. NFL membership alone does not establish no-push rules.
- Supply `event_phase='pregame'` and phase evidence. Schedule time or the existing
  ingestion status default alone is not validated phase evidence.
- The evidence strings identify the validation source/rule for future adapters;
  this pure engine cannot independently authenticate those assertions.
- Duplicate observation IDs or multiple quotes for the same Outcome/sportsbook
  invalidate the snapshot. Quotes belonging to another market also invalidate it.

## Configuration

Configuration identifies canonical competition, market type, scope, reference-book
IDs, version, and the full calculation policy. References exclude the target book.
Minimum coverage defaults to two complete books and cannot be reduced below two
in this version. Book membership is configuration, not a property inferred from
its name or broad sportsbook category.

Target/reference age limits and maximum input skew are required parameters without
production defaults. Age and skew limits are inclusive. Skew is the oldest-to-newest
`observed_at` across the target and every included reference outcome. Excessive
global skew rejects the evaluation; the engine does not choose a convenient subset.

Provider timestamp policies apply to target and references:

| Policy | Missing timestamp | Present timestamp |
| --- | --- | --- |
| IGNORE | Accepted | Not used for eligibility |
| REQUIRE | Ineligible | Must satisfy explicit maximum age |
| MAX_AGE_IF_PRESENT | Accepted | Must satisfy explicit maximum age |

When checked, provider time after observation time is ineligible. No timestamp is
substituted for a missing provider update. Naive timestamps invalidate the snapshot.

Active finite Decimal prices greater than one are required. Eligibility checks run
on the supplied current selection; no fallback to an older active quote occurs.
Reference eligibility is all-or-nothing per book. Remaining complete books must
still meet the configured minimum.

## Results and arithmetic

Every `EVEvaluation` retains the full immutable snapshot/configuration, engine name
and version, and either a typed rejection reason or probability/EV estimate.
Reference exclusions identify the book, source observations, and reason. Successful
estimates record exact per-book observation sets and probabilities for both outcomes.

Proportional no-vig is performed independently within each reference book; target
probabilities are then averaged equally. EV is `fair_probability * target_odds - 1`.
Negative and zero EV are valid results, without any display qualification filter.

An isolated Decimal context uses explicitly configured precision (at least 28 digits)
and ROUND_HALF_EVEN. Arithmetic has finite-context rounding but no intermediate
storage-scale quantization. Ambient Decimal context does not control results.
Outputs remain Decimal ratios at calculation precision; persistence/display rounding
is a future boundary.

All initial engine tests use synthetic contract evidence and test-only thresholds.
They do not establish production reference coverage, freshness limits, or NFL
settlement rules. Production configuration, event/rules validation, and Opportunity
storage are separate follow-up work. Database snapshot
selection is now provided by `corner.ev_selection` as described below.

## Database snapshot selector

`select_ev_snapshot` accepts a canonical target Outcome ID, target Sportsbook ID,
explicit `evaluated_at`, immutable configuration, and a `MarketValidation` bound
to the canonical Event and Market. It returns either a `SnapshotSelection` holding
an engine snapshot or a typed assembly failure (unknown outcome, missing trusted
target, configuration mismatch, or validation mismatch).

One SQL statement reads the target's Market, all its canonical Outcomes, and the
relevant `trusted_current_quotes`. This keeps canonical relationships, disposition
eligibility, and quotes in the same PostgreSQL statement snapshot. No separate
target/reference reads are mixed. The selector neither commits nor writes data.

Only the exact target quote is selected from the target sportsbook; references
come from configured books excluding that sportsbook. All canonical outcomes
survive even when no book currently offers them, preserving three-way structure
and preventing missing-price data from creating a false two-way contract. Quotes
from other Markets or unconfigured books are not included. All Outcomes and their
points remain explicit; the selector does not interpolate or pair alternate lines.
V1's engine rejects unsupported multi-line/three-way contracts.

State, prices, timestamps, and missing reference sides are passed through to the
engine. No age, active-state, coverage, or provider-update filter is applied in SQL.
The engine returns insufficient coverage when references cannot qualify. A missing
trusted target is an assembly failure because there is no target observation to
evaluate. A trusted unavailable target still assembles and is rejected by the engine.

This selects **presently trusted state**. `evaluated_at` controls engine eligibility;
it does not rewind SQL visibility or exclude later-recorded dispositions. Passing
an old timestamp must never be interpreted as a historical backtest. Historical
knowledge-time selection remains a separate future interface. Callers should
capture/retain the returned snapshot and configuration for reproducibility.

`MarketValidation` is supplied by a trusted rules/phase adapter. The current schema
cannot prove settlement rules or reliable pregame status. The selector checks the
assertion's Event/Market identity but cannot independently verify its substantive
truth. Production rules/phase validation and freshness configuration remain open.

Example with an already validated context and existing connection:

```python
selection = select_ev_snapshot(
    conn,
    target_outcome_id=outcome_id,
    target_sportsbook_id=sportsbook_id,
    evaluated_at=evaluated_at,
    configuration=config,
    validation=validated_market,
)
if selection.snapshot is not None:
    evaluation = evaluate_ev(selection.snapshot, selection.configuration)
else:
    assembly_failure = selection.reason
```
