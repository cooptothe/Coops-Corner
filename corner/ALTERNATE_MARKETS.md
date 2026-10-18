# Alternate markets and prop tools

Local manual main fetching has no three-event cap. Alternate spreads, totals
and team totals are requested only for upcoming games today in America/Chicago.
Standard additional markets (BTTS, Draw No Bet, team totals) retain later-game
coverage. The base request is up to six credits per league, plus up to twelve
credits per event today or six per later event. Each request checks affordability; no retries
or background paid calls were added. Tennis keys may expand into tournaments.

In Player props, open **Markets to fetch**, select the statistics, and choose
**add alternate lines**. Documented cash alternate markets are also individually
selectable under **Alternate lines**. Existing selections and recommended
defaults are preserved; the existing cost display includes selected alternates.
Availability depends on the sport, event and bookmaker.

The provider catalog was checked against
https://the-odds-api.com/sports-odds-data/betting-markets.html on 2026-10-18.
Unsupported invented suffixes and DFS-only alternate payout markets are excluded.

Fresh retained cash props now join the tools catalog without passing an EV gate.
Exact complementary outcomes support arbitrage and promo conversion; different
lines on the same player/statistic/period support middles. Standard and alternate
responses for the same contract are deduplicated. A one-sided quote is usable
when a real complementary hedge exists; missing opposite prices are never
invented. DFS multipliers are not executable single-bet hedges.

For each distinct player/statistic/line window, middles show the best cross-book
price pair rather than every dominated sportsbook permutation. All quoted
lines participate, all quotes remain available to promo conversion, and the
existing exact payoff calculator still computes pushes, fees and returns.

Player, event, statistic and period remain separate coordinates. Integer lines
include pushes; only integer/half-point lines enter these tools. Exchange fees
must be known. Liquidity and bookmaker settlement equivalence remain unverified,
as for existing main tools; confirm both legs and rules before betting.

The dedicated props EV feed retains its two-reference, fee-adjusted pricing
policy. Main EV receives no prop EV rows from the generic tools calculator.
The Lab and supported result grading use the base statistic for alternates.
Tracked tool legs retain the original provider event/player/prop identity for CLV.

The scheduler's reviewed market scope and event/quota gates are unchanged.
Collection and billing activation remain unchanged. All automated tests use
recorded or synthetic payloads and spend no credits.

Local manual alternates now request only upcoming events on the current America/Chicago calendar day. Standard main and prop markets keep their existing time coverage. Deployed scheduler policy is unchanged. A single main fetch updates all main tools; a prop fetch rebuilds those same tools from captured prop quotes, without another provider request.
