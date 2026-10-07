# Retained settlement comparison — October 2, 2026

**Outcome: insufficient evidence. No production approval or scope change.**

Candidate: DraftKings Louisiana target; Pinnacle + Novig references; NBA full-game
two-way moneyline; decisive-settlement conditional EV. This is an offline
comparison of existing captures, not a current rules certification or legal advice.
No messages, API requests, new source captures or runtime changes were made for
this review. Provider emailing has been skipped at the user's direction.

## Main finding

Resolving Novig's Fair Value Settlement (FVS) alone would not establish this set's
compatibility. The retained DraftKings and Pinnacle documents also describe
different non-start windows. The current engine requires compatible conditioning,
not just overtime inclusion or a winner/loser pair in an ordinary completed game.

**This is a potential incompatibility in the retained candidate rules, not a
rejection of the actual consumed products.** Exact product mapping, applicable
revisions, and offering-specific overrides are still missing.

## Branch comparison

| Branch | DraftKings retained evidence | Pinnacle retained evidence | Novig retained evidence | Review consequence |
| --- | --- | --- | --- | --- |
| Ordinary completion / overtime | Two-way moneyline includes overtime; basketball has named exceptions [D1,D2,D3]. | Game period includes overtime [P1]. | Exact NBA contract absent from retained index [N3]. | Ordinary-game similarity is insufficient. |
| Game never starts on schedule | General two-calendar-day window; basketball postseason provision uses four calendar days [D1,D3]. | General 12-hour non-start window [P1]. | General help describes most postponements within 48 hours as active, subject to market-specific rules [N1]. | Different windows need explicit resolution, not normalization to a common TTL. |
| Started game interrupted | Basketball-specific windows anchored to the scheduled start date; early/late branches differ [D3]. | General 30-hour completion window with sport exceptions; NBA rule voids game-period bets below 43 completed minutes [P1]. | Suspended/abandoned contests appear among FVS triggers [N2]. | Do not infer one common decisive population. |
| Exactly 43 completed regulation minutes | In a 48-minute game, five remain: the early-interruption branch applies [D3]. | The below-43 void rule does not itself specify every outcome at or above 43 [P1]. | NBA-specific boundary unknown [N3]. | Failing one void predicate does not prove settlement is decisive. |
| Tied late interruption | Last-play-statistics provision interacts with general two-selection push wording; exact controlling result unresolved [D1,D2,D3]. | No-draw-offered draw is void in general rules; NBA interaction remains unresolved [P1]. | Generic help labels both push and void outcomes as fair-market-value settlements [N1]. | Labels cannot establish common economics or conditioning. |
| Non-decisive economics | Straight-bet push definition returns stake; exceptional branches still require scope/fee review [D1]. | Glossary describes void as refund [P1]. | Published FVS example has both a gain and a loss versus entry cost [N2]. | Non-zero FVS is not zero-return invalidation if it governs the quote. |
| Revisions and applicability | Retained Louisiana content, but no exact consumed-offering/effective-period binding. | Regional product and applicable revision unresolved. | Feed-to-product-to-NBA-contract chain incomplete. | No production settlement assertion for any book. |

## Two diagnostic scenarios (hypothetical, not observed incidents)

### A. Thirteen-hour delayed start

Consider an ordinary regular-season game scheduled at local 00:00, starting at
13:00 and completing normally later that same day. Assume the quoted markets are
governed by the retained texts, with no other cancellation, title override or
exception. Pinnacle's general non-start cutoff has passed; DraftKings' general
calendar-day cutoff has not. The DraftKings cutoff alone therefore does not void
this wager, whereas the Pinnacle clause calls for voiding it.

This is a **candidate conditioning counterexample**, not proof DraftKings must pay
a specific real wager. Obtain the exact offering hierarchy before concluding that
the real contracts differ. If the difference is confirmed, this v2 configuration
cannot treat the contracts as equal merely because the event later completes.

### B. Exactly 43 minutes completed, then no resumption

The superficially similar numbers do not establish equivalence. DraftKings'
five-minutes-remaining branch covers this boundary. Pinnacle's rule says what
happens below 43 minutes; it is not a complete affirmative settlement rule for
43 or more. Its general completion rule and sport/market overrides still matter.
Do not borrow Pinnacle's explicit American-football suspension rule for basketball.

## What this closes, and what it cannot close

- The documentary comparison is now explicit and digest-bound. Non-start windows,
  interruption boundaries and non-decisive economics are separate review items.
- Novig remains insufficient evidence / material compatibility concern. The live
  October 2 response contained no Novig quote and supplies no missing contract link.
- DraftKings' v1 rejection remains immutable. This comparison neither confirms an
  actual interrupted-game push nor retroactively changes its semantics.
- Pinnacle is not approved merely because its rules are more conventional than
  FVS. Its conditions must match the target's, not just be individually understood.
- Phase approval is independent and remains unresolved. No settlement comparison
  establishes freshly verified pregame status.

No further local reinterpretation can supply an absent product contract or a
provider's verification guarantee. The next useful input is a retained exact
offering/rules bundle, permitted provider clarification, or authorized live quote
with source identifiers. Emails remain skipped; no background polling is started.
An explicit reference-scope revision would require user direction and a new
review, not automatic substitution.

## Source locators and integrity

`evidence-index.json` binds seven original bodies and seven text derivatives by
SHA-256. Paths are relative to `source-approval/`. The complete prior manifests
remain beside the originals; text derivatives are navigation aids, not originals.
This is a declared limited corpus, **not** an assertion of evidence completeness.

- **D1:** DraftKings LA `dk_la_general_json`, capture `20260926T234325857765Z`;
  introduction hierarchy, Push definition, Settlement Rules, Event Cancellations
  and Interruptions. Derived text lines 41, 98–102, 124, 128–134.
- **D2:** Same capture, `dk_la_market_json`; 2-Way Moneyline Markets, lines 31–33.
- **D3:** Same capture, `dk_la_basketball_json`; Schedule and Format Changes,
  lines 16–33; overtime paragraph under General Basketball Settlement Rules.
- **P1:** Pinnacle `pinnacle_rules`, capture `20261001T214305078414Z`; General
  Rules lines 54–64 and hierarchy line 78; Basketball lines 246–251; Void glossary
  lines 787–788.
- **N1:** Novig `novig_settlement`, capture `20261001T214305855075Z`; voided trade,
  postponed event, push and sport-specific contract questions.
- **N2:** Same capture, `novig_fvs`; triggers, payout, worked example and finality.
  Its player-prop example is illustrative of the documented economics, not an
  NBA moneyline settlement incident.
- **N3:** Same capture, `novig_contracts`; Basketball index. Missing NBA entry is
  a limitation of this retained index, not proof no NBA product exists.

These findings depend on the retained revisions only. Current publication status,
offering applicability and approval are not proven by matching hashes.
