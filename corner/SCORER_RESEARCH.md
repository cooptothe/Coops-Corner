# Independent scorer research — October 17, 2026

## Implementation

ATD and ATG market keys already existed. A pricing guard skipped scorer markets
before inspecting complete Yes/No references. That guard is removed: two other
eligible references on the exact player/market/line now support automatic pricing
when both sides exist. Different players are never normalized into one market.
No provider call or collection activation is performed.

Rows expose normalized reference weights, highest first. Existing reputation
priors give FanDuel 5 for major US player-prop families, Pinnacle 2, and most other
eligible references 1. Soccer uses FanDuel 4, Pinnacle 2 and Betfair exchange 2.
These are provisional influence settings, not measured sharpness or liquidity.
The target is excluded. Missing references are renormalized. Removed/unsupported
books and DFS prices do not become valid references through weighting.

## Independent derivation

Let q=1/d be a reference's implied Yes probability. With nonnegative margin on
each binary side, q=p+v_yes and q_no=1-p+v_no. Given v_yes+v_no<=H:

`max(0,q-H) <= p <= q`

Both endpoints are attainable under these assumptions. Proportional removal
q/(1+h) and equal allocation q-h/2 pick particular allocations, neither identified
by one price alone. Several players may score, so forcing all scorer prices to
sum to one is invalid. Book weighting does not identify the missing margin.

Pool interval endpoints with normalized weights. For target return D_net after
supported fees, EV endpoints are p_low*D_net-1 and p_high*D_net-1. Assumed or
transferred-margin rows now expose this allocation sensitivity in expandable UI.
The existing headline point EV is unchanged. The range is not a confidence
interval or a guarantee about the true probability. It requires the supplied
margin ceiling and nonnegative per-side vig; price shading may violate these.
An observed maximum on other players is not a proven future ceiling.

## Reproducible stress experiment

Run `python -m pipelines.scorer_study --output scorer-study.json`.

Seed 20261017; 50,000 attempted cases, 46,948 valid binary quote pairs. Ground-truth
p is uniform from .02 to .80; total overround h from .01 to .25; the fraction of
h allocated to Yes is uniform from zero to one. Invalid implied quote pairs are
excluded. Target true EV ranges from -15% to +15%. Every method is given the
true h, more information than a real one-sided quote supplies.

| Method | Probability RMSE | False-positive share of flagged edges |
|---|---:|---:|
| Raw implied | .08582 | 39.23% |
| Proportional removal | .04667 | 27.55% |
| Equal allocation | .04149 | 24.78% |
| Allocation lower endpoint | .08062 | 0% |

The lower endpoint flags 7,463 cases versus 27,094 for proportional removal. Its
zero false positives follow from the assumptions and known ceiling. This is
synthetic sensitivity evidence, not an ATD/ATG backtest, measured accuracy or a
profitability claim. Equal allocation is not established as generally superior.

## Independent scoring-model sensitivity

For expected scoring count lambda, Poisson gives P(N>=1)=1-exp(-lambda).
Gamma-Poisson with dispersion k gives 1-(1+lambda/k)^(-k). At lambda=1 the results
are 63.21% and 50% for k=1. Expected count alone does not determine anytime chance.
These functions are research-only and do not set member feed probabilities.
NFL scored TD, NHL goals and soccer goals require separate fitting. Passing TDs
cannot silently become quarterback scored TDs; appearance, overtime/shootout and
void rules must match the offered contract.

## Data and validation limits

The previously retrieved OddsGap free sample has passing-yard snapshots, vendor
consensus and best prices. It lacks per-book ATD/ATG Yes/No prices. Its 24 joined
NFL passing-yard rows cannot fit scorer margins or rank scorer-reference accuracy.
No historical scorer performance is claimed and no arbitrary automatic margin
default is introduced.

Fit future book weights with shrinkage by sport/market against independently
verified outcomes. Use pregame timestamps, exact settlement mapping and rolling
chronological train/validation/test blocks; keep all players and snapshots from
one game in one block. Freeze weights before test. Compare Brier/log loss,
reliability and fee-adjusted returns against equal weights and current priors.
Report game-block uncertainty. Exclude the offered book from its own benchmark;
never use closing prices or later news to form earlier predictions.

## Sources examined

- OddsJam's exchange article discusses one-sided TD/home-run pricing and exchange
  Yes/No markets, but publishes no exact one-sided formula or numerical weights:
  https://oddsjam.com/betting-education/sports-betting-exchanges-a-necessary-addition-to-the-market
- Provider market definitions:
  https://the-odds-api.com/sports-odds-data/betting-markets.html
- Clarke, Kovalchik and Ingram (2017), “Adjusting Bookmaker's Odds to Allow for
  Overround”: https://www.sciencepg.com/article/10.11648/10026106
- Dixon and Coles (1997), “Modelling Association Football Scores and
  Inefficiencies in the Football Betting Market”, Lancaster University research
  portal. Its team-score model does not calibrate individual scorer probabilities.
- Historical-data inventory: https://theoddsgap.com/data

No proprietary OddsJam formula is asserted or reproduced.
