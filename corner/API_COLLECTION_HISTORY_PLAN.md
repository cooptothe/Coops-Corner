# The Corner: collection budget and Lab-only historical odds

Revised October 19, 2026 — America/Chicago.
Owner clarification: paid historical odds are needed ONLY for The Lab.
Status: planning only. No provider calls, runtime cap changes or activation.
This revision replaces the earlier general 500K historical-research proposal.

## 1. Lab data sources and scope

The Lab has two distinct data needs:

| Feature | Data needed | Paid historical odds required? |
|---|---|---|
| Last game / last 5 / 10 / 20 results | Player game logs | No |
| Hit rate against a user-selected line | Game logs plus selected threshold | No |
| Matchup, minutes, role and supported splits | Verified statistics/context | No |
| News/injury context where available | Free source responses | No |
| Current sportsbook line | Reuse our shared current-odds inventory | No extra historical request |
| Actual bookmaker line/price before a past game | Matched historical odds | Yes, if not already retained |
| Historical price/line movement display | Selected historical snapshots | Yes, only for missing retained snapshots |

The existing trends adapter uses shared ESPN game-log and context caches. Free
sources are subject to their availability, coverage and usage terms; missing
fields must remain unavailable rather than be invented. Cache and rate-limit
source requests. Historical betting prices are not a substitute for game logs,
verified player outcomes, participation, minutes or injury information.

Important UI distinction: "8 of last 10 above today's 22.5 line" is a threshold
comparison, not proof that the player beat the actual historical sportsbook line
8 times. Only label a result as beating the historical offered line when that
specific pregame line is matched and available. Pushes, DNPs, missing stats and
sample size remain visible. Historical hit rates are not forecast win chances.

Paid history is NOT allocated to the EV/arbitrage/middles/promo feeds, automated
CLV gap-filling, a general model-training service or an unrestricted research
crawler. Those feeds reuse current collected odds. Tracker CLV continues to use
eligible retained reference observations and shows unavailable data when missing.
A future scope expansion requires a new budget review.

## 2. Proposed monthly envelope

The advertised API plan is $249 USD for 15M credits including historical access.
Hosting, taxes/currency charges and other costs are outside this API allowance.
Verify the actual purchased quota and provider billing dates before activation.

| Pool | Credits per provider billing cycle |
|---|---:|
| Main markets plus scheduled alternates | 7,900,000 |
| Scheduled player props | 5,000,000 |
| Lab-only historical odds maximum | 100,000 |
| Metadata/operations | 500,000 |
| Protected reserve, not routine spending | 1,500,000 |
| Total | 15,000,000 |

The initial Lab history ceiling is reduced from 500K to 100K. The released 400K
returns to planned main-market headroom; the protected reserve is unchanged.
The 100K is a ceiling, not a target. If The Lab only displays current-threshold
hit rates and game logs, historical-odds spending can remain ZERO.

The current implemented governor still has 8M main / 5M props / 500K metadata
and 1.5M reserve, with no historical adapter or fourth pool. Implementing the
100K Lab pool requires an audited carve-out from main, preserving prior usage,
reservations, unknown charges and cycle bindings. Do not reset the ledger or
claim this document has changed deployed limits.

## 3. 16-hour pregame schedule

All paid dispatch remains 08:00–24:00 Central; no started-event pregame jobs,
no overnight calls and no replay of missed live ticks when the window opens.

| Scope / time to start | Standard books | Approved exchange sources |
|---|---:|---:|
| Main featured odds, throughout the service window | 60 seconds | 20 seconds |
| Additional odds, final 30 minutes only | 60 seconds | 20 seconds |
| Props, greater than 6 hours | 60 minutes | 60 minutes |
| Props, 2–6 hours | 15 minutes | 15 minutes |
| Props, 15 minutes–2 hours | 5 minutes | 5 minutes |
| Props, final 15 minutes | 60 seconds | 20 seconds |

This preserves the existing candidate cadence. Validate each fast source's
classification before activation. Do not request faster than source updates.
Early-morning games during the overnight gap do not get near-start updates.

Additional keys: alternate_spreads, alternate_totals, team_totals, btts,
draw_no_bet. Existing deployed caps remain 50 admitted events/day and 30,000
additional credits/day, shared across leagues. This is not unlimited alternate
coverage. Alternate team totals and the expanded LOCAL alternate-prop catalog
are not silently added to scheduled scope. Local manual-fetch rules remain
separate and do not regain the removed three-game cap.

Conservative 31-day baseline, assuming every requested market is returned:
- Featured per sport key/day = 3 × (960 + 2,880) = 11,520 credits.
- 18 full-time active expanded sport keys × 31 = 6,428,160 credits.
- Additional per game = 5 × (30 + 90) = 600 credits.
- 50 additional games/day × 31 = 930,000 credits.
- Main plus additional = 7,358,160 credits.
- Proposed main headroom = 7,900,000 − 7,358,160 = 541,840 credits.
- With full 5M props, 500K operations and 100K Lab history: routine planned usage
  = 12,958,160, plus 541,840 headroom and the 1.5M protected reserve.

Expanded tennis tournament keys count individually. Nineteen full-time keys plus
max additional coverage = 7,715,280, within 7.9M. Twenty = 8,072,400, which exceeds
main by 172,400. Coverage, active hours and missing markets can reduce charges;
do not spend assumed savings ahead of evidence. Reforecast actual slates before
activation. Worker/publication throughput is an independent cadence gate.

The scheduled props catalog remains 16 basketball / 20 football / 17 baseball /
10 hockey / 8 soccer keys, NOT the larger local manual catalog. Expanding that
set requires its own forecast. The legacy basketball set includes three Q1
prop keys; this document does not silently remove or expand deployed markets.

## 4. Lab-only historical acquisition

History is requested in bounded background batches, not on a polling interval.
The documented ceiling is 10 × markets × effective bookmaker regions per
snapshot. Up to ten explicit books count as one region; 11–20 as two. Event
history settles on unique returned markets; featured history budgets specified
markets. Reserve the full requested ceiling, then reconcile actual headers.

For both current groups, full availability per requested timestamp:
- One event with 16 basketball prop markets: 320 credits.
- One event with 20 football prop markets: 400 credits.
- Another timestamp incurs another charge; a user's repeat view must not.

Proposed sublimits within 100K: 90K selected Lab prop snapshots and 10K historical
discovery/diagnostics/unknown-charge allowance. Example: 90 basketball games ×
three timestamps × 320 = 86,400, within 90K. This is an illustration, not a promise
of complete historical coverage. Selecting fewer needed markets can reduce cost.

Operational rules:
1. First ship the game-log/current-line Lab experience without paid history.
   Only enable historical acquisition when the actual historical-line/price
   feature is ready to use its results.
2. Select exact missing event/market/book/time records after checking retained
   captures. Default to one useful pregame snapshot for selected events; three
   timestamps are an explicit line-movement study, not an automatic default.
3. Initial funded pilot <=5K credits, within the 100K ceiling. Every manifest
   specifies purpose, request set, maximum charge and matched event identities.
4. Maximum batch reservation 10K; one batch in flight; at most one historical
   HTTP request/second and within the provider's overall rate limit. Review at
   20K per rolling seven days; hard stop at 100K/provider cycle. A fifth weekly
   review does not reset the cycle. All retries/bootstrap/unknowns count.
5. Candidate low-priority window: 09:00–11:00 Central, only after pregame jobs
   are caught up. No timer is installed by this document. Stop before the next
   dispatch for overdue current odds, backup lock, reconciliation uncertainty
   or a budget refusal. No historical work outside the 16-hour window.
6. Cache centrally. Exact canonical requests are reusable; after retrieval,
   deduplicate by actual returned snapshot timestamp and event/book/market set.
   Recent snapshots are generally five minutes apart. Do not buy second-by-
   second requests for the same stored snapshot. Coverage varies by date/source.
7. Record raw response/checksum, actual/requested time, acquisition time,
   charge, event/player/line/settlement identities and provenance. Match only
   pregame observations; the nearest snapshot is not necessarily the exact close.
8. The Lab reads precomputed/cached records. Opening a player, adjusting the
   chart line, changing filters or having more members cannot cause a paid
   provider call. If history is absent, display "Historical line unavailable"
   and retain the free game-log chart.
9. Historical observations stay separate from fresh feed snapshots. Do not
   change their dates or republish them as current opportunities. No outcome
   label or projection is invented from odds alone.
10. Check disk capacity before batches and include manifests/raw data in
   encrypted backups. Storage growth and off-server delivery remain separate
   operating considerations; API access does not make storage unlimited.

## 5. Pacing and priorities

Use the actual provider cycle, not a calendar-month reset. Reconcile preexisting
same-key local/manual spending; external usage drift pauses the strict governor.
Forecast actual + reserved/unknown + remaining expected demand by pool daily
and whenever active expanded keys or market catalogs change.

If forecasts exceed a limit: pause Lab historical batches first; then review
additional coverage and slower early pregame polling; then distant props and
early featured exchange polling. Preserve useful approved near-start coverage
where affordable. Candidate reductions require a tested explicit policy; they
are not implemented automatically here. No source is polled faster to chase
missing data. Show skipped/stale coverage rather than pretend it is current.

Stopping Lab history does not automatically enlarge a fixed main pool. Any
reallocation requires an audited transfer preserving the cycle total/reserve;
initial implementation should refuse untested transfers. Never spend protected
credits, upgrade the plan, switch keys or reset accounting automatically.

## 6. Implementation and activation sequence

A. Free/offline work: enforce Lab-only endpoint/manifest scope; add a versioned
fourth-pool migration preserving all ledger history; implement cache/dedup,
read-only historical publication, pacing and backup coordination. Keep all
provider dispatch blocked. Match the existing cached ESPN/free-source path to
Lab game-log needs independently of historical betting prices.

B. Offline acceptance: 18/19/20-key budget scenarios; exact repeated snapshot
reuse; missing markets; historical records never becoming fresh; concurrent
users making zero paid calls; timeouts preserving unknown charges; lease/backup
fencing; cycle boundaries; old ledger migration; disk-bound refusal; restored
pending jobs staying paused with no duplicate charges or rows.

C. Deferred funded gate: verify actual 15M subscription/quota/cycle and prior
usage, review a <=5K Lab manifest, then run the explicitly authorized pilot.
Validate headers, returned data relevance and cache reuse. Include the actual
ledger/captures in an encrypted checkpoint and prove isolated recovery before
activation. No payment or provider activation is authorized by this plan.

D. Supervised operation: start Lab paid history paused. Complete the independent
routine pregame activation gates first; turn on only approved Lab batches when
current-data queues and cycle budgets permit. Review daily for the first week.

Sources verified October 19, 2026:
- Pricing: https://the-odds-api.com/
- Historical billing/coverage: https://the-odds-api.com/liveapi/guides/v4/#get-historical-event-odds
- Intervals: https://the-odds-api.com/sports-odds-data/update-intervals.html
- Existing free-statistics implementation: corner/TRENDS.md and pipelines/trends_service.py.

This document is proposed scope/budget, not a claim that the historical adapter,
new quota pool or historical-line UI has been implemented or activated.
