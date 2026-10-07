# Public-evidence checkpoint — October 2, 2026

Current research scope: NBA full-game two-way moneyline; DraftKings Louisiana
target; Pinnacle and BetOnline required references. Novig is deferred, not rejected.
This research scope does not activate or modify a runtime channel generation.

## Completed review of currently retained material

| Candidate | Current result | Missing proof |
| --- | --- | --- |
| DraftKings v2 | insufficient_evidence | Exact Louisiana offering and effective rules binding; controlling tied late-interruption treatment; complete conditioning contract |
| Pinnacle | insufficient_evidence | Exact regional offering and effective rules binding; complete NBA interruption/completion-window treatment |
| BetOnline | insufficient_evidence | Real NBA quote plus a permitted, retained substantive governing rules bundle and product binding |
| Sportradar phase | insufficient_evidence | Entitlement/applicability, real transitions, and defensible positive-state verification freshness |

New, supplemental source-only reviews (original decisions are unchanged):

- [DraftKings v2](draftkings-la-nba-fullgame-conditional-v2/reviews/public-evidence-2026-10-02.json)
- [Pinnacle](pinnacle-nba-fullgame-conditional-v1/reviews/public-evidence-2026-10-02.json)

Each binds the prior review, retained source bytes, current research scope, and
the existing October 2 quote capture by SHA-256. Hash checks establish integrity
relative to retained records, not independent source authenticity or applicability.
The current corpus has been reviewed; the complete applicable evidence universe
has **not** been established. This is not a production approval artifact.

The existing capture contains DraftKings and Pinnacle NBA quotes, including
provider-reported offering IDs. They need not be recaptured merely to demonstrate
those books were returned. BetOnline was absent. Neither absence nor the user's
season/availability context proves why the provider omitted it.

## Findings that must not be promoted into approval

DraftKings' retained moneyline and basketball rules describe overtime and
exceptional settlement. They do not establish how the exact Louisiana offering
settles the unresolved tied late-interruption branch. The rejected v1 review
remains unchanged; v2 does not reinterpret it.

Pinnacle's fewer-than-43-minute void rule does not imply that every interruption
at or above 43 minutes receives a decisive settlement. The general completion
window, sport rules, and actual market overrides must be reconciled for the
applicable product.

The published DraftKings calendar-day and Pinnacle 12-hour non-start windows are
not interchangeable. If they govern the exact offerings without an applicable
override, that difference must be resolved under the conditioning-compatibility
policy, not rounded away. Current exact-offering applicability remains unproven.

## Next evidence, without outreach or quota polling

1. Reopen DraftKings/Pinnacle only for new retained official/public evidence
   closing the named product, revision, or settlement gaps. More rereading of the
   same corpus is not a prerequisite to moving on.
2. For Sportradar, use permitted documentation and real transition capture only
   once access exists. Samples cannot invent a latency guarantee; cache or receipt
   times do not by themselves prove freshly verified pregame state. No approved
   positive phase path currently exists.
3. Wait for an independent indication that relevant NBA markets are populated
   (for example, user-provided offering evidence). Do not spend API quota polling
   to discover that condition. No automatic monitor is configured by this plan.
4. Then make one deliberate, separately retained request for DraftKings,
   Pinnacle, and BetOnline, preserving raw response, request/receipt and HTTP
   metadata, source IDs and links, with no secret retained. A missing book remains
   missing; there is no automatic retry or replacement population.
5. Obtain BetOnline's applicable rules by a permitted official download/export
   or a provenance-backed user-supplied copy. Existing HTTP 403 bodies and reader
   previews are not the missing rules bundle; do not bypass access restrictions.

No emails or support requests will be sent. Existing correspondence and historical
reviews remain historical records; this instruction does not erase them.

## Decision and implementation gates

- **approved:** complete admissible evidence establishes the requested assertion
  and scope, followed by the required explicit approval review.
- **rejected:** evidence establishes incompatibility of the actual applicable
  product under the pinned policy.
- **insufficient_evidence:** a necessary link or branch remains unproven.

An unapproved candidate can be left unapproved; another candidate requires an
explicit scope revision and its own review. No silent substitution is permitted.
Settlement approval cannot substitute for independent phase approval.

No production loader, new grants, engine changes, or production-positive
authorization are introduced. After all required approvals exist, the separate
next step is one retained end-to-end proof in the isolated database. Successful
isolated proof still does not automatically enable production authorization.
