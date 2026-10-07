# Real-transition investigation plan — not executed

This is a specification for later bounded research capture, not a collector or
production polling configuration. Access, permitted retention, rate budget, event
selection and source-verification semantics must first be confirmed. No live
game response has been captured in this dossier.

## Acquisition and completeness

Predeclare several exact NBA game IDs, season types, coverage levels, canonical
Event mappings, endpoints, access tier, observation windows, request limits and
stop conditions. Retain the mapping rationale and source identifiers; team names
and approximate tip time alone must not resolve ambiguous matches. Do not set an
approval sample size or freshness TTL from an arbitrary number of successful games.

For every planned request, retain success or failure, skipped request reason,
rate-limit response and coverage gap. Store exact response entity bytes and
SHA-256, sanitized endpoint/version/parameters, request start/receipt UTC times,
monotonic duration and clock-health evidence. Record HTTP status and available
Date, Age, ETag, Last-Modified, Cache-Control, Expires, Retry-After, Content-Type,
Content-Encoding and request/correlation identifiers after secret review.
Absent metadata stays absent; never fabricate a source assertion time from receipt.
Authentication headers/query secrets and cookies must not enter shared artifacts.

Preserve provider status, game/league/team IDs, coverage, scheduled time and all
source timestamp fields with their documented meanings. Original bytes remain
distinct from extracted/normalized records. Documentation examples, simulations
and replays must be labeled as such and never counted as live observations.

The inventory must enumerate all attempts, retained records, missing expected
records, conflicts and exclusions with reasons. Use immutable manifests and digest
references. A later capture gets a new identity; no favorable-subset selection.

## Timing interpretation

For each transition, retain the last observed pregame response and first observed
live response, including missing responses between them. This brackets what our
client observed; it does not establish actual jump-ball time or a maximum provider
delay. Any comparison with actual play needs independently retained, synchronized
reference evidence and its uncertainty. Broadcast timing alone is not ground truth.

Assess separately: source verification age, response/cache age, receipt age,
collection interval and clock uncertainty. An HTTP 304, unchanged ETag, fresh
Date or push heartbeat is not positive re-verification unless the approved source
contract explicitly makes it so. No observed sample maximum becomes a guaranteed TTL.

## Adverse-case inventory

For every item record `observed`, `provider_documented`, `not_observed`, or
`unresolved`, with source/digest references. Failure injection is synthetic testing,
not a real provider outage. Never induce an outage or exceed agreed request limits.

- Normal scheduled/created-to-live progression; skipped intermediate states.
- Delayed start versus a delay after play began; do not authorize from delayed alone.
- Postponed/replacement IDs; ambiguous remapping is not automatic continuity.
- Schedule/game endpoint disagreement and apparent status regression.
- Identical old body served with a new receipt time or HTTP Date.
- Collection outage, partial coverage, failover, rate limiting and transport loss.
- Pregame status persisting after independently evidenced play; preserve it even
  if it prevents approval. Where actual play is unknown, state that limitation.
- Preseason/extended-boxscore differences; no extrapolation to other season types.

## Review and eventual end-to-end gate

Review access/applicability, complete inventory, provider answers and all adverse
evidence together. Missing defensible fresh verification yields insufficient
evidence, not supported pregame. Missing source content/digest integrity yields a
validation failure. Neither authorizes preparation.

Any future approved revision must independently establish phase authority; it
does not approve DraftKings/Pinnacle/Novig settlement or book availability. Later
integration needs the fixed real odds scope, all three settlement approvals and
the separately approved production loader. The eventual proof retains source and
approval digests, assertions, evaluation and fresh assessment preparations,
evaluation/qualification/occurrence/assessment identities, lifecycle receipt,
opening transition and reproducibly rebuilt episode. Historical evaluation
authorization must not substitute for fresh assessment authorization.
