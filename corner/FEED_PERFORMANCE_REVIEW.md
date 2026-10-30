# Feed performance and freshness review — 25 October 2026

## Implemented

- Tool feeds request only the quotes referenced by their own paginated rows. Schedule requests main lines only. There is no full-snapshot quote download before EV/arbitrage/middles can render.
- The first validated 250-row page can render before the remaining pages finish. A visible loading indicator distinguishes partial from complete results. Every page is bound to one snapshot; missing quotes and snapshot changes still fail explicitly.
- Shared browser requests are bounded, keyed by snapshot and devig method, and detached on navigation. They are cleared on account changes.
- Per-snapshot server calculations now use a bounded, reentrant single-flight cache. Concurrent requests cannot independently repeat the same sorted result or custom devig calculation. Errors are never cached as success.
- Live calculations cache six path/method results for two seconds. The visible live browser feed reads stored results every five seconds, avoids overlapping requests, and pauses reads in hidden tabs. These reads buy no odds.
- Due live jobs receive the first half of a normal four-job dispatch batch, ranked by overdue age. Remaining work retains persistent round-robin scheduling. This reduces queue delay without discarding pregame work.
- Mobile exposure badges use a short label in narrow EV columns with their full meaning retained for accessibility. Navigation uses the existing shared route list.

## Live intervals and budget

Source: https://the-odds-api.com/sports-odds-data/update-intervals.html
The provider documents 40-second in-play main-market updates and 10-second in-play exchange updates. Requesting faster would not guarantee newer source odds.

The worker recalculates a live plan at most every 15 seconds from the existing ledger and current event inventory. When funded, standard sportsbook requests reach 40 seconds and exchange requests reach 10 seconds. On busy slates, it first balances the two groups at a slower affordable interval; standard books then reach their 40-second floor before spare allowance accelerates exchanges toward 10 seconds. This is an adaptive target, not a guarantee of one fixed interval or end-to-end source freshness.

Planning counts overlapping games in the same league as one sport request window. Assumed game durations are 8h MMA, 5h tennis, 4.5h football/baseball and 3.5h other sports, plus a bounded allowance for old uncertain in-play candidates. These assumptions plan demand only; they never classify a game as finished, replace ESPN state, or remove a live scope.

| Allocation | Monthly credits |
| --- | ---: |
| Main + additional + live, shared | 7,900,000 |
| Player props | 5,000,000 |
| Metadata | 500,000 |
| History | 100,000 |
| Protected reserve | 1,500,000 |
| Total subscription | 15,000,000 |

Live keeps its existing 500,000/month and 20,000/day subcaps **inside** main. The paced daily allowance also spreads remaining live credits across remaining cycle days, and respects remaining shared-main/global headroom. Reserved or uncertain charges count until reconciled. Pool limits, reserve, cooldowns, quarantine, and provider billing evidence remain authoritative. No next-cycle activation is added.

The saved November schedule envelope in ALL_BOOKS_FORECAST.json remains 13,414,836 planned credits / 1,585,164 remaining. It counts the shared main cap once, including live. It is not a fresh October usage forecast or a promise that every independent main/alternate/live maximum can run simultaneously. Last owner-confirmed usage was 507,587; this review makes no new provider calls and cannot treat that old number as current. Read the deployment status output for actual ledger usage and selected intervals.

Pregame countdowns remain unchanged because this change has no measured new credit allocation to fund faster paid requests:

| Time to start | Main | Props | Additional |
| --- | --- | --- | --- |
| >12h | 15m | 10m | Off |
| 6–12h | 10m | 5m | Off |
| 4–6h | 5m | 3m | Off |
| 2–4h | 5m | 2m | Off |
| 1–2h | 3m | 1m | 10m |
| 30–60m | 2m | 1m | 5m |
| 15–30m | 2m | 1m | 2m |
| Final 15m | 2m | 1m | 1m |

Collection still uses the existing 08:00–00:00 America/Chicago window. NCAA props remain excluded. Live remains main lines only and server-restricted to wonya. Source timestamps and 90-second live quote expiry remain unchanged; faster polling never re-dates an old quote.

## Validation and release limits

Regression checks cover budget exhaustion, provider floors, cadence fences, live priority with pregame progress, single-flight concurrent calculations, per-method cache expiry, first-page delivery, cancellation, snapshot consistency, auth/premium access and existing market calculations. Frontend type checking and production build are required before release.

Browser checks use synthetic data and an isolated localhost preview. Reviewed mobile pages at 390px include EV, props, arbitrage, middles, schedule, promo, Lab, tracker, account and help. Feed/filter controls and compact props exposure badges were visually checked. Lab research data is unavailable in that minimal preview API; this is not evidence of a production Lab failure or proof of its historical-data coverage. Scrollable navigation is intentional. This is not an exhaustive device/accessibility certification.

This update is ready for deployment validation, not a claim of proven mass-user capacity. Before a broad release, measure authenticated production cold/warm feed latency, p95 latency under realistic concurrent sessions, API/DB memory and CPU, quote ages by book/group, and collection errors through a full busy slate. Do not infer capacity from the login route being healthy. The deployment helper checks service readiness, builds with a previous-web rollback, renews existing collector authorization through the standard repair path and prints read-only live cadence/coverage evidence.


## October 30: history-size bottlenecks

- Props mounts independently of the main capabilities/catalog endpoint. An
  unrelated main-catalog rebuild or error cannot block the props page.
- Successful outbox acknowledgements atomically increment a one-row SQLite
  publication revision. Scheduled main reads use it to invalidate their source
  cache instead of counting the entire PostgreSQL observation history. Legacy
  workers fall back to the prior fingerprint. Existing source-age cutoffs and
  the forced source refresh limit still apply. Supported publication must use
  the coordinated worker; manual database corrections require catalog reload.
- Offline partial outbox and closing-line lookup indexes retain all records.
  Install while collection is stopped with pipelines.feed_indexes. The first
  index build can take several minutes on a 32 GB ledger. Do not interrupt it
  merely because no intermediate progress appears.
- Props pricing keeps two exact-input cache entries with a shared computation
  lock. Every request first reloads and prunes current scopes, then hashes the
  complete input and margin option. Changes, withdrawal and expiry invalidate
  reuse; callers receive independent result copies.
- Local synthetic benchmark: 80,000 outbox rows, one pending lookup median over
  twelve calls, 89.2791 ms before index / 0.0554 ms after. This is one SQLite
  query on the development host, not VPS throughput or end-to-end page latency.
- Run pipelines.feed_profile --catalog after deployment for actual retained
  props cold/warm and catalog cold/reload timings. It makes no provider calls.

128 relevant backend checks, 260 frontend tests and the production build pass.
Real concurrent-user load and VPS latency remain to be measured. Storage
retention and guarded backups are still required to prevent disk exhaustion.


## Production memory follow-up

The October 30 deployment completed and verified live collection, but its final
optional Lab diagnostic was killed by the OS. That diagnostic unnecessarily
rebuilt the entire retained research catalog. It now performs SQL-only saved
row counts, with a bounded nonfatal deployment timeout. Saved research decoding
and raw prop-scope decoding stream one row at a time. Snapshot hashing preserves
the identical canonical digest while encoding only one record at a time.
The full-catalog profiler refuses to allocate a second production catalog beside
a running API; use its default props timings online and --catalog only offline.
Kernel OOM evidence and actual process RSS still need production verification;
systemd MemoryCurrent includes more than the Python heap.
83 relevant backend regressions pass for these changes.
