# Full-quota collection intervals

Updated November 1, 2026. Window: **06:00–22:00 America/Chicago**.
All 15M credits are authorized for useful collection. The owner explicitly
removed the previous 1.5M protected holdback; unused credits do not accumulate.
The hard 15M ceiling, actual-charge accounting and request reservations remain.

| Time before start | Main lines | Player props |
|---|---:|---:|
| 12–24 hours | 15 min | 5 min |
| 8–12 hours | 10 min | 4 min |
| 6–8 hours | 5 min | 3 min |
| 4–6 hours | 3 min | 2 min |
| 3–4 hours | 2 min | 90 sec |
| 2–3 hours | 90 sec | 60 sec |
| Final 2 hours | 60 sec | 60 sec |

At an exact boundary the faster band applies. Main league boards use the
nearest upcoming start; no known start within 24 hours uses a 15-minute board
poll. All 16 books remain configured, props exclude Betfair and NCAA sports.

| Time before start | Additional/alternate markets |
|---|---:|
| More than 2 hours | Not requested |
| 90–120 minutes | 10 min |
| 60–90 minutes | 8 min |
| 45–60 minutes | 4 min |
| 30–45 minutes | 3 min |
| 20–30 minutes | 2 min |
| 10–20 minutes | 90 sec |
| Final 10 minutes | 60 sec |

Live pacing targets provider floors of **40 seconds standard / 10 seconds
exchange**, within an increased 3M monthly and 150k daily subcap. Its normal
monthly pacing allowance starts near 100k/day; observed demand adjusts intervals.
These credits are part of main's pool. Planning ends at 22:00, avoiding budgeting
for closed hours. Busy slates and depleted allowances can require slower intervals.

## Allocations and forecast

| Pool | Credits |
|---|---:|
| Main/live/alternates combined | 7,500,000 |
| Player props | 7,400,000 |
| Metadata/reconciliation allowance | 100,000 |
| Historical acquisition | 0 |
| Protected holdback | 0 |
| Total | 15,000,000 |

Metadata remains a small accounting allowance for discovery; free discovery
requests normally settle at zero. Historical acquisition remains disabled.
Moving these allocations never changes prior charges, offsets or cycle dates.
The stopped-worker upgrade explicitly verifies current usage before replacing
only the current cycle's policy record and auditing the allocation change.

Alternate daily credit cap: 30k, at most 66 new games/day using a conservative
45 polls per group per game including transition overhead. Existing admissions
are preserved. The shared main pool always overrides this subcap.

465 free ESPN daily scoreboard queries succeeded for November 1–December 1.
Through November 20: 147 NBA, 132 NHL, 43 NFL games, soccer and NCAA boards.
No NCAA props. Expanded tennis match slates are not completely known this far
ahead; scenario reserves room for 16 additional keys at one-minute polling for
all 16 open hours daily. Some college/soccer start times remain provisional.

Full-month model: props 7,112,092 credits; known non-tennis main boards 769,812.
Including extra-key allowance, full live/alternate allowances, metadata and
reported 71,807 credits added again conservatively, the planning scenario is
14,748,511 credits, leaving about 251k. Through November 20 the scenario is about
9.66M credits, leaving about 5.34M for the remainder of November.

This is not a guaranteed spend or a promised ending balance. Actual returned
market counts, outages, reschedules, new events and liquidity affect consumption.
Polling faster than the provider updates solely to reach zero would waste quota.
Intervals are due times, not guaranteed network or publication delivery times.
Source timestamps and existing quote-expiry rules remain unchanged.

Quota resets December 1 UTC, independently of the November 20 invoice.
Sources/inputs: `forecasts/november-2026-events.json` and
`forecasts/november-2026-cadence.json`. Reproduce the old/new schedule simulation
offline with `python -m pipelines.collection_cadence_forecast`.

Provider limits: https://the-odds-api.com/sports-odds-data/update-intervals.html
Billing docs: https://the-odds-api.com/liveapi/guides/v4/
Reset FAQ: https://the-odds-api.com/manage/faqs.html
