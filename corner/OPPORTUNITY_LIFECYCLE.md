# Opportunity lifecycle: pure state-machine proof

Migration 011 now persists this model through `corner/lifecycle_store.py`; see
`LIFECYCLE_LEDGER.md`. The transition helper updates episode state incrementally,
while `project_episodes()` remains the independent full-history reconstruction
oracle. The original prototype and synthetic tests below still define its behavior.

`corner/lifecycle.py` implements Opportunity Decisions 1 and 2 in memory. It adds
no tables, migrations, queries, scheduling, alert delivery, or changes to the legacy
pipeline. Tests use synthetic identities, observations and explicitly supplied times.
This is a behavioral proof, not a production opportunity service.

## Boundaries and vocabulary

- Evaluation: immutable analytical fact with its exact target and **contributing**
  references. Excluded reference inputs remain in EngineEvaluationInput; they do
  not become contributing evidence just because the engine inspected them.
- Qualification: immutable threshold judgment. This module neither calculates EV
  nor reexecutes the qualifier. A future adapter must verify the actual ledger rows,
  digests, policy compatibility and contributing evidence before constructing facts.
- Occurrence: only an ID and a qualified-decision ID. It does not claim present
  availability. One qualification has at most one occurrence, with no copied input
  relationships. A retry returns the existing occurrence even if it proposes a
  different new record ID. Different qualification decisions may have occurrences
  for the same evaluation without duplicating episode transitions.
- Assessment: current actionability judgment over exact evidence, policy, channel
  generation, evaluation watermark, prior assessment, and phase evidence.
- Episode: reconstructible projection of opened/continued/closed lifecycle events.
  Closure followed by a valid new opening uses a new episode ID. Member dismissal
  and alert delivery are outside this aggregate.

The condition is `(positive_ev, target_sportsbook_id, outcome_id,
qualification_channel)`. Event and Market are not duplicate condition-key fields.
A different line means a different canonical Outcome and a different aggregate.
Price changes alone need not change episode identity, provided a new qualified
evaluation and aligned assessment continue the still-open episode.

## Frozen channel generations

Each generation specifies one engine implementation, immutable engine configuration
identity, authoritative qualification implementation/configuration identity, and
actionability policy including explicit age limits. Version labels alone are not
configuration identity; the adapter should supply retained configuration digests or
equivalent immutable identities. Test build names/digests are deliberately synthetic.

Generation rollover requires the expected current generation. It closes an open
episode with `channel_configuration_changed`, resets current markers, preserves
history, and requires an evaluation made at or after activation of the new generation.
Reusing/reactivating a generation ID is rejected. A late rollover command whose
expected generation is no longer current is recorded but does not change state.

## Pure API

All dataclasses are frozen; collections become tuples. Reducers return a new state
and never mutate their input. IDs and timezone-aware timestamps are supplied by the
caller; this module does not allocate production IDs or consult the wall clock.

```python
state = initial_state(condition, generation)

# Optional independent arrival: advances knowledge before qualification finishes.
state = process_evaluation(state, EvaluationArrival(generation.id, evaluation))

# Contains the persisted qualification and its immutable evaluation fact.
state = process_judgment(state, judgment_command)

# Contains the exact trusted quotes, phase evidence and expected state binding.
state = process_assessment(state, assessment_request)

assert state.episodes == project_episodes(state.events)
```

Evaluation and qualification may also arrive together via `process_judgment`.
Qualified detection is retained even when it is too old or incompatible to drive
the current episode. Nothing automatically opens merely because it was qualified.
Unknown generation assessments are rejected; an assessment cannot silently pick a
policy. No independently supplied `actionable=True` is accepted: the reducer derives
the assessment using the generation's frozen policy.

## Two evaluation markers

`watermark` orders applicable analytical knowledge by `(evaluated_at, evaluation_id)`.
IDs only break timestamp ties; insertion/qualification/delivery times never order
market evidence. `latest_threshold_qualification_id` retains the newest applicable
evaluable qualification accepted by the reducer.

An independent evaluation advances the watermark before its qualification arrives.
The subsequent matching qualification can still apply at that watermark. Equivalent
additional decisions for that evaluation do not trigger another transition.
Contradictory decisions under the same generation and policy/configuration identity
raise a consistency error, including when the evaluation is historical.

A not-evaluable evaluation advances the watermark without changing threshold state
or closing an episode. A new episode can open only from a qualified judgment **at
the watermark**. An existing episode may instead assess its earlier evidence during
an uncertainty/pending-qualification gap. That survival assessment cannot extend the
underlying observation freshness deadlines. A closed episode cannot use that old
qualification to reopen after a newer evaluation has advanced the watermark.

Older evaluations and qualifications remain historical. In particular, a late
negative evaluation behind a newer not-evaluable watermark cannot rewind threshold
state or close an episode. No engine non-evaluation reason is interpreted as a
lifecycle closure rule.

## Actionability and applicability

`AssessmentRequest` binds to:

- Channel generation, assessment ID and `assessed_at`.
- The processed evaluation watermark and exact qualified decision being assessed.
- `basis_assessment_id`: the last applied assessment when this request was prepared.
- Exact current trusted target/contributing-reference observations.
- Event-bound phase evidence.
- A proposed episode ID when opening is possible.

The adapter must supply a coherent current trusted snapshot and validated phase
evidence. The model cannot prove that arbitrary caller data actually came from
`trusted_current_quotes`; database selection/atomic persistence are future work.
There is no historical-as-of query implied by a request's timestamp.

The assessment retains the evaluated evidence through its qualification fact, the
current supplied observations, policy identity/limits, target deadline, each reference
deadline, and every failed rule. Same observation ID with changed immutable contents
is a consistency error, not an ordinary price change.

For v1, exact observation matching is required. Even a new poll with identical
prices invalidates the previous analytical evidence until reevaluated. No equivalence
or interpolation is inferred. A missing trusted stream is evidence mismatch, not
proof that the provider declared it unavailable.

Deadlines use observation time plus the explicitly supplied maximum age. Equality
at a deadline remains eligible (`age <= maximum`); expiry applies strictly after it.
No arbitrary production freshness defaults are introduced. Provider-update-age
policy remains part of engine eligibility; this prototype does not invent an
additional provider-time actionability rule.

All failures are retained. If multiple failures close an episode, the deterministic
primary reason uses this priority: unsupported phase, target unavailable/suspended,
target stale, reference evidence stale, analytical evidence changed. This is reporting
precedence, not suppression of the other assessment reasons.

Assessments order by `(assessed_at, assessment_id)`, independently of evaluations.
To apply, their generation, watermark, qualified-evidence binding and prior-assessment
binding must still match. A later timestamp cannot rescue an obsolete binding.
Historical/inapplicable assessments are retained with an explicit no-op disposition.

## Transitions and timers

| Evidence | Effect |
| --- | --- |
| Current qualified judgment + aligned actionable assessment, no episode | Open |
| New qualified judgment + aligned actionable assessment, open episode | Continue |
| New applicable not-qualified judgment | Close: qualification_lost |
| Current target suspended/unavailable | Close: target_unavailable |
| Evaluated target past its deadline | Close: target_stale |
| Contributing reference past its deadline | Close: analytical_evidence_stale |
| Trusted evidence no longer matches evaluated observations | Close: analytical_evidence_changed |
| Phase no longer supported pregame | Close: unsupported_phase |
| Generation rollover | Close: channel_configuration_changed |
| Not-evaluable result alone | No episode transition |
| Late/obsolete input | Retain history; no rewind |

Repeated actionable assessments of the same occurrence update assessment authority
without producing redundant `continued` events. Lifecycle events retain sequence,
episode/generation, policy identity, transition time, reason, triggering evidence
identity and occurrence when relevant. Episode projection is rebuilt from these
events; the full aggregate additionally needs evaluation, judgment, assessment and
generation histories to reconstruct watermarks and applicability.

No transitions happen spontaneously when time passes. A future scheduler must submit
an assessment/expiry check using the applicable evidence and watermark. A saved timer
bound to an old assessment is a historical no-op after a refresh—even when the new
assessment used the same evaluation watermark. Advancing the watermark likewise
invalidates old timers; orchestration must reassess/reschedule rather than leave an
expired episode indefinitely open. The pure model does not implement that scheduler.

Transition times describe lifecycle application, not market chronology. Applied
transition times cannot go backwards. Judgment redelivery time is not command
identity; assessment times and generation-command times are explicit immutable inputs.

## Proof and deliberate limits

```powershell
python -m unittest discover -s tests -p test_corner_lifecycle.py -v
```

Tests prove delayed arrivals, independent evaluation/qualification arrival, both
ordering tie-breakers, old expiry races, same-watermark refresh binding, exact-price
and reference identity changes, uncertainty gaps, separate freshness deadlines,
generation rollover, duplicates/conflicts, close/reopen and projection replay.

This serialized, single-condition in-memory reducer does **not** prove concurrent
lifecycle persistence. Independent channel/occurrence and assessment persistence now
have their own contracts in `CHANNEL_LEDGER.md` and `ASSESSMENT_LEDGER.md`. Condition
transaction/CAS strategy, application/transition journals and projections now have
their own Migration 011 contract and tests. Scheduling and runtime-role provisioning
remain later work. Tuple histories and local event sequences
are testing tools, not decisions about the physical PostgreSQL schema or UUID strategy.
