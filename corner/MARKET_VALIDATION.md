# Market validation: pure admissibility proof

`corner.market_validation` implements independently versioned phase and settlement
policies, pure validators, immutable assertion values, and a separate EV-v1
capability/compatibility gate. It builds on the existing standalone validator
draft. There is **no production source approval, ledger, capture integration,
assessment automation, or polling** in this slice.

## Authority boundary

Provider fact != validation assertion != engine capability.

`RetainedEvidence` contains exact immutable bytes, their SHA-256, a source identity
and type, a retained-evidence UUID, receipt time, and locator. Policies and evidence
envelopes are supplied by trusted configuration/loaders, NOT arbitrary caller
claims. Hash verification proves byte integrity, not source authenticity. A caller
that can invent an approved authority or rewrite policy can invent a claim; these
pure functions do not authenticate source provenance.

The two supported evidence formats are **Corner contracts**, not Odds API response
schemas. No adapter currently establishes that an actual provider can produce
their required authoritative semantics. Raw Odds API JSON must not be relabeled
as explicit phase evidence. Unsupported formats are validation errors.

Positive tests use clearly synthetic authorities. They prove actual validator code
paths without approving any real feed or sportsbook. A real positive pregame path
and a reviewed real no-push rules path remain prerequisites for production wiring.

## Phase policy

`PhasePolicy` freezes its identity and source grants. Each grant names:

- authenticated source authority/type and provider identity;
- exact source-status-to-classification mapping;
- maximum source assertion age and maximum receipt age.

`EventBinding` supplies established canonical/provider event mappings. Evidence
must match them. The source contract supplies explicit status and source assertion
time; legacy status, future schedule, false completion and missing scores never
acquire positive authority automatically. A production grant must justify its
status semantics independently; merely approving a word like `scheduled` would
not establish that it represents positive current-state evidence.

Supported judgments: `supported_pregame`, `unsupported_live`,
`unsupported_completed`, `unknown`.

An admissible source expires at the earlier of source time + source age limit or
receipt time + receipt age limit. Equality is eligible; later is expired. An
assertion is usable no earlier than its assertion time and no later than its
earliest contributing deadline. Future receipt/source timestamps are errors;
this proof uses zero clock-skew tolerance, not an implicit production tolerance.

Unapproved sources, expired evidence and unmapped status values cannot establish
positive authority. Different classifications among currently admissible evidence
produce `unknown / conflicting_phase_evidence`, including positive vs unknown.
The validator does not select whichever source arrived last, implicitly supersede
old evidence, or authenticate completeness of a caller-supplied evidence set.
A future loader must define and retain the complete applicable evidence capture.

## Settlement policy

`SettlementPolicy` grants a particular retained rules-content hash authority for
one sportsbook + competition + market type + scope. A mutable URL is only a
locator, never the authority. A changed rules revision/content requires an
explicit new policy grant; unchanged URL or revision label does not suffice.

The retained structured rules configuration declares:

- rules revision and effective interval `[effective_from, effective_until)`;
- complete settlement selection labels, matched to canonical Outcome IDs;
- two-way / three-way / quarter-line structure;
- overtime, tie, push, refund and void semantics.

Refund/void identifiers must identify reviewed, immutable rule meanings in the
approved configuration. This module does not scrape prose or infer rule meanings.
Expected outcomes describe the contract, not the available sportsbook quotes.

Classifications: `no_push_two_way`, `three_way`, `push_capable`, `quarter_line`,
`unknown`. Two-way requires impossible tie and push for `no_push_two_way`; tie/push
refund produces `push_capable`. Both sides losing on a tie does not establish an
exhaustive binary outcome set and is `unknown`. Contradictory structural terms are
errors. This is intentionally a narrow vocabulary, not a general settlement model.

Rules applicability is evaluated at the requested assertion time (the proposed
wager/capture instant). Receipt time must already be known but does not supply a
phase-style TTL. Applicable conflicting approved terms produce unknown. Missing
authority or no effective rules produces unknown. Incompatible book/competition/
market/scope/outcome bindings are errors even when the source is unapproved.

## Assertions and verification

`ValidationAssertion` is an immutable in-memory value, not a registered database
record. The caller supplies assertion identity and time once. It preserves:

- canonical command snapshot: complete policy, subject, evidence bytes and source
  metadata, assertion time, format, validator version and implementation digest;
- canonical result snapshot: classification/reason, evidence diagnostics,
  validity bounds, exact subject, and settlement terms where established;
- command/result digests and `(assertion_id, result_sha256)` reference.

Collections with set semantics sort deterministically; timestamps use UTC with
microseconds; raw evidence bytes remain exact and are base64 encoded. No floats
enter the snapshot. JSON text prevents mutable nested dictionary/list state.

Reading `.result` or `.reference` verifies hashes, supported implementation/format,
and reproduces the assertion from its retained command. Unsupported historic builds
fail validation instead of silently executing today's different rules. A future
version registry can provide old decoders/implementations explicitly.

`unknown` is a successful judgment over insufficient admissible evidence. Digest
mismatch, malformed/unsupported formats, invalid bindings or inconsistent serialized
results are `ValidationError`, never unknown. Reproduction proves consistency only;
it does not substitute for trusted-source authentication or policy authorization.

## Capability is separate

`check_ev_v1_capability` consumes exact phase/settlement assertions, the contract,
the explicitly required target/contributing reference books, and capture time.
Every required book needs its own assertion. Wrong subjects or duplicate/unexpected
book assertions are errors; missing book assertions fail closed.

It requires supported pregame and compatible no-push two-way moneyline rules. A
valid three-way assertion stays three-way; EV v1 still does not support it. Equal
classification or shared Outcome identity is insufficient: settlement terms must
match across all required books. There is no fuzzy rules-equivalence inference.
The gate does not perform EV calculation, pick reference books, or grant lifecycle
authority. Engine configuration and input eligibility remain separate checks.

## Integration deliberately deferred

The existing `MarketValidation` callback, worker, evaluation formats, and database
schema are unchanged. Frozen evaluations do not yet reference this new assertion
format. No synthetic source is installed into production capture.

Before wiring capture, establish real source authority and retained fixtures, then
design durable assertion identity/references and a versioned capture format. Capture
must freeze exact assertion IDs/digests and verify their complete provenance. An
expired historical assertion remains valid historical evidence of its original
judgment, but cannot newly authorize current actionability. Retries must not refresh
assertions. Later source evidence requires a new capture/intent, not mutation.

## Verification

```powershell
python -m unittest discover -s tests -p test_corner_market_validation.py -v
```

Tests use synthetic retained content, not edits to raw provider fixtures. They
exercise positive paths, unknown/error separation, binding/integrity failures,
phase conflicts/expiry, effective rules revisions, three-way capability rejection,
per-book coverage/compatibility, deterministic serialization and immutable replay.
