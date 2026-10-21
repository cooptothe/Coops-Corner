# Scheduled collection forecast — October 20, 2026

## Final owner scope

8 a.m.–midnight America/Chicago, including the November DST change.
Main leagues: every 60 seconds throughout the 16-hour collection window.
This matches the provider's published standard pregame update interval; no
sub-minute standard requests or in-play collection are enabled.
Main/additional standard group: the original six plus BetOnline (betonlineag),
Caesars (williamhill_us), and Bovada (bovada). Nine books remain one billed
region-equivalent. Props use a separate ten-book standard group with the existing cadence;
local manual props request sixteen books including exchanges.
Additional markets: every 2 minutes in the final hour, existing 50-event/day
and 30,000-credit/day safeguards retained. Props: >6 hours hourly; 2–6 hours
every 5 minutes; final 2 hours every minute. No scheduled NCAA football,
men's basketball or women's basketball props. College main/additional markets
remain. Dormant exchange groups remain disabled; no history collector enabled.

## Schedule evidence

Free ESPN public scoreboard queries were downloaded for each day October 21
through December 1, 2026. Fifteen non-tennis league queries per day succeeded;
UFC and ATP/WTA used available tournament/card range responses. Event IDs were
deduplicated within each league. October 21–November 20 Central contains 3,187
listed non-tennis events; November UTC contains 4,116. The raw public schedule
lookup also returned nine ATP and seventeen WTA tournaments overlapping the
initial period. Tournaments are not individual matches: future draws cannot
be enumerated reliably now. UFC cards do not enumerate every MMA promotion.
Schedules can be revised, playoff games are conditional, and some start times
are unconfirmed. Public events do not prove provider book/market availability.
No paid odds or historical requests were made for this research.

Sources (publisher-operated public endpoints):
https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard
https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard
https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard
https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard
https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard
https://site.api.espn.com/apis/site/v2/sports/basketball/womens-college-basketball/scoreboard
Other soccer, MLB, WNBA and MMA paths are recorded in the exported inventory.
Billing: https://the-odds-api.com/liveapi/guides/v4/
Provider refresh rates: https://the-odds-api.com/sports-odds-data/update-intervals.html

## Full November quota-cycle forecast

| Component | Credits |
|---|---:|
| Pro props, every configured key returned on every planned poll | 1,433,880 |
| Main stress envelope: 82 expanded keys, all 16 hours, every minute | 7,084,800 |
| Additional: maximum 50 games/day, 30 polls/game, 5 keys | 225,000 |
| Metadata allowance (actual discovery currently zero charge) | 500,000 |
| Lab historical allowance (not activated) | 100,000 |
| Total spending envelope | 9,343,680 |
| Total with another 20% added to props | 9,630,456 |
| Protected reserve, outside spending envelope | 1,500,000 |

The 82-key main envelope deliberately overstates the configured schedule and
assumes every key returns all three main markets every minute. It fits existing
main 7.9M/props 5M allocations. No budget migration, reset or extra purchase is
needed. Existing usage remains charged; all pool/reserve guards remain.
The next-month span crosses the November 1 UTC quota reset; both October's
remaining dates and the whole November cycle were simulated separately.
The original November assumptions produced a much larger NCAA props bill;
the final forecast excludes all three NCAA categories explicitly.

Peak modeled near-start *pro props* events: 23 (October 28, 22:30 UTC).
A serial worker still depends on HTTP/database latency, publication backlog,
quarantines and discovery time. Cadences are minimum due intervals, not a
latency SLA. No actual VPS load test for this new schedule is claimed.

## Freshness and rollout

Owner update: all scheduled source-age ceilings are 30 minutes (1,800 seconds).
Neither receipt nor replay re-dates provider prices. Source age and capture age
must both remain under that ceiling. Prices five minutes or older are marked
"Verify odds"; display is not proof the edge still exists at the sportsbook.
Withdrawals, started games and reader failures still remove results immediately.
Existing expired snapshots are not rewritten or resurrected; the new ceiling
applies to new captures after rollout. Hourly distant main polling can still
have gaps after 30 minutes, as explicitly requested by the owner’s age limit.
Strict CLV evidence windows are unchanged, so slower main polling may leave
more bets without a qualifying closing sample.

The worker's existing cycle/activation expires at November 1 UTC. This patch
does not auto-reset usage or silently bind a new cycle. A fresh provider quota
verification and explicit November binding/approval are still required before
that boundary. The forecast is not evidence that rollover is already set up.

## Book expansion and acquisition compatibility

Official keys checked October 20, 2026:
https://the-odds-api.com/sports-odds-data/bookmaker-apis.html
The provider bills explicit bookmaker groups in blocks of ten. Moving scheduled
main/additional requests from six to nine books does not add a billing tier.
The local manual main list moves from twelve to fifteen, still two blocks.
BetOnline and Bovada are now owner-selected main/alternate reference books
as well as eligible targets. Caesars is an added target. New quotes apply
wherever the provider supplies comparable valid prices;
book-by-market coverage is not guaranteed or proved by a no-network test.
Straight fixed-odds payouts use the existing zero straight-bet commission model;
this does not model funding/withdrawal charges, taxes or promotional offers.
Allowlisted links use betonline.ag, bovada.lv and existing Caesars domains.

A 31-day stress envelope is 7,553,460 credits for main plus capped additional
markets, still below the existing 7.9M main allocation. November's 30-day main
plus additional envelope is 7,309,800. Existing 5M props allocation, 100k history
allocation, 500k metadata allocation and 1.5M protected reserve are unchanged.
Actual eligible leagues are a subset of the conservative 82-key envelope.

New acquisitions require the complete nine-book main group. Already purchased
six-book main/additional outbox records can replay without rewriting their
manifest, original requested books, timestamps or payload digest. No arbitrary
partial book scope is accepted and no accounting reset occurs.

Main reference update: BetOnline and Bovada use the conservative unit reputation
prior, not a claim of fitted accuracy or equal sharpness to Pinnacle. Target
books never reference their own price; two complete independent references are
still required (existing soccer single-reference exception unchanged). User
filters do not alter reference selection. Main fair estimates can change when
these new reference prices are present. Props use their existing reference
policy, with a separate optional CORNER_PROPS_REFERENCE_BOOKS operator setting;
legacy overrides remain supported; BetOnline and Bovada are explicitly included
as props references through the separate props policy.
All supported board quotes feed EV, arbitrage, middles, schedule, and promo
conversion through the shared retained catalog; no duplicate acquisitions.


Final props expansion (owner approved): scheduled props now request ten cash
books, including Caesars, Fanatics, BetOnline and Bovada; manual props request
sixteen books including the existing exchange list. These remain one and two
ten-book billing blocks respectively. BetOnline and Bovada are eligible props
references with relative weight 1, below existing FanDuel/Pinnacle priors. The
target is excluded and two eligible independent references remain required.
Exact pairs are devigged; modeled one-sided assumptions remain disclosed, not
empirically calibrated. More returned market keys can increase actual charges
when previously absent, but market-count ceilings and quota guards are unchanged.
No new paid request is needed for deployment verification.
