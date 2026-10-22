# Premium live main lines

## Access and UI

Pregame / Live switches are on Positive EV, Arbitrage, and Middles. No separate
Live page, no props/alternates, no Premium pricing or billing changes. The
authenticated account named `wonya` is the only Premium member. Account identity
is read from the signed session and account DB on every request. Query strings,
headers or client state cannot grant access. Other accounts receive 403 from
GET `/api/v1/live-stoppages`; anonymous requests receive 401. All responses are
no-store. The UI gate is only an additional presentation layer.

The compact, branded odds grid virtualizes rows, freezes event metadata, shows
American prices, flashes changes briefly, and supports market/league/availability
filters. Play means lines open; pause means no active lines in fresh captures.
Unknown means stale/missing data or a paused collector. No icon asserts that play
has stopped. Rendering and polling cannot establish executable liquidity.

## Scheduling, secrets and quota

The loopback-only, token-authenticated POST
`/api/v1/cron/refresh-live-odds` uses FastAPI BackgroundTasks to write a request
marker. A systemd timer invokes it every minute. Public/proxied requests and
requests with an Origin header are refused. Token is in a private configuration
file, never a URL/CLI argument, HTML or JavaScript. The browser only reads cached
results every 15 seconds. No cookie alone can trigger a paid live refresh.

The existing single worker and lease dispatch live jobs serially, through a
bounded HTTPX client. No second collector uses the shared key. Each league/group
requests h2h/spreads/totals for already-started events, using the existing 16 books
in two ten-book billing blocks. Maximum six credits per full league refresh.
No sub-minute polling, retries, overlapping workers or after-hours odds requests.
Inventory is the existing zero-credit event discovery; cached future starts
become live candidates without waiting for the next inventory poll.

Live sub-limits: **500,000 credits per bound quota cycle, 20,000 per Central day**.
These count actual charges OR held reservations, atomically. They are inside the
existing 7.9M main pool, not new allocations. Existing 15M total, 1.5M reserve,
metadata/props/history pools, calendar-cycle approval and uncertainty recovery
remain unchanged. Uncertain dispatches hold credits and use existing recovery.
Busy live coverage stops at its sub-limit; it does not borrow the reserve. This
guarantees a spending ceiling, not that every live game receives a minute refresh
on a busy slate. Main-pool exhaustion can also stop live collection.

Config `/srv/corner/config/live-odds.json`: enabled flag, fixed premium_username
`wonya`, random cron_token. No Odds API key is copied into the web/API environment.
Queue directory has a narrowly scoped API systemd write permission. Disable the
timer and set enabled=false to stop requesting live work; other collection keeps
its existing schedule. Previously captured quotes expire normally.

## Price and status correctness

Official docs: https://the-odds-api.com/liveapi/guides/v4/#get-odds
and https://the-odds-api.com/sports-odds-data/update-intervals.html

The Odds API notes that suspended/closed markets can retain non-advancing source
timestamps before removal. It does not supply a reliable stoppage reason here.
Scheduled start only infers in-play candidacy; a delayed game can be misclassified.
We do not invent timeout/halftime/VAR/clock or completed-state information.

Usable blocks require complete named outcomes, finite decimal prices >1,
compatible spread/total points, and market-level source age <=90 seconds. Locked,
duplicate, invalid, partial or stale blocks are excluded. No deprecated book-level
timestamp fallback. No-source-availability can set is_suspended=true only when
both book groups have fresh successful responses. A failed/stale group or paused
collector produces unknown (null), never a confirmed game stoppage.

Live data is stored in separate ledger tables. It does not overwrite pregame
snapshots, PostgreSQL prices, Lab history or CLV scopes. Successful empty responses
withdraw that group's old lines. Failed responses remain subject to conservative
quota reconciliation. Source timestamps are never re-dated.

Candidates reuse the existing weighted devig, cover and integer-score middle
calculators. Target prices are excluded from EV references. All required sides
and known target fee context are required. Compared books must have source times
within ten seconds. Quarter lines are excluded from two-outcome live EV/arb
matching, not silently treated as binary. Middles show payoff windows without a
fabricated probability or EV. All results are snapshot estimates, with game state,
settlement rules and execution availability explicitly unverified. A score change
between book updates can invalidate an apparent edge despite timestamp proximity.

The browser removes candidates at their source expiry and stops displaying them
after 20 seconds without a successful cached read. No 30-minute pregame retention
is applied to live opportunities.

## Deployment and evidence

Use `deploy/deploy-premium-live.sh` after a clean pull and stopping the collector
and recovery timer. It runs tests before stopping the web service, preserves the
previous production build, restores it on a failed build, configures private cron
access, renews the existing worker approval and checks anonymous rejection.

Offline tests cover authorization, public cron rejection, queued-only scheduling,
HTTPX timeouts/redaction, freshness/empty captures, cycle sub-limits, same-stream
settlement and UI virtualization. Synthetic fixtures exist only in tests/isolated
preview. They prove logic, not live provider coverage or industry certification.
The wonya authenticated journey and real live coverage must be checked after
deployment. No wallet transfer or payable checkout is enabled by this feature.
