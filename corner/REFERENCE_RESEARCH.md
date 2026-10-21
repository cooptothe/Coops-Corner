# All-book references: research and policy, October 21, 2026

Both the main EV feed (including alternates) and props feed now admit every
supported book with eligible, exact matching prices. Targets never reference
themselves. Legacy reference-list environment settings do not narrow production
consensus. Explicit calculator/test inputs remain supported. User display
filters never change reference selection. No new acquisition or provider calls.

## Evidence and limits

Outlier publishes NBA props ratios of FanDuel 100 vs Pinnacle/DraftKings/Caesars
25, MLB 75/50/25, and equal NFL anchor weights for FanDuel/Pinnacle/BetOnline.
These are vendor strategy presets, not an independently validated accuracy
dataset. Its multi-book guide also includes BetOnline for NBA props.
Sources: https://help.outlier.bet/en/articles/11908672-how-to-read-use-positive-ev-filter-presets-in-outlier
https://help.outlier.bet/en/articles/11011706-use-multi-book-devigs-and-custom-weighting-to-increase-your-roi

Pinnacle describes a high-limit, low-margin model. Circa describes using bettor
information and market liquidity to set limits. These support market-making
reputation, not a precise statistical accuracy ratio for every sport or prop.
https://www.pinnacle.com/betting-resources/en/educational/why-pinnacle-offers-higher-betting-limits-than-other-sportsbooks
https://www.circasports.com/blog/art-of-setting-sports-betting-limits

Exchange price quality depends on available liquidity, not simply the exchange
label. The feed does not verify depth for every quote. Betfair's own screen
guide distinguishes odds from available money:
https://betting.betfair.com/how-to-use-betfair-exchange/beginner-guides/reading-the-betfair-screen-010819-51.html

No reliable first-party outcome study was found establishing theScore/Bovada as
the best NHL prop source, BetOnline as the best MLB source, or a definitive
winner for soccer scorers/shots/assists. Internet assertions are not treated as
verified per-market rankings. Circa/BookMaker appear in external research but
are not silently added to our acquisition plan or assumed to be API coverage.

## Implemented relative policy weights

Numbers are policy priors; no claim that a weight of four is four times as
accurate. Weighting by sport/market is distinct from empirical calibration.

| Context | Higher influence | Remaining eligible sources |
|---|---|---|
| Main NFL/NBA/MLB | Pinnacle 4 | Other cash books 1; thin/unverified exchanges 0.5 |
| Main NHL | Pinnacle 5 | Other cash books 1; thin/unverified exchanges 0.5 |
| Main soccer/tennis | Pinnacle 4, Betfair 3 | Other cash books 1; other exchanges 0.5 |
| Alternate/team total/BTTS/DNB | Main sport prior; Betfair capped at 1 | No assumed main-line exchange liquidity |
| NBA props | FanDuel 4; Pinnacle/DraftKings/Caesars/BetOnline 1 | Other eligible books/exchanges 0.5 |
| MLB props | FanDuel 3, Pinnacle 2; DK/Caesars/BetOnline 1 | Other eligible books/exchanges 0.5 |
| NFL props | FanDuel/Pinnacle/BetOnline 2; DK/Caesars 1 | Other eligible books/exchanges 0.5 |
| NHL/soccer/WNBA/other props | Cash books 1; no evidenced winner asserted | Exchanges 0.5 |
| Main WNBA/challengers | Cash books/Betfair 1 | Other exchanges 0.5 |
| Main MMA/boxing | Pinnacle 3 | Other cash books/Betfair 1; other exchanges 0.5 |

MLB pitcher/batter submarkets, ATD/ATG, points/rebounds/assists and alternate
prop lines receive the relevant league prop prior. We do not fabricate distinct
stat-specific rankings without evidence. Supported unexpected cash sources use
the documented baseline. DFS remains excluded under the owner's prior policy.

For each target: match contract, player, line and settlement, exclude target,
remove each reference's vig, then normalize weights over available eligible
sources. Main EV remains weighted proportional devig; props retain power and
proportional sensitivity and labeled one-sided margin assumptions. At least
two other reference sources are required for props; the existing selected
single-anchor soccer-main exception is unchanged. Missing opposite sides do
not magically become a no-vig pair. Known regional Betfair aliases count as one
source and split their influence. Shared vendors/other unknown correlations
are not claimed to be empirically independent.

Positive weighted consensus EV is an estimate, not proof of profitable outcomes
or a promise of more wins. Increasing retail participation can dilute an anchor
or move probabilities; this owner-requested policy intentionally changes the
reference population. Historical holdout calibration and CLV monitoring remain
separate research tasks, not established by these online sources.

No API books, market keys, intervals, quotas, budget pools, ledger accounting,
checkout gates, or family invitations change. Bounded in-memory prior caching
avoids repeated parsing; no news/stats/network lookup occurs on feed requests.
