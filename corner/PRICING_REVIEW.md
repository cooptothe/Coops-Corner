# Pricing review - October 16, 2026

This release is based on c0032c2. No live collector is enabled. Local manual
fetching and the confirmed Polymarket .us link behavior are preserved.

## Verified fee boundaries

| Book / product | Ordinary straight-bet treatment | Release behavior |
| --- | --- | --- |
| DraftKings Sportsbook | Return is stake times quoted decimal odds; margin is already in prices | Zero separate exchange commission |
| FanDuel Sportsbook | Fixed odds with embedded margin | Zero separate exchange commission |
| theScore Bet (provider espnbet) | Fixed-odds sportsbook settlement | Zero separate exchange commission |
| BetMGM Sportsbook | Fixed odds with embedded margin | Zero separate exchange commission |
| BetRivers Sportsbook | Fixed-odds sportsbook settlement | Zero separate exchange commission |
| Pinnacle | Fixed odds with embedded margin | Zero separate exchange commission |
| Novig | Pregame straight app/website trades fee-free; futures/live/parlays have different treatment | Zero for this pregame straight scope only |
| ProphetX | October 12 version 1.3: 2% of positive net gains per market | 0.02 on isolated straight targets; no assumed rebates |
| Betfair Exchange | Positive market-net winnings; rate depends on account package, jurisdiction and market | Requires operator-confirmed CORNER_BETFAIR_COMMISSION; unset/invalid is unknown, not zero |
| BetOpenly | Developer-owned app advertises 1%; developer documentation identifies commission on wins, but exact current fee base was not independently verified | Unverified targets excluded from financial tools; quotes retained |
| Kalshi | General taker coefficient 0.07 times contracts times price times (1-price), series multipliers/exceptions; maker coefficient 0.0175 where applicable | Explicit fee utility tested; feed needs series, execution quantity, rounding and gross/net price evidence before target use |
| Polymarket US | Standard taker coefficient 0.0695; table-tennis exception 0.10; nearest-cent half-even rounding; combos have separate curve | Explicit fee utility tested; feed needs confirmed US venue/contract/execution context before target use |
| Polymarket international | Category/market-specific taker fees; not interchangeable with US schedule | Never substitute international fees for confirmed .us destination |
| PrizePicks / Underdog | Indicative DFS odds and lineup-dependent payouts, not independent straight-bet return contracts | Preserve collection; exclude indicative prices as probability references and standalone EV targets |

Fixed sportsbook rows concern ordinary cash straight wagers only. Promotions,
taxes, deposits, withdrawals, cashout, account-specific charges, execution depth,
and dead heats need separate handling. No additional fixed "vig fee" is subtracted
from an already quoted sportsbook target price.

Sources checked October 16:

- DraftKings: https://help.draftkings.com/hc/en-us/articles/360061942833-Understanding-Odds-US
- FanDuel: https://support.fanduel.com/s/article/Sports-Betting-Terms
- theScore: https://sportsbook.thescore.bet/hc/en-us/articles/40914371384077-Terms-of-Use-US
- BetMGM: https://sports.betmgm.com/en/blog/what-is-vigorish-explanation-sports-betting-bm06/
- BetRivers: https://helpcenter.betrivers.com/s/article/Sportsbetting-Quickstart-Guide?code=Ontario
- Pinnacle: https://www.pinnacle.com/betting-resources/en/betting-tools/margin-calculator
- Novig: https://support.novig.com/en/articles/16195057-fees-on-novig
- ProphetX: https://www.prophetx.co/lobby/t-c/trading-fees (supersedes older 3% marketing pages)
- Betfair: https://www.betfair.com/GBR/en/aboutUs/Betfair.Charges/
- BetOpenly: https://apps.apple.com/us/app/betopenly/id6471480892 and https://dev.betopenly.com/docs/integration-patterns/ (fee base remains unverified)
- Kalshi: https://kalshi.com/docs/kalshi-fee-schedule.pdf (July 7 effective schedule; series and rounding exceptions apply)
- Polymarket US: https://docs.polymarket.us/fees
- Polymarket international: https://help.polymarket.com/en/articles/13364478-trading-fees and https://polymarket.com/fees
- Provider venue keys and indicative DFS odds: https://the-odds-api.com/sports-odds-data/bookmaker-apis.html
- PrizePicks: https://www.prizepicks.com/help-center/payouts
- Underdog: https://help.underdogsports.com/en/articles/13780101-pick-em-standard-flex-entry-payouts

## Mathematical correction

Previously a symmetric reference pair 1.91 / 1.91 produced 1/1.91 = 52.356%
for each side. Both sides sum to 104.712%; that is not a probability distribution.
It could manufacture a positive edge against a fair 2.00 target.

For each exact event/player/market/line and complete binary reference book, set
q_i=1/d_i and solve q_0^k + q_1^k=1. Both q_i lie strictly between zero and one;
the sum is continuous and strictly decreasing from two to zero as k goes from
zero to infinity, so the positive root is unique. The power model produces a
coherent binary distribution and allows asymmetric margin allocation. Symmetric
prices return exactly 0.5. Missing counterparts are not invented.

Reference: Clarke, Kovalchik and Ingram, *Adjusting Bookmaker's Odds to Allow for
Overround* (2017), https://www.sciencepg.com/article/10.11648/10026106 . This paper
does not establish performance for our particular player-prop sample.

Remove margin within each book before pooling. Existing reputation weights are
renormalized over eligible complete references; the target is always excluded
and props still require two other books. Those weights remain priors, not fitted
accuracy scores. DFS assigned prices are not valid standalone reference evidence.

As sensitivity analysis, also compute proportional probabilities q_i/sum(q).
EV uses the lower pooled estimate of the two methods. This lower value is a model
sensitivity bound only, not a statistical confidence interval or a guaranteed true
probability. The displayed power estimate is explicitly a model estimate.

For positive-win commission c, target net decimal return is 1+(d-1)(1-c).
EV per unit stake is p * net_return - 1. Integer lines are conditional on decisive
settlement; no push mass or unconditional expected return is inferred.

Main-line proportional consensus remains unchanged; account-specific commission
is applied to target returns, not mistaken for bookmaker reference margin. Back
covers choose by net win return. Per-leg charging is conservative when positions
share a net-commission market: losing stakes can reduce actual commission but
cannot increase it above the isolated winning-leg charge. Cent rounding and
availability still require checking at the venue. This is not an optimal portfolio
netting optimizer. Existing back/lay and middle payoff engines retain their
explicit isolated-position assumptions.

Unknown commissions are null in API output and have an explicit fee_status. Those
quotes remain in the schedule/reference evidence but cannot be EV targets, covers,
middles, or promo inputs. Browser stake calculations and tracker net-odds overrides
preserve modeled commission; displayed raw provider odds remain recognizable.

## Calibration evidence - blocked, not fabricated

User authorized a bounded historical probe. The configured local key successfully
returned historical event IDs (1 credit) but historical player_points was denied:
HTTP 401 HISTORICAL_UNAVAILABLE_ON_FREE_USAGE_PLAN (0 credits). Two calls, one
credit total; reported quota after probe 243 used / 257 remaining. No retry,
provider upgrade, production publication, or collector activation occurred.

Historical props require a paid plan. Historical prices alone do not label player
outcomes: the documented scores endpoint contains team scores, not final player
statistics. Independently verified box scores / prop settlement rules are needed.

Do not label these estimates empirically calibrated. Once historical access is
available, build a predeclared all-eligible-props cohort, not only tracked winners
or positive-EV bets. Capture one fixed pregame horizon; join exact event, player,
stat, line, overtime and settlement rules; exclude unresolved/void/push outcomes
from the decisive model while reporting their counts separately. Split by event
and time, never randomly by opposing side or bookmaker; keep tuning, calibration
and final evaluation periods separate. Fit any recalibration only on the earlier
calibration partition. Evaluate untouched later data per sport/market/horizon with
Brier score, log loss and reliability bins, using event-clustered uncertainty.
Until that exists, no fitted weights, interval coverage or out-of-sample ROI claim.

Offline evaluation command:

    python -m pipelines.validate_prop_calibration --input holdout.jsonl

Each row requires event_id, market, player, line, predicted_at, starts_at,
resolved_at, probability, won (0/1), settlement='decisive', synthetic=false,
outcome_source and frozen model_version. The scorer rejects duplicates and late
forecasts, and reports event counts. Provenance declarations must be independently
audited; a JSON flag does not prove reality. Scoring does not itself certify calibration.

## Validation and rollout

308 backend tests ran: 305 passed, 3 Linux-only lock tests skipped on Windows.
143 frontend tests passed; TypeScript passed. A Next production webpack build
passed. Default Turbopack could not follow the reused dependency junction outside
the isolated build root; the normal VPS build remains required.

Apply the isolated patch to c0032c2, run the backend suite and normal pnpm build
on the VPS before restarting services. No schema or database data migration is
required. Re-run recorded props authority validation with expected power estimates;
do not interpret changed probabilities as a failed retention/replay invariant.
Public HTTPS and .us link behavior stay intact. API key stays absent from VPS.

Open items: paid historical entitlement, independent player outcomes and holdout
calibration; exact BetOpenly fee base; Betfair account/market rate; verified native
fee context for nonlinear contract venues. These are not marked as passed.

## Alternative historical source: The Odds Gap

At the owner's request, downloaded the free September 15-21 sample from
https://theoddsgap.com/data . A passing-yard t1 pilot yielded 24 exactly matched
NFL observations across 13 games after excluding college and unmatched rows.
All retained forecast timestamps preceded kickoff; two outcome labels were
independently spot-checked against official team reports. The supplied vendor
consensus scored Brier 0.2492093325 and log loss 0.6915654477, compared with 0.25
and 0.6931471806 for a constant 50% forecast. This is a small exploratory vendor
benchmark, not calibration or verification of Corner's probabilities.

The export contains consensus props probabilities, not per-book paired props
prices, so Corner's target-excluded weighted forecasts cannot be reconstructed.
No coefficients were fitted or deployed. A broader paid window alone would not
remove that input limitation. Exchange export odds are documented as fee-adjusted;
do not deduct the same fee again. Full pilot evidence is retained separately in
output/research/odds-gap-20261016; this research did not call The Odds API, buy a
subscription, change the confirmed .us links, or enable collection.
