# All-book scheduled pregame collection

Updated October 31, 2026. Collection window: 06:00 inclusive through 22:00 exclusive America/Chicago.

The window remains 16 hours. Cadences, pool caps and protected reserve are unchanged.
A 06:00–24:00 window would raise the conservative 30-day main ceiling from
7,084,800 to 7,970,400 credits, exceeding the 7.9M main pool before live/additional
allowances. The saved props schedule estimate below has not been recalculated
for the shifted hours; durable pool caps remain authoritative.
Scope is upcoming events in the next 24 hours. Game starts, source timestamps,
withdrawals, minimum reference requirements and the 30-minute retention rule remain
unchanged. Intervals are minimum due times, not end-to-end delivery guarantees.

## Requested books

All three acquisition kinds request the same sixteen books, split into two groups:

- Standard (ten): DraftKings, FanDuel, theScore Bet (`espnbet`), BetMGM, BetRivers,
  Pinnacle, BetOnline (`betonlineag`), Caesars (`williamhill_us`), Bovada, Fanatics.
- Exchange (six): Novig, Betfair Exchange (`betfair_ex_uk`), ProphetX, Kalshi,
  BetOpenly, Polymarket (`polymarket_us`). The owner-confirmed US venue is preserved.

The provider bills up to ten explicit bookmaker IDs as one region equivalent.
Each group therefore reserves one credit per requested market; together they are
two blocks. Returned x-requests headers settle actual usage. Empty/unavailable
markets need not incur the maximum reservation. Unsupported markets cannot be
manufactured. DFS remains excluded.

## Countdown intervals

Standard and exchange groups use identical bands. No sub-minute exchange polling.

| Time until start | Main lines | Player props |
|---|---:|---:|
| More than 12 hours, up to 24 hours | 15 minutes | 10 minutes |
| More than 6 hours, up to 12 hours | 10 minutes | 5 minutes |
| More than 4 hours, up to 6 hours | 5 minutes | 3 minutes |
| More than 2 hours, up to 4 hours | 5 minutes | 2 minutes |
| More than 1 hour, up to 2 hours | 3 minutes | 60 seconds |
| Final hour | 2 minutes | 60 seconds |

Main-line requests contain the league's upcoming board; their band follows the
soonest known upcoming start in that league. An unknown start uses two minutes.

| Time until start | Additional / alternate markets |
|---|---:|
| More than 2 hours | Not collected |
| More than 60 minutes, up to 120 minutes | 10 minutes |
| More than 30 minutes, up to 60 minutes | 5 minutes |
| More than 15 minutes, up to 30 minutes | 2 minutes |
| Final 15 minutes | 60 seconds |

Main and additional captures feed EV, arbitrage, middles, schedule and promo tools
from the same store. Props also feed their supported downstream tools. No separate
purchase per screen. No NCAA football or basketball player props. Fee-dependent
venues remain excluded as execution targets until the required fee context is
known; valid matching raw prices can still inform references. Collection does not
mean every venue has an executable positive edge or adequate available liquidity.

## Budget

Existing allocations are unchanged: main/additional 7.9M, props 5M, metadata 500k,
Lab history 100k. Protected reserve 1.5M. Historical acquisition is not activated.

Full November UTC planning on the saved public schedule:

| Component | Credits |
|---|---:|
| Main: 82 keys, both groups, fastest two-minute band for all 16 hours | 7,084,800 |
| Additional: 26,296 daily cap across 31 possible Central dates | 815,176 |
| Props: actual configured market counts, both groups, countdown bands | 4,914,836 |
| Metadata | 500,000 |
| Lab history allowance | 100,000 |
| Total planning envelope | 13,414,812 |
| Remaining under that envelope | 1,585,188 |

This is a saved-schedule estimate plus conservative main/additional bounds, not a
live quota balance or guaranteed bill. Main's actual countdown bands are slower
than its planning ceiling. Missing or changed events, start times, availability,
provider charges and workload change actual consumption. The saved props workload
is below its 5M pool by 85,164 credits; extra activity can exhaust that pool. Hard
pool limits and the global reserve then refuse further purchases rather than
spending the reserve. We do not buy extra data just to spend down to 1.5M.

Additional acquisition remains capped at 73 events/day and 26,296 credits/day in a
30-day cycle; 50 events/day and 18,095 credits/day in a 31-day cycle. Both groups
share those caps. At most 36 polls/group/event are allowed for planning (normally
35 from the countdown bands), five market keys, 360 credits/event total. Caps are
durable across restarts and preserve prior admitted events and uncertain charges.

Machine-readable breakdown and saved event-source hash: ALL_BOOKS_FORECAST.json.
The older CADENCE_FORECAST.json describes the prior nine/ten-book policy only.

## Deployment and approval

The `all-books-pregame-v1` profile explicitly binds the sixteen IDs and the
`all-books-countdown-60s-floor-v1` cadence. It does not claim measured 20-second
classification or full-slate throughput. Prior protected activation checks remain.
Use `CORNER_ENABLE_ALL_BOOKS=1 bash deploy/update-expanded-books.sh` after stopping
the collector and pulling. This prepares renewed root approval using the existing
bound quota cycle. Later recoveries preserve the all-book profile.

No cycle reset, refund, quarantine clearing, writer privilege expansion, paid
validation request or automatic next-cycle binding. October approval still ends
November 1 UTC; November requires its own explicit fresh quota binding/approval.
Previously purchased six/nine-book captures replay with their original manifests.
Polymarket international legacy captures are not relabeled as US captures.

## Provider sources

- Billing and parameters: https://the-odds-api.com/liveapi/guides/v4/
- Book IDs: https://the-odds-api.com/sports-odds-data/bookmaker-apis.html
- Update floors: https://the-odds-api.com/sports-odds-data/update-intervals.html

Provider pregame books refresh around 60 seconds, exchanges around 20 seconds.
Our exchange floor is deliberately 60 seconds or slower. Serial request spacing
remains 100ms, with no retry of an uncertain paid request. `includeBetLimits=true`
requests available limits/open BetOpenly offers; liquidity is not matched volume.
