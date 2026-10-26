# Reference policy — October 26, 2026

Version: configured-policy-priors/10-exchange-matrix-2026-10-26.

Positive EV (main, alternate and live supported markets): Pinnacle 45%; Novig,
ProphetX, Polymarket US and Kalshi 35% combined; BetOnline 10%; DraftKings and
FanDuel 10% combined.

Props: FanDuel 35%; Novig 35%; ProphetX and Kalshi 15% combined; Pinnacle and
DraftKings 15% combined. Whenever Novig is not an eligible reference (including
when Novig is the target), use FanDuel 60%, Pinnacle/DraftKings 40% combined.
ProphetX and Kalshi remain secondary in this fallback.

Divide each group among available independent sources. Omit absent groups and
normalize the remaining primary mix. If other eligible books are present, reserve
5% collectively for them and scale the primary mix to 95%. Secondary books share
their pool using the existing lower sport/market priors. With no primary sources,
normalize the available secondary priors; reference-count and feed display gates
still apply. Betfair regional aliases share one source allocation. Betfair props
and DFS remain excluded. Polymarket US uses polymarket_us.

Each source is devigged before pooling. Target exclusion, exact contract matching,
freshness, modeled fees and minimum independent references are unchanged.
Available quotes do not prove exchange liquidity or betting volume. These are
owner-configured policy weights, not empirically fitted accuracy scores.

No collection cadence, provider request, or quota budget changes.
