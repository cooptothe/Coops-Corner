# November 20 deadline collection release

Owner objective: use all usable quota by November 20, 2026, ending midnight Central (`2026-11-21T06:00:00Z`). No post-deadline holdback. Actual provider-cycle end stays December 1, 00:00 UTC; this release does not reset or replace the monthly ledger.

## Forecast

Latest supplied usage: **755,877 used; 14,244,123 remaining**, November 4 at 20:00 UTC. There are 298 regular collection hours to the deadline: an initial **47,799.07 credits/hour**, about **860,383 per full day**. Runtime recomputes from the ledger, not from this frozen figure.

The refreshed 420-query ESPN schedule gives a maximum source-floor demand of **18,797,520 props credits** and **1,462,236 main credits** during regular 6amÃ¢â‚¬â€œmidnight collection through November 20. This assumes all markets and both bookmaker groups return chargeable data. It establishes sufficient modeled demand for the 15M objective, not a guarantee of real source coverage. Future tennis, overnight exceptions, live and additional markets provide further possible demand and remain globally governed.

## Runtime behavior

- Regular scope: 06:00Ã¢â‚¬â€œ24:00 America/Chicago. Overnight: configured soccer/tennis only, live or starting within two hours. Free discovery remains available overnight; paid empty pregame leagues are skipped.
- Initial allocation: main/live/additional 5.5M, props 9.5M; metadata/history idle allocations zero. Validated free inventory continues with zero metadata budget. An explicitly reconciled unexpected charge remains accounted.
- Weight the remaining days by the public schedule's source-floor demand, normalizing the partial first day. This allocates more budget to busy slates instead of saving it for quieter dates; missing schedule data falls back to equal-hour pacing.
- Recalculate once per minute and on inventory-scope changes. Learn actual-to-reserved charge ratios; prioritize the relative nearer-start bands. Shorten to source floors when spend is behind, lengthen distant bands when the slate exceeds the deadline rate.
- Source floors: standard pregame/props 60s; exchange pregame 20s; standard live 40s; exchange live 10s. These are minimum allowed target intervals, not throughput guarantees under arbitrary load.
- Main/props limits automatically transfer remaining capacity using observed eligible demand, including full pending reservations. Every split sums to 15M. Never change used credits, offsets, unknown charges, or actual cycle dates.
- Live no longer strands credits behind the old separate 3M/month or 150k/day subcaps. Live shares the same deadline controller, managed main limit and hard 15M global reservations.
- Additional markets retain the reviewed 30k/day admission cap. Exhausted, quarantined and cooling scopes do not inflate the adaptive demand calculation.
- Deployment requires 2 GiB free disk space; runtime refuses new paid requests below 1 GiB and reports `storage_low`, preserving room for accounting instead of failing after another purchase. No retention deletion is introduced.
- No catch-up purchases and no calls faster than source updates. No college props or Betfair props are added; no configured books removed.
- Stop purchases when the quota is consumed or the spending deadline passes. A final fully funded request settles correctly even if it uses the last credits.
- `source_capacity_limited` means the current eligible slate is already at source floors and cannot meet the spending target. It is a useful constraint signal, not a collection crash or permission to make wasteful calls. Unknown request/charge safeguards continue to pause uncertain accounting.

## Deployment

Stop worker and timers, reconcile while still on the old release, pull, then run `bash deploy/deploy-nov20-deadline.sh`. The script runs regression tests, verifies fresh provider usage without paid calls, migrates the existing policy, restarts the backend for overnight live queueing, renews the root-owned commit approval, and starts collection and timers. No frontend build or database replacement is needed. If old-release recovery refuses, stop before pulling and preserve its evidence.

After deployment run `python -m pipelines.collection_deadline_status`. It reports the target, source capacity, managed pool limits, fresh provider-reported remaining credits, and status age. This command is read-only and performs no provider requests.

## Sources and inputs

- https://the-odds-api.com/sports-odds-data/update-intervals.html
- https://the-odds-api.com/liveapi/guides/v4/
- `forecasts/november4-2026-events.json`, `november4-2026-sources.json`, `november4-2026-deadline.json`.
- Owner's six active keys, 42-event inventory and daily charge breakdown, November 4. This release supersedes earlier month-end holdback plans and cadence-only drafts.
