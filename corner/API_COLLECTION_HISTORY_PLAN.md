# The Corner: pregame collection and historical research plan

Planning date: October 19, 2026 — America/Chicago.
Status: proposed budget and implementation sequence. No collection, provider
request, purchase, quota migration or activation is authorized or performed by
this document. Current disabled staging and local manual controls stay intact.

## 1. Financial envelope

The provider currently advertises 15 million monthly credits for $249 USD,
including historical access. This is the API subscription only; hosting, any
applicable taxes/currency charges and other operating costs are outside this
$249 calculation. Verify the account's actual purchased quota and renewal
boundary before activation. Do not infer purchase from the advertised plan.

Proposed hard allocations per provider billing cycle:

| Pool | Credits | Scope |
|---|---:|---|
| Main | 7,500,000 | Featured odds plus five scheduled additional markets |
| Props | 5,000,000 | Existing reviewed scheduled player-prop catalog |
| History | 500,000 | Bounded historical odds, discovery and reconciliation |
| Metadata/operations | 500,000 | Existing operational allowance |
| Protected reserve | 1,500,000 | Not available to routine dispatch |
| Total | 15,000,000 | 13.5M maximum routine dispatch |

This is a carve-out from the CURRENT 8M main pool, not an extra allowance and
not a proposed reduction of the protected reserve. The current governor has
only main/props/metadata pools. A fourth history pool and audited migration are
implementation work, not already-enforced behavior. Never reset a live cycle
or discard existing usage to adopt the proposal.

Use actual provider billing dates, not calendar-month resets. Model 31 days for
conservative forecasting; prorate pacing against the actual cycle length and
remaining credits, including preexisting manual or research usage on this key.
The provider's response headers, reconciled with the ledger, determine charges.

## 2. Pregame schedule and coverage limits

All paid dispatch remains inside 08:00–24:00 Central. Started events are not
collected as pregame. No overnight backfill of missed live ticks at 08:00.

| Scope / time to start | Standard group | Approved exchange group |
|---|---:|---:|
| Featured main odds, throughout service window | 60 seconds | 20 seconds |
| Additional odds, final 30 minutes only | 60 seconds | 20 seconds |
| Props, greater than 6 hours away | 60 minutes | 60 minutes |
| Props, 2–6 hours away | 15 minutes | 15 minutes |
| Props, 15 minutes–2 hours away | 5 minutes | 5 minutes |
| Props, final 15 minutes | 60 seconds | 20 seconds |

This preserves the current candidate schedule. Fast-group classifications must
be validated per provider venue/market; the proposed group cannot simply make
all venues exchanges. Never poll faster than the documented source cadence.
History has no 20-second cadence: it is immutable data requested in batches.
Events starting during the overnight gap do not get near-start collection.

The five scheduled additional keys are alternate_spreads, alternate_totals,
team_totals, btts and draw_no_bet. The current governor admits at most 50 distinct
additional-market events per Central day and at most 30,000 additional credits
per day. These are global deployed caps, not per league or per member. The local
manual app is separate: it has no restored three-game cap, uses its local-day
market policy, and does not silently inherit deployed collection schedules.
Alternate team totals and expanded alternate player props in the LOCAL catalog
are not implicitly added to this deployed forecast.

At full returned markets, existing groups of six standard and six fast books:
- Featured per sport key/day: 3 × (960 + 2,880) = 11,520 credits.
- 18 full-time active sport keys × 31 days = 6,428,160 credits.
- Additional per admitted event: 5 × (30 + 90) = 600 credits.
- 50/day × 31 days = at most 930,000 additional credits.
- Main plus additional planning total = 7,358,160 credits.
- Proposed 7.5M main-pool headroom = 141,840 credits, about 1.9%.

The 18-key assumption includes actual expanded provider sport keys. ATP/WTA
picker names do not count as one key if discovery expands them into several
tournaments. At 19 full-time keys and maximum additional coverage, main usage
would be 7,715,280: 215,280 OVER the proposed main allocation. Inactive leagues,
missing markets and shorter actual activity may reduce charges, but savings
are not pre-spent. A provider-calendar audit is required before live sign-off.

With props and operations using their full allowances, modeled routine usage
is 13,358,160 credits including 500K history; 141,840 operating headroom and the
1.5M protected reserve remain. It is a conditional fit, not unlimited coverage.
Serial worker/publication throughput must also sustain the cadences; credit
arithmetic alone does not establish update latency.

## 3. Historical work: purpose, scope and cost

Use history for: missing closing-reference observations; selected opening/near-
close price comparisons; and reproducible, outcome-matched calibration studies.
Do not download every five-minute snapshot for every event. Do not fetch history
from a member page, on every Lab line adjustment, or once per user.

A historical request costs 10 × market count × effective bookmaker regions.
With explicit bookmakers, up to ten count as one region, 11–20 as two. For the
current two groups, plan two effective regions. Event history uses returned
unique markets; featured history budgets specified markets. Reserve the full
requested ceiling before dispatch; settle only against verified actual headers.

Examples for ONE requested timestamp, assuming full availability:

| Request | Planned cost |
|---|---:|
| One league, three featured markets, both groups | 60 |
| One event, five additional markets, both groups | 100 |
| One basketball event, 16 scheduled prop keys, both groups | 320 |
| One football event, 20 scheduled prop keys, both groups | 400 |

Featured league history can include several games. Event props/additional history
must be requested per event. Another timestamp incurs another charge. Coverage
varies by bookmaker, sport and date. Available history does not mean every
requested player/line existed. Recent snapshots are generally five minutes apart;
additional-market history is available after May 3, 2023 at 05:30 UTC.

Initial 500K history envelope:

| Historical purpose | Maximum credits/cycle |
|---|---:|
| Prop calibration / missing prop closes | 300,000 |
| Additional-market price/CLV gaps | 100,000 |
| Featured market studies / missing closes | 50,000 |
| Historical discovery, sample diagnostics, unresolved charges | 50,000 |
| Total | 500,000 |

These are planning sublimits. No credit is spent simply because a sublimit exists.
Examples, not guaranteed dataset sizes:
- 300 basketball games × 3 timestamps × 320 = 288,000 credits, inside the prop
  sublimit. A football-heavy sample costs more; recalculation is required.
- 1,000 five-market additional event snapshots × 100 = 100,000 credits; this is
  1,000 timestamps, not 1,000 games at several timestamps.
- At most 833 three-market/two-group featured league snapshots fit in 50,000.
- 500 basketball games × 3 × 320 = 480,000: it does NOT fit the 300K prop sublimit.

Default new studies use full-game markets, excluding game-period markets.
Published examples using the 16-key existing scheduled basketball catalog are
conservative acquisition illustrations: that legacy scheduled set includes
three Q1 prop keys. Removing them from deployed collection is a separate policy
change, not silently assumed here.

## 4. Batch operation and reuse

1. Build a manifest offline: study purpose, market/book list, event IDs, requested
   timestamps, full cost ceiling and sample-selection rule. Prefer a small
   representative sample spanning price bands, sports and dates to a huge
   cherry-picked backfill. Initial pilot ceiling: 25K credits, counted WITHIN
   the cycle envelope; not an extra allowance.
2. Put history behind current pregame work. Candidate maintenance slots are
   09:00–11:00 Central, with an optional 13:00 review slot when queues are quiet.
   These are proposed windows, not installed timers. Pause before dispatch when
   current odds are overdue, backups hold the maintenance lock, reconciliation
   is uncertain, or any budget gate is blocked.
3. One batch in flight, maximum 25K credits reserved for a batch, at most one
   historical HTTP request per second. Per-request cost and total shared provider
   request rate still apply. Bootstrap uses at most 100K of the 500K envelope.
4. Review at 100K historical credits per rolling seven days; hard stop at 500K
   per provider cycle and within each sublimit. A fifth weekly review does not
   reset or add credits. Bootstrap and retries count toward the same ceilings.
5. Save raw response/checksum, actual snapshot timestamp, requested timestamp,
   event/market/book identities, acquisition time, actual charge and provenance.
   Cache exact canonical requests; after retrieval deduplicate by the ACTUAL
   snapshot identity. Do not assume different requested times mean different
   returned snapshots or charge users again for displaying cached results.
6. Reuse retained routine captures first for CLV and research. Backfill only
   genuine gaps after checking contract/player/line/settlement identity. Closest
   available pregame snapshot is not automatically the exact closing price.
7. Historical data stays in a historical namespace. Never republish it as fresh
   odds, alter its dates, or use post-start prices to prove pregame model quality.

Research needs independently matched outcomes, participation/void/push handling,
and chronological out-of-sample evaluation. Historical odds alone do not supply
verified player results or establish profitable predictions. Missing outcomes and
coverage bias must be reported, not silently dropped to improve a score.

## 5. Pacing, escalation and hard stops

Recalculate provider-cycle forecasts at least daily and after discovery changes.
Track actual + reserved/unknown charges + remaining scheduled demand for each
pool. Report active expanded keys, admitted/skipped events, returned market
counts, credits/day, cycle remaining and feed freshness. All users share this
acquisition inventory; user count and repeated page views do not multiply calls.

Priority order when forecasts exceed a limit:
1. Stop/defer new historical batches. Do not touch the reserve.
2. Review expensive additional coverage; a proposed degradation is 60-second
   polling for all groups or a narrower final window, rather than buying data
   that the API does not update. Keep skipped/degraded coverage visible.
3. Slow distant pregame prop polling before sacrificing near-start coverage;
   evaluate expanded prop markets selectively rather than turning on every
   local market at once.
4. If necessary, reduce early featured exchange polling toward 60 seconds while
   preserving approved fast near-start sources. This needs a tested explicit
   cadence policy; it is not implemented by this document.
5. At a hard cap, do not dispatch. If useful coverage cannot be maintained, show
   it as unavailable/stale and require an operator decision. No automatic paid
   plan upgrade, reserve spending, hidden pool borrowing or account/key switch.

Stopping history does not itself enlarge a fixed main pool. Moving unused history
allocation back to main requires an audited, explicit cap transfer preserving
15M total and 1.5M reserve. Initial implementation should refuse such transfers
until separately tested; reduce demand instead. Same-key local manual requests
also consume this purchased quota and must be reconciled; uncontrolled external
usage pauses the current strict governor. Never run an unaccounted manual client
alongside the supervised worker.

## 6. Implementation and activation sequence

Phase A — free/offline engineering:
- Add versioned proposed budget policy and a fourth ledger pool; preserve every
  previous attempt, cycle binding, offset and reserved unknown. Verify allocation
  sums, month boundaries, and safe migration against a copy, not a reset.
- Implement a dedicated read-only historical acquisition adapter with fixed
  endpoint allowlist, batch manifest, dry-run estimates, cache and separate data
  namespace. Bind all paid requests to the same governor/key/cycle.
- Persist work and outbox idempotently; use shared maintenance lock and quota
  lease. Retrying publication/research must not buy another snapshot by default.
- Refuse guessed charges after timeouts; reserve unknown costs, pause and require
  operator reconciliation. The existing fail-closed policy remains in force.
- Add backup/restore coverage for historical manifests, ledger/outbox and raw
  captures. Test restore stays paused and replay adds neither charges nor rows.
- Add offline scenarios for 18 versus 19+ keys, busy sports weekends, incomplete
  market returns, repeated timestamps, billing rollover, cap refusals, source
  withdrawal, external usage drift and interrupted checkpoints.

Phase B — funded checks, deferred until authorized:
- Verify purchased 15M quota/cycle and prior spending; do not print the key.
- Run a pre-approved pilot <=25K history credits only after manifest review.
  Verify actual headers, coverage, cache reuse, outcome matching and storage.
- Run bounded live provider/cadence and throughput checks separately.
- Include actual ledger/captures in a fresh coordinated encrypted checkpoint and
  prove isolated recovery. Match activation evidence to the final deployed commit.

Phase C — supervised beta operation:
- Start with historical work paused; enable routine pregame collection only
  after its independent activation gates pass.
- Review first-day provider headers and projected cycle use. Enable history only
  when coverage, queues and remaining allocations support its approved pilot.
- Review daily for seven days, then weekly. Do not promise full expanded prop or
  unlimited alt/history coverage before the actual slate forecast passes.

## 7. Acceptance criteria

No API or wallet spending during Phase A. Maximum routine allowance 13.5M;
reserve 1.5M; provider cycle total 15M. Simulated 18-key baseline and all sublimits
must reconcile. A 19-key full-time + max-alt slate must flag overbudget rather
than pass. Duplicate cache reads make zero provider calls. Unknown costs never
become zero automatically. Restored work remains paused and replay-safe.
Historical observations cannot appear as live opportunities. No UI interaction
starts a provider request. Costs and source timestamps remain auditable.

Sources verified October 19, 2026:
- Pricing: https://the-odds-api.com/
- Historical endpoints/billing: https://the-odds-api.com/liveapi/guides/v4/#get-historical-event-odds
- Featured history: https://the-odds-api.com/liveapi/guides/v4/#get-historical-odds
- Provider intervals: https://the-odds-api.com/sports-odds-data/update-intervals.html
- Market scope: https://the-odds-api.com/sports-odds-data/betting-markets.html

Code inspected: corner/collection_policy.py, corner/collection_quota.py,
corner/credit_governor.py, corner/additional_markets.py, corner/prop_markets.py,
pipelines/collection_provider.py and pipelines/collection_live.py. This document
is a plan, not a claim that these proposed historical controls exist today.
