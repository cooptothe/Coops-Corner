# Beta scheduled collection - control plane and manual-fetch removal

Prepared October 16, 2026 against commit 2c0c6c7. No paid provider calls.

## This release

- With CORNER_PRIVATE_BETA=1, both manual paid-fetch entry points return 403
  scheduled_only before capture/ingestion. Applies to operator and members alike.
- Status responses explicitly disable the main and props fetch controls. The UI
  hides the paid main refresh/leagues controls and props fetch configuration.
  Filters still control which retained bets a member sees. Missing policy fails
  closed in the UI. Legacy non-beta development retains its existing behavior.
- Empty-state guidance no longer directs users to removed paid-fetch controls.
  Cached page reload, retry and parlay quote review remain reads of retained data;
  they do not contact the provider or cause paid work.
- New isolated offline worker exercises policy, reservations and snapshots. It has
  no HTTP client/live mode and never publishes simulated data into member feeds.

## Collection policy

America/Chicago standard window: 08:00 inclusive to midnight exclusive. After
Hours / After Market: midnight to 08:00, no new collection. UTC persistence and
timezone-aware comparisons; DST transition tests included. No catch-up replay.

Main lines: 60 seconds standard, 20 seconds proposed exchange group. Props:
24h-6h hourly, 6h-2h every 15m, 2h-15m every 5m, final 15m 60s/20s.
No started events. Props horizon 24 hours. All 18 configured selections supported,
with ATP/WTA requiring actual expanded tournament keys. Every family market is
requested for each eligible event, with no 20-event cap. Missing source coverage
is not synthesized. Proposed exchange classifications still need live verification.

Standard main (6): draftkings, fanduel, espnbet, betmgm, betrivers, pinnacle.
Proposed exchange (6): novig, betfair_ex_uk, prophetx, kalshi, betopenly, polymarket.
Props standard adds prizepicks and underdog (8). BetOnline stays excluded.

## Accounting and persistence

Budget pools remain 8M main + 5M props + 0.5M metadata + 1.5M protected = 15M.
The provider billing cycle must be configured explicitly, not reset on the first
calendar day. Overlapping periods and changing existing cycle bounds are refused.
SQLite BEGIN IMMEDIATE reserves estimated market/book-group cost before dispatch.
Actual x-requests-last charges reconcile the reservation, including zero. Missing
charge headers/timeouts/crashes keep conservative reservations and block the job;
no automatic uncertain-request retry. Overcharges, exhausted provider reserve,
missing remaining header or HTTP error pause further work for operator review.

A durable worker lease and per-job cadence survive restarts. A stale lease holder
cannot publish a late result. This does not claim an external HTTP exactly-once
guarantee: provider/network idempotency and live transport deadlines remain gates.
Graceful one-shot exit releases the lease while retaining next-due state.

Successful snapshots replace only the exact requested book/market/event scope.
Groups do not re-date each other. Provider timestamps are retained. Actionable
snapshot limits currently 180s standard / 60s exchange, capped at event start.
Those are candidate freshness policies needing live timestamp/skew validation.
Distant coarse captures therefore may have gaps in actionable availability.

## Offline rehearsal on the VPS after code verification

Keep existing private-beta flag, empty API key and zero manual cap. Do not change
public firewall rules. Tests and rehearsal need no new purchases or secrets.

    cd /srv/corner/app
    .venv-api/bin/python -m unittest tests.test_collection_worker tests.test_scheduled_only tests.test_refresh_service tests.test_props_refresh tests.test_beta_access tests.test_accounts
    .venv-api/bin/python -m pipelines.collection_worker --manifest fixtures/collection/simulation.json --state /srv/corner/config/collection-simulation.sqlite3 --now 2026-10-16T15:00:00Z

The example is a fixed historical simulation time, not the current collection
clock. First run: 40 simulated jobs, 108 simulated main units and 48 props units.
Repeat at the same time: zero new jobs and unchanged accounting. All runs report
mode=simulation, provider_calls=0, feed_publication=false. The fake tournament IDs,
events and quota headers are deliberately labeled. Never use this ledger as real
provider-usage evidence. Use a separate simulation file for a fresh rehearsal.

## Verification completed locally

95 backend tests passed (scheduler, manual-fetch denial, main/props regressions,
beta access and accounts). 141 frontend tests passed. TypeScript passed.
Concurrent connections verify one reservation; expired lease tests preserve
uncertain costs; billing-window, DST, cadence changes, split-group merging,
staleness and restart tests pass. Two CLI runs execute 40 then 0 simulated jobs.
Existing tests emit a Starlette httpx deprecation warning and some unclosed-test-
connection ResourceWarnings; no test failed. These warnings are not production
load or leak verification. VPS production build/browser checks remain pending.

## Still required before automatic live collection

1. Controlled sport/event discovery and persistent inventory, including rotating
   tennis tournaments; start/reschedule/cancellation updates without omissions.
2. Live provider transport through the same governor; startup quota/billing-cycle
   reconciliation, deadlines, backoff/rate limiting and authorized credentials.
3. Scope-safe adapters publishing retained main odds into PostgreSQL and props
   into a shared transactional store. Do not reuse legacy replace_scope for one
   scheduled event: it can remove other games. No second JSON writer.
4. Automatic browser snapshot/version reads, per-source age/skew checks, source
   fee/calculation verification, honest last-success/next-due/After Hours states.
5. Guarded operator status/pause/reconciliation tools, supervised worker, alerting
   and new backup coverage. Worker ownership is not a member cookie.
6. Recorded integration, crash/recovery, actual slate/credit forecasts and bounded
   real provider smoke on/after October 19. No live API purchase before then.

This is not a completed live scheduler. Removing manual fetch does not make the
empty staging feeds collect real odds. Do not expose paid member access based on
the offline rehearsal alone. Scheduled backups, payment/receipt lifecycle, HTTPS,
load and final launch gates also remain open in the release plan.
