# Additional full-game markets

Included: alternate_spreads, alternate_totals, btts, draw_no_bet, team_totals.

All five appear in main Positive EV, arbitrage and promo conversion when the existing reference, fee and exact-contract checks pass. Alternate spreads/totals and team totals participate in cross-line middles. BTTS and Draw No Bet are binary contracts, not cross-line middles. A draw refunds Draw No Bet stakes: its probability and EV remain conditional on a decisive result. The feed states this explicitly. No draw probability is invented.

Team totals carry the provider's exact event-team description through normalization, binding, PostgreSQL and displayed selection names. Missing or unknown team descriptions fail closed. Opposite teams never share a contract or middle coordinate. Alternate and featured lines share a middle coordinate only for the same event and settlement family. Quarter/split lines remain excluded by the current catalog's integer/half-line validation.

## Collection and credits

Additional markets use the per-event odds endpoint, never the league featured endpoint. Local manual main refresh also retains at most three upcoming event responses per active sport key. Its ceiling is 36 credits/key (6 main + 3 x 10 additional). The review dialog displays the increased estimate and tennis expansion caveat. Raw responses and normalized capture bodies are retained separately; replay spends no credits and retries unfinished child ingestions.

The guarded live runner includes additional jobs only during the final 30 pregame minutes, during existing 08:00-midnight Central service hours. Standard group: 60 seconds; exchange group: 20 seconds. Both groups have <=10 reviewed books each. A durable Central-date admission cap allows 50 distinct games/day; a 30,000-credit/day subcap includes actual or reserved unknown charges. Requests remain inside the existing 8M main pool, 15M total and protected reserve. At all five markets returned in both groups this models <=930,000 additional credits per 31 days. Existing 18-key main baseline + this allowance is 7,358,160 credits. Higher main sport-key counts, prior spending and retries still consume the same hard pool; coverage stops at the cap.

These changes do not enable the worker, add a provider key or change funded activation evidence. Existing release-commit approval must be renewed before any future live activation. Backup already includes the entire ledger, so the additive admission tables are covered.

## Snapshot authority and performance

Additional scopes publish through the same retained outbox and idempotent PostgreSQL writer as main scopes. Reader authority recognizes both kinds, keeping standard and exchange groups separate, expiring stale scopes and removing withdrawals without legacy fallback. Local featured and additional captures do not invalidate each other solely because they came from different endpoints.

There are no provider requests in feed rendering. Immutable catalog and query caches remain in use. Middles are grouped by event/coordinate/team before calculation; the line-window cache is bounded at 8,192 entries. Existing pair-check limits remain in place rather than allowing an unbounded alternate-line computation.

## Verification

- Synthetic cases cover all five EV/arbitrage/promo paths, exact team isolation, cross-family alternate middles, missing references, authenticated quote serialization and draw refunds.
- Governor tests cover event/window limits, separate source groups, withdrawals/expiry and retained event-endpoint publication.
- Opt-in disposable PostgreSQL test ingests and replays 36 observations with the deployed writer privilege pattern, then reads/calculates through a role denied raw payload SELECT and odds INSERT. It creates/drops only its named temporary database and temporary roles.

Official market definitions and per-event requirement: https://the-odds-api.com/sports-odds-data/betting-markets.html
Billing: https://the-odds-api.com/liveapi/guides/v4/
Intervals: https://the-odds-api.com/sports-odds-data/update-intervals.html
