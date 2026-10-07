# EV v2: decisive-settlement conditional contract

This slice implements +EV Engine Decision #2 using parallel, version-aware
interfaces. **No migration or production authority is introduced.** The original
`ev.py`, `evaluations.py`, `qualifications.py`, `channels.py`, capture, worker and
work-ledger modules remain unchanged, including their source-derived identities.

## Meaning

V2 reports:

```json
{
  "calculation_basis": "decisive_settlement_conditional",
  "fair_probability_basis": "win_given_decisive_settlement",
  "conditional_fair_probability": "0.52",
  "conditional_ev_ratio": "0.17",
  "invalidation_probability_model": "none",
  "unconditional_ev_ratio": null
}
```

The numbers above illustrate the format. Probability and EV are full-precision
base-10 strings; non-evaluations retain the basis with null conditional metrics.

`conditional_EV = P(win | decisive settlement) * decimal_odds - 1`.

No probability of exceptional invalidation is estimated. No unconditional return
is produced. SQL `fair_probability` and `ev_ratio` retain their existing precision
as projections; consumers MUST resolve their basis using the snapshot version and
result contract. Cross-basis filtering/ranking/qualification is not valid merely
because these columns have the same names. There is no UI change in this slice.

V1 remains `corner.ev.snapshot/1` and engine `1.0.0`. The version-dispatch reader
labels its basis `legacy_v1_unspecified`, a diagnostic sentinel meaning **retain
the original v1 interpretation**, not an assertion that v1 was conditional or
unconditional. That sentinel is not written back into legacy snapshots.

## Pure v2 engine

`corner.ev_conditional` defines:

- `Configuration`: version, explicit basis/model, pricing settings, pinned
  settlement/admissibility policy;
- `SettlementPolicy`: identity plus complete canonical conditioning and
  invalidation descriptions, two-way decisive structure and absent push behavior;
- `SettlementEvidence`: exact book/market/outcome binding, assertion ID/digest,
  policy revision, decisive structure, push behavior and semantic rule descriptions;
- `EvaluationCommand`: immutable snapshot, configuration, settlement evidence and
  audit context;
- `evaluate`: conditional estimate or typed non-evaluation.

Configuration composes the unchanged v1 pricing settings and eligibility kernel.
The serialized v2 `pricing` object deliberately omits the legacy settlement label.
The input contract requires `decisive_two_way`; old `two_way_no_push` is not
implicitly reinterpreted. Legacy kernel labels exist only in the internal binary
calculation adapter and are not persisted as the v2 contract.

The v1 kernel supplies deterministic freshness/coverage selection and tentative
binary math. V2 releases that estimate only after every contributing book and the
target pass its settlement compatibility gate. A failed gate clears probability,
EV and contributing estimates; all supplied observations and settlement evidence
remain in the immutable command. Noncontributing books cannot influence consensus.

Required conditions for all contributing books:

```text
decisive_structure = two_way
push_behavior = absent
conditioning contract = pinned policy's contract
invalidation behavior = pinned policy's behavior
policy revision = pinned revision
```

Canonical JSON equality is deliberately strict. No fuzzy equivalence or latest
policy lookup occurs. Different invalidation criteria can change the conditioning
population, even if offered outcomes and prices match. Failure returns
`incompatible_decisive_settlement_conditions`; missing assertions return
`missing_decisive_settlement_evidence`. Malformed/wrong-subject evidence is an error.

These are **trusted-adapter inputs**, not proof of source approval. The reference
and digest identify the claimed immutable assertion; this module does not load or
authenticate an assertion ledger or authorize an operator. Tests use only synthetic
assertions. A production assertion-loader/approval path is still required.

## Version-dispatch APIs

Use `corner.analytics_versions` for new multi-version callers:

| Operation | API |
| --- | --- |
| Freeze/rebuild evaluation command | `serialize_command`, `deserialize_command` |
| Run pure version-pinned calculation | `evaluate_command` |
| Serialize analytical result | `serialize_result` |
| Read persisted full-precision result and basis | `decode_evaluation` |
| Persist evaluation and input links | `record_evaluation` |
| Apply basis-aware qualification | `qualify_evaluation`, `record_qualification` |
| Validate/serialize/register a generation | `GenerationConfiguration`, `generation_snapshot`, `register_generation` |

V1 command/configuration types delegate to the unchanged v1 implementations.
V2 uses `corner.ev.snapshot/2`, engine `2.0.0`, and an implementation digest that
pins the v2 source, adapter, reused pricing/serialization/qualification/channel
helpers and runtime. Unknown formats/builds fail; they never fall back to v1 or
today's current implementation. Future changes must retain supported artifacts or
explicitly reject unavailable revisions, not regenerate old meaning.

Evaluation persistence derives columns, result snapshots and observation links
from one command. It uses existing immutable tables, authority/key uniqueness,
savepoints, atomic inserts, retry comparison and concurrent determinism checks.
Caller owns commit/rollback under READ COMMITTED. Matching retries return original
IDs/timestamps; changed commands conflict; failed writes leave no partial header.

## Qualification

`ConditionalEVPolicy` requires
`expected_calculation_basis = decisive_settlement_conditional` and a positive
minimum conditional-EV ratio. `corner.qualification.snapshot/2` retains that basis,
full policy/build identity, exact evaluation result digest and full-precision EV.

Basis mismatch raises `BasisMismatch` (a qualification validation error). It is
not `not_qualified` or `not_qualifiable`. Even non-evaluable evaluations must have
the expected basis before they can produce `not_qualifiable`.

Comparison remains inclusive `>=` over the format-decoded full-precision result,
never the rounded SQL projection. V1 policies cannot qualify v2 results; conditional
policies cannot qualify v1 results. The old qualification API rejects unknown v2
snapshot formats rather than guessing their meaning.

## Channel generations

V2 registration requires a `GenerationConfiguration` containing:

- exact supported v2 engine implementation/configuration;
- exact conditional qualification implementation/policy;
- explicit settlement/admissibility policy, equal to the engine's pinned policy;
- the actionability policy to be used by a future compatible lifecycle adapter.

All three calculation/qualification/settlement bases must agree. An old qualifier
cannot be inherited into a new conditional generation. The complete tuple is
validated before any database write. Existing generation columns and JSON snapshots
express it using `corner.channel.configuration/2` and
`corner.channel.registration/2`; no DDL is necessary.

Registration alone does not activate a generation or grant lifecycle authority.
The existing orchestration and lifecycle adapters intentionally remain v1-only.
Do not activate v2 for them: their decoder/build checks reject unsupported v2
evidence rather than silently processing it. Their version-aware integration is
deferred alongside production capture; this slice is not an end-to-end v2 worker.

## Preservation and stopping point

- Existing frozen v1 WorkCommands still execute through their original adapter.
- No historical evaluation, policy, assertion or channel is rewritten.
- The DraftKings rejected v1 dossier remains untouched.
- No v2 source is approved; no assertion capture is wired.
- No polling, worker capture, assessment, activation or lifecycle changes.
- No database migration or automatic promotion.

## Verification

```powershell
$env:CORNER_TEST_DATABASE='1'
$env:CORNER_TEST_CONCURRENCY='1'
python -m unittest discover -s tests -p test_corner_conditional_ev.py -v
```

The tests cover v1 replay, v2 round trips, explicit/null result fields, full-precision
thresholds, both directions of basis mismatch, incompatible conditioning, generation
tuple validation, existing-schema persistence, rollback after header insertion,
real frozen v1 work execution, and concurrent/non-owner evaluation, qualification
and generation registration. Concurrent disagreement retains the winner and raises
a determinism failure. Synthetic evidence remains visibly separate from approval.
