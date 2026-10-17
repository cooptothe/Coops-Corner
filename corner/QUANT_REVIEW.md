# Quantitative review: main lines, props, projections and research context

Reviewed October 17, 2026. User scope: assess every retained prop, including one-sided markets; improve both feeds; keep reference books fixed and add estimated-win-chance filtering. This work neither enables paid collection nor establishes predictive profitability.

## Assessment

The existing implementations are mathematically recognizable market-pricing baselines, not the best possible empirically demonstrated forecasting models. Correct EV arithmetic does not validate its input probability. No universal devig, sportsbook ranking or projection family dominates every sport, market, horizon, limit and settlement rule. Selection must follow point-in-time validation rather than complexity or attractive backtest ROI.

Main production calculations use reputation-weighted proportional no-vig across an explicitly complete outcome set, excluding the betting book. This handles three-way markets including draws and preserves conditional settlement for possible refunds. Props use paired power no-vig with proportional-method sensitivity, then transferred same-event/book overround or explicit unpaired policy assumptions. These are different estimation policies. Keeping either one pending a proper forecast comparison is preferable to silently claiming another method is proven superior.

The 10% central / 20% stressed unpaired policy is not a fitted hold estimate or a guaranteed lower bound. Transferred overround does not identify how a bookmaker allocates margin to a particular longshot. Reference weights are published internal reputation priors, not measured historical precision. Agreement among copying books does not imply independent evidence. Unknown contract fees and DFS lineup payouts remain ineligible as standalone fee-adjusted opportunities.

A lay bet wins when the named selection loses. The main feed's win-chance display/filter now uses 1-p for lay bets; the underlying named-selection probability and lay payoff calculation remain unchanged. Reference books and weights remain fixed by the server pricing policy. Users cannot select or remove pricing references. The estimated-win-chance slider only hides rows below its threshold; it never recalculates probability or EV. Probabilities can still change when underlying quotes or the fixed model inputs change.

## Vendor research: what is actually published

OddsJam describes fair prices based on market quotes and historical book-sharpness backtesting, separately for props and main lines. Its public educational descriptions are not a complete reproducible specification of the production weights, one-sided margin model, training labels or held-out performance. Promotional statements do not establish guarantees. We do not label a guessed implementation as OddsJam's proprietary formula.

Outlier's published Pro presets explicitly describe devig-book selection, market-specific weights, variation limits and fractional Kelly. Its MLB example assigns FanDuel 75, Pinnacle 50 and several other books 25; its NFL example lists a different book set and describes equal weighting. The same article contains some inconsistent explanatory copy, so it is evidence of exposed settings, not an independently validated universal ranking. We do not import these numbers as fitted coefficients for our users. Its research documentation distinguishes implied probability from L5/L10/L20/H2H and season hit rates, and exposes matchup/positional context. These descriptions do not disclose a full player-level generative projection model for us to reproduce.

Our implementation takes the useful transparent controls and context, while keeping historical rates, market-derived probabilities and independent projections distinct. Neither a favorable opponent rank nor a headline gets an invented percentage adjustment.

## Probability and settlement

For a unit back stake, E[profit] = p_win * (decimal_odds-1) * (1-commission) - p_loss. A push returns stake and contributes zero. If probabilities are conditional on decisive settlement, absolute expected return must also account for the decisive probability; paired prices alone do not determine push or void mass. Price-dependent exchange fees, execution quantities, slippage, dead heats, nonrunners and different overtime/participation rules need their actual payoff context. A shared player name/line is not proof that different contracts settle identically.

A single yes price q=1/odds cannot reveal both true probability and margin allocation. Anytime-scorer yes prices across players must not be normalized to 100%: multiple players can score. First-scorer fields can be exclusive, but require complete coverage and a no-scorer outcome under consistent rules. First and last are not the same as anytime. The new competing-hazard research function exposes its independent constant-rate assumption and requires the complete competing field, including opposition. Real playing-time and game-state hazards would be time varying; this function is not a fitted match model.

## Implemented projection baselines

Every one of the 71 current catalog entries receives an explicit model plan and required inputs. This is a coverage map, not a claim that all source data exists. Forty-seven entries have a current game-log mapping for the audited representative supported leagues. Every retained quote is included in a coverage outcome; unknown markets and missing fee contexts are explained rather than quietly declared +EV. The Lab no longer silently truncates its inventory at 2,000 quotes; validated pages reject mixed snapshots or incomplete lists.

- Count outcomes: Gamma-Poisson posterior predictive negative binomial, using a Jeffreys rate prior and up to 40 eligible games. A method-of-moments overdispersed negative-binomial comparison is available when variance exceeds the mean. These account for different distributional assumptions; neither models injuries or proves calibration.
- Signed integer yardage: a discretized Student-t predictive distribution from a normal sampling model with unknown mean/variance, compared against a smoothed empirical threshold model. Negative outcomes are allowed. This is a baseline; mixture/compound opportunity-yardage models are the better next candidates once attempt-level data and role features are available.
- Binary outcomes/milestones: exact eligible event results with a smoothed binary baseline. Double/triple-double logs require all five relevant stat categories, not total points or a sum of categories. Missing components remain missing.
- Anytime count events: evaluate P(count >= 1), with explicit no-line Yes/No contract identity. NHL anytime-goal quotes can now use available goal logs; the research threshold 0.5 is never substituted for a nonexistent sportsbook line in the parlay/tracker contract.
- Longest outcomes: empirical full-game maximum baseline, requiring same-period result and no-attempt settlement review. An eventual opportunity-level maximum model would use the distribution of attempts and gains, not a normal model for individual attempts.
- First/last scorer: explicit competing-risk model plan; actual model function requires complete field rates. Without those inputs the result is needs-context, not a fabricated probability. NFL anytime TD requires complete eligible touchdown components, including applicable return/defensive rules; passing TDs cannot be substituted for the quarterback scoring a TD.
- Quarter props: full-game logs are explicitly rejected as first-quarter evidence. Soccer cards, red cards, pitcher wins, special-team events and other unsupported source mappings remain visible in the coverage plan with their required exact outcomes.

The Lab displays projected mean, modeled win/push probabilities, fee-adjusted return and method comparisons where supported. They are research-only: edge_validated=false and live_feed_eligible=false. The projection spread is sensitivity to assumptions, not a calibrated confidence interval. A high historical hit rate is not a forecast probability. No staking suggestion or parlay joint probability is inferred from these experimental estimates.

## Context to fit with suitable data

Basketball: availability and minutes distribution first, then pace, usage, starters/bench combinations, foul/blowout risk and possession-level rate. Combos require joint covariance. Football: snaps, routes/targets, carries, red-zone/goal-line shares, pass attempts, weather, game script and injury replacements. Baseball: lineup/plate appearances, handedness, park/weather, pitcher arsenal and batter quality; pitcher outs/strikeouts need workload and opponent opportunities. Hockey: ice time, power-play role, shots/xG, line combinations, opposing goalie and pulled-goalie effects. Soccer: minutes/start/substitution probabilities, penalties, shot quality, position and team/opposition scoring intensities.

Use only facts observed before the forecast. Separate a player's possible role scenarios and average over them; do not set an injured player's historical mean to zero or multiply last-five hit rates by an arbitrary matchup factor. Missing news is not evidence of no injury. Existing news/source timestamps, small H2H samples, season/team changes and workload shifts remain displayed. No fitted numerical news or matchup adjustment is claimed.

## Validation and risk

The new model-validation helper requires train cutoff < prediction time <= event start < settlement time, with feature timestamps no later than the prediction. It rejects duplicate predictions and reports event-balanced Brier/log scores and counts; many props in one game are not treated as independent events. Diagnostics alone never authorize a live edge.

Before promotion: acquire verified game/player identities, exact historical odds/line/fees and settlement, archived pregame features and outcomes. Split chronologically by event, tune on validation only, and preserve untouched out-of-time seasons. Compare market consensus, simple historical baselines and candidate projections using log loss, Brier score, reliability plots and calibration slope/intercept. Fit probability calibration on separate folds. Estimate uncertainty with event/date blocks, account for repeated market/line searches, and record all candidate models rather than selecting a lucky ROI maximum. CLV is a useful diagnostic, not a guarantee or a training feature available before the original bet. Profit simulations require executable prices, limits, stale-price handling and fees.

The cached OddsGap player-log sample contains 958 rows for 958 players, one game per player. It cannot train or validate a per-player projection. The previously joined passing-prop subset lacks raw opposing per-book prices and is not a book-weight calibration dataset. Inactive/zero-filled or unverified records need independent checks before training. No numerical predictive accuracy or profitability is claimed from this sample.

For bankroll decisions, optimize a portfolio under uncertain probabilities and correlated outcomes; do not multiply SGP leg marginals. Fractional Kelly is a risk-sizing convention, not a probability-validation method. Expanding longshot coverage increases the need for tail calibration and simultaneous-exposure controls; it does not make big payouts easier or guarantee winning plays. Existing same-game parlays still use the actual sportsbook combined quote for recording.

## Release impact

This is additional model/research scope beyond the launch freeze. Install and verify the transparent filters and research baselines; do not promote projections into the paid +EV feed until out-of-time validation passes. Payments, trial clocks and live collection settings are unchanged. No paid odds calls are made by the coverage audit, display filters or research models.

## Primary sources checked

- Clarke, Kovalchik & Ingram (2017), devig comparisons: https://www.sciencepublishinggroup.com/article/10.11648/j.ajss.20170506.12
- Gneiting & Raftery, proper scoring rules: https://sites.stat.washington.edu/people/raftery/Research/PDF/Gneiting2007jasa.pdf
- Dixon & Coles, Poisson football model: https://academic.oup.com/jrsssc/article-abstract/46/2/265/6990546
- Competing process hazards in hockey: https://arxiv.org/abs/1208.0799
- StatsBomb, expected-goals feature context: https://statsbomb.com/articles/soccer/upgrading-expected-goals/
- Conformal prediction under drift: https://www.stat.berkeley.edu/~ryantibs/papers/nexcp.pdf
- Kelly's original paper: https://www.princeton.edu/~wbialek/rome/refs/kelly_56.pdf
- OddsJam's public methodology description: https://oddsjam.com/betting-education/bible-of-sports-betting
- Outlier's published EV presets: https://help.outlier.bet/en/articles/11908672-how-to-read-use-positive-ev-filter-presets-in-outlier
- Outlier's Prop Finder definitions: https://help.outlier.bet/en/articles/6711738-research-player-propositions-with-outlier-s-prop-finder
- Outlier's matchup interpretation: https://help.outlier.bet/en/articles/8575657-understanding-opposition-rank-in-outlier
- OddsGap historical data/sample description: https://theoddsgap.com/data

## Performance boundaries

Coverage loads only on the first user expansion, not on Lab or feed navigation. Per-player projections are computed on selection; this release adds no background scans or polling. Existing deferred searches and bounded visible result lists remain. Source reads and calculations run outside the API event loop.

Local synthetic in-process measurements with 8,000 quotes: inventory construction median 124.67 ms (7 runs), coverage classification 9.65 ms (7 runs), and 40-game count projection 0.33 ms (30 runs). These exclude network, browser rendering, cold source loads and production contention. They are not an industry-wide performance certification. Production p95 API latency, page interaction and cold/cache-hit timings still require deployed measurement.
