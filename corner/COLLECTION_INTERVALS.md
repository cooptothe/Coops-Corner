# Scheduled collection: optimized cadence, October 20, 2026

Collection runs 8 a.m.–midnight America/Chicago. Standard pregame requests
never run faster than 60 seconds per scope. Games must be upcoming and within
24 hours. No NCAA football or basketball player props are purchased.

| Scope | Time before start | Target interval |
|---|---|---:|
| Main h2h, spreads, totals | All | 60 seconds |
| Additional/alternate markets | 1–2 hours | 5 minutes |
| Additional/alternate markets | Final hour | 60 seconds |
| Pro player props | 6–24 hours, 28/29/30-day months | 150 seconds |
| Pro player props | 6–24 hours, 31-day months | 180 seconds |
| Pro player props | Final 6 hours | 60 seconds |

Additional keys remain alternate_spreads, alternate_totals, btts, draw_no_bet
and team_totals. Main/additional quotes share EV, arbitrage, middles, schedule
and promo conversion; no duplicated acquisitions per tool. Props continue to
feed their supported downstream tools. No period-market expansion is included.

Main standard books: DraftKings, FanDuel, theScore (espnbet), BetMGM,
BetRivers, Pinnacle, BetOnline, Caesars (williamhill_us), Bovada: nine books.
Props add Fanatics: ten books, still one region-equivalent. Manual requests
remain fifteen main/sixteen props books, still two billing blocks. Dormant
exchange groups retain their old unverified policy and remain disabled.
BetOnline and Bovada remain eligible main/props references with relative weight
1; existing FanDuel/Pinnacle props weights, target exclusion, matched lines,
devigging and the two-reference gate are unchanged. One-sided margin estimates
remain modeled assumptions, not fitted win probabilities. User filters cannot
change reference policy. Caesars remains a props target and eligible reference.

## Budget and daily alternate limits

Existing pools stay main 7.9M, props 5M, metadata 500k, Lab history 100k.
Total spending cannot exceed 13.5M; the 1.5M reserve stays protected. No policy
migration, usage reset, refund, quarantine clearing or historical activation.

Alternate daily caps are computed from the actual bound cycle length after
allowing for an 82-key main stress ceiling (960 polls/day, three market keys).
UTC quota cycles touch an extra Central calendar date, so that partial day is
budgeted too. November allows at most 73 alternate events/day and 26,296
credits/day; a 31-day cycle allows at most 50 events/day and 18,095 credits/day.
Both event and credit caps are durable; repeated restarts cannot reset them.
These caps bound acquisition, not a promise every listed event is available.
The first eligible events admitted by the existing round-robin worker consume
the daily places. Already admitted events and unknown charges still count.

| Full November planning component | Credits |
|---|---:|
| Main stress ceiling: 82 expanded keys, all 16 hours, one minute | 7,084,800 |
| Additional ceiling: 26,296 x 31 possible Central dates | 815,176 |
| Pro props: saved event schedule, all keys returned | 4,933,976 |
| Metadata allowance | 500,000 |
| Lab historical allowance (not enabled) | 100,000 |
| Total planning envelope | 13,433,952 |
| Balance under that envelope | 1,566,048 |

This is a conservative envelope, not a prediction of actual spend. Main's
82-key assumption substantially exceeds typical configured activity; missing
markets, empty responses, unavailable books, quarantine and serial latency
reduce actual use. The earlier 9.34M envelope was also not an actual-bill
forecast. We do not buy redundant requests to force exactly 1.5M remaining.
Extra events or changing start times can exhaust a pool; claims then stop
within that pool rather than consuming the protected reserve. No empirical
throughput guarantee or full-provider coverage is claimed.

The saved schedule research contains 4,116 non-tennis November events, including
NCAA games excluded from props. Future tennis tournament draws are incomplete;
82 is a stress assumption, not an API promise. NBA/NHL/NFL and soccer schedules
can change. The 30-second simulation grid respects the selected 150/60-second
bands and uses all configured keys on every simulated request. Reproducible
summary and saved-source hash: CADENCE_FORECAST.json.

## Provider documentation reviewed

- V4: https://the-odds-api.com/liveapi/guides/v4/
- Refresh rates: https://the-odds-api.com/sports-odds-data/update-intervals.html
- Rate limits: https://the-odds-api.com/guide/rate-limit.html

Main lines use league /odds; props and alternates use one-event /events/id/odds.
Combined requested keys are already batched per event/group. Explicit books
override regions and bill in groups of ten. Charges use returned market keys;
empty responses cost zero. Actual x-requests-* headers, not the forecast,
settle each reservation. Market availability varies by event and bookmaker.
The /events list is cached by existing discovery. We do not add /markets calls
per tick (that endpoint costs a credit and is not a complete coverage list).
Requests stay serial and now have a 100ms start-spacing floor (at most ten
per second per worker), below the published paid-plan 30/s ceiling. 429s can
still occur; unknown accounting retains existing stop/reconcile controls,
never an automatic repeat of an uncertain paid request.

## Freshness and deployment

Cadences are minimum due intervals, not a latency SLA. Source and capture age
both remain capped at 30 minutes; replay never re-dates a price. Withdrawals,
started games and reader failure can remove results sooner. Quotes >=5 minutes
old carry verification guidance. Strict CLV evidence windows remain unchanged.
Previously purchased six-book main/additional publications still replay with
their original manifest, digest, timestamps and token. Props snapshots remain
readable across book-group changes. No paid odds calls are needed for tests.

Deploy with deploy/update-expanded-books.sh after stopping the worker and
pulling this commit. Recovery preserves all charges and quarantines, verifies
fresh quota, and renews commit-specific root approval before restart. No new
cycle is created: October approval still expires November 1 UTC. Fresh explicit
quota binding/approval for November remains required before that boundary.
