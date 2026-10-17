# Player props Trends

Trends is a separate research workflow. It does not overwrite the market-reference
fair probability, enable odds collection, place bets or unlock unresolved fees.
The props page has a Trends panel and a per-row Trends button. It can research
retained one-sided quotes even when the market-consensus feed cannot price them.

## Data and coverage

The adapter uses ESPN's public search, game-log and player overview/news responses.
No API key or paid odds credits are used. Public access is not a guaranteed API
contract or a grant of commercial redistribution rights; verify applicable usage
terms before relying on it commercially. Full articles are not scraped or copied:
only short linked headlines and publication/update timestamps are displayed.

Initial leagues: NBA, WNBA, NFL, NHL and MLB, for supported over/under statistics.
Missing statistics, unsupported leagues, ambiguous players, team mismatches and
unresolved fees remain unavailable. Soccer, college, first-score and yes-only
markets are not silently mapped to an unrelated statistic. Athlete identity needs
an exact normalized name, league and sport, plus a matching current event team.

Regular-season games only; at most two seasons, a 366-day lookback and 40 usable
games. Last 1/5/10 are descriptive windows, not independent evidence. The baseline
uses up to 30. Show every window's actual denominator, decisive hit count, pushes,
mean and median. Historical results are re-evaluated at the current line, not the
historical line that was offered. DNPs and unknown stats never become invented
zeros. Explicit DNP/nonparticipation and zero-minute basketball games are excluded;
the source does not prove every sportsbook's starting/participation rules.

Opponent and home/away samples are separate descriptive splits. They are not
multiplied into probabilities. Minutes/ice time/attempts/at-bats are labeled
workload proxies where available, not a universal usage or snap-share metric.
No unsupported opponent defensive rating, lineup projection or injury multiplier
is invented. Different teams/seasons and changed workload need review.

## Statistical design

For wins `w`, losses `l` and pushes `u` at the exact current line:

- Decisive historical hit rate: `w/(w+l)`; pushes shown separately.
- Provisional Jeffreys-smoothed estimate: `(w+0.5)/(w+l+1)`.
- Net decimal return for supported win commission `c`: `1+(d-1)*(1-c)`.
- Research EV: `(w+l)/(w+l+u) * (p * net_return - 1)`. The decisive fraction is
  empirical; no unconditional future push mass is claimed to be calibrated.
- Historical sampling sensitivity uses a 95% Wilson interval on decisive results.
  It is not a future-game confidence guarantee: stationarity and independence
  assumptions may fail and searching many props creates selection bias.

A **research candidate** needs at least 20 decisive games, positive EV even at the
historical Wilson lower endpoint, a completed game within 30 days, no detected
team change, no >=20% recent workload shift, and available news. An availability
headline suppresses the candidate pending human review. These are transparent
screening rules, not fitted coefficients, certified +EV or a statistical guarantee.
No article sentiment or headline is converted into a numeric probability boost.

Chronological expanding-window replay reports holdout Brier score and log loss,
starting after 20 observations. It uses the current fixed line retrospectively.
It does **not** establish betting profitability. Proper calibration still requires
archived point-in-time lines/odds, source snapshots, injuries, costs, independently
verified outcomes, a held-out period, market-specific calibration and correction
for model/selection search. All output remains `not_empirically_calibrated`.

## Source freshness and failure handling

Shared SQLite cache: identity seven days, game logs six hours, news fifteen minutes.
Failed requests get a two-minute negative cache. Source failures never mark old
data fresh; news failure is not presented as proof of health. The UI shows source
check times and sample coverage. The newest 500 entries are retained; this is a
disposable research cache, not the account, odds authority or payment ledger.

The cache defaults to `retained/trends.sqlite3`; override with `CORNER_TRENDS_DB`.
There is one-flight locking per service process and a shared SQLite ceiling of
240 source attempts/hour across processes. Only fixed ESPN hosts/paths are fetched;
clients supply a server-bound retained quote ID, never an arbitrary URL or athlete.
Expired quotes cannot trigger research. Browser requests are account-gated.

**Find research candidates** scans at most 300 upcoming retained selections using
cached data only and returns up to 25 candidates, with checked/unavailable counts.
It does not fetch hundreds of players from a browser action or buy odds data.
Opening a specific selection can fetch bounded free source data. The background
worker fills up to 20 distinct upcoming players per run (maximum CLI limit 40).
Coverage is deliberately bounded; it is not a claim that every retained prop has
been researched. Missing players can be researched directly.

## Deployment and acceptance

The research interface is now The Lab (`/lab`). Props-row Trends links open the
selected retained quote there. See `THE_LAB_UX.md` for the revised UI workflow,
parlay review and staging acceptance checks.

Base: `4b3411b`. No new Python or npm dependency. Caddy's existing
`/api/refresh/v1/*` route already covers the authenticated Trends endpoints.

Run the backend tests:

`python -m unittest tests.test_prop_trends tests.test_trends_service tests.test_trends_worker tests.test_refresh_service tests.test_props_refresh tests.test_scheduled_only tests.test_beta_access tests.test_accounts`

Run `pnpm test` and `pnpm build` in web, then restart the accounts and web services
using the established deployment workflow. Odds collection stays disabled.

With retained quotes present, `python -m pipelines.trends_worker --limit 20`
warms the free cache. It makes no odds-provider requests. Optional hourly systemd
templates are in `deploy/corner-trends.service` and `.timer`. They are supplied
disabled and were not installed or enabled on the VPS by this task. Verify their
paths and units on Linux before enabling. No paid odds-worker configuration changes.

Checks: unit/regression fixtures, UI rendering/escaping and mobile CSS, TypeScript,
production build, and one real public-data adapter smoke test with a synthetic
matchup/price. The smoke test returned 30 baseline games, ten recent rows and
linked news with five free ESPN requests and zero odds-provider calls. It was not
a real offered bet, a calibrated prediction or a VPS publication.

References: ESPN public source responses inspected October 17, 2026;
https://www.nba.com/stats/help/glossary (stat definitions);
https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm (binomial interval
methods). BALLDONTLIE's documented free tier does not include NBA game player
stats, so this feature does not pretend that endpoint is free.
