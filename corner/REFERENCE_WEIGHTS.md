# Reference weighting

`reputation-priors/2` assigns relative influence to each complete, eligible book's
proportional no-vig probabilities. These are explicit heuristic choices based on
the supplied reference guide; they are not fitted accuracy scores or verified
liquidity. We normalize over available references after excluding the target.

## Main lines

| Sport family | Pinnacle | Betfair Exchange | Other configured exchanges |
| --- | ---: | ---: | ---: |
| Soccer | 4 | 3 | 0.5 |
| Tennis | 4 | 3 | 0.5 |
| Basketball | 4 | 1 | 0.5 |
| MLB/baseball | 4 | 1 | 0.5 |
| NFL/football | 4 | 1 | 0.5 |
| NHL/hockey | 5 | 1 | 0.5 |
| MMA/boxing | 3 | 1 | 0.5 |

WNBA and sport keys explicitly identifying challengers use equal weights because
the guide does not establish a reliable dominant source there. Unlisted sources
have weight 1 only if already explicitly eligible as references. This does not
turn every recreational book into a reference. Generic calculator callers with
no sport context retain equal weights.

## Player props

FanDuel: 5 for basketball, football, baseball and hockey; 4 for soccer; 2 otherwise.
Pinnacle: 2. Betfair Exchange: 2 for soccer, 1 otherwise.
PrizePicks and Underdog: 0.5. Other configured references, including Novig: 1.

Existing reference-count rules, target exclusion, exact-line matching and full
outcome requirements remain. Soccer main lines allow a single Pinnacle/Betfair
reference; soccer props additionally allow a single FanDuel reference. One-sided
prices are still not converted into no-vig probabilities.

Main EV responses expose each normalized `weight` and `reference_weight_version`.
Props expose `reference_weights` and the same version. The feed reference labels
show rounded percentages; these can differ slightly from a summed 100%.

## Source availability and scope

BetOnline is withdrawn from requests, references, targets and filters.
12 main-line and 14 props books remain within two ten-book billing groups:
up to 6 credits per main league request, 2 per returned prop market/event.

The Odds API's current public bookmaker list does not include Circa,
Bookmaker/CRIS or SBOBET. They are not requested using invented keys. A supported
provider integration is needed before they can participate.

This is current-price EV weighting, not a change to closing-line evaluation.
It does not promote exchanges based on unverified liquidity or time of day.
The timing claims in the guide require a separate limits/depth and timing model;
they are not silently inferred from bookmaker names. Vig removal remains
proportional; the suggested power method is outside this weighting-only change.
