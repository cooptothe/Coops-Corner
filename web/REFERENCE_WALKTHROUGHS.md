# User-supplied walkthrough references

- https://www.youtube.com/watch?v=WBiZCFxS2FY
- https://www.youtube.com/watch?v=YgjXHpa8Dbc&t=2534s

Reviewed transcript material and a targeted frame from the second walkthrough.
Its approximately 18:27–22:29 section describes history, P/L breakdowns by
book/sport/league/market, recording a placed bet, and historical price movement.
Around 40:32–43:49 it shows filters and multi-outcome payoff comparisons.
These are product references, not proof of profitability, provider availability
or automatic execution. Do not adopt the risk-free/guaranteed-profit claims.

Preserved constraints: Next.js + TypeScript, Corner branding, American odds, USD,
six featured markets. Fantasy optimization and previously excluded Sharp Money/
Insiders are excluded.

| Area | Actual state |
|---|---|
| Games & Odds | PostgreSQL-backed retained snapshot; no paid auto-refresh |
| Accounts | Local registration/session foundation, not production identity management |
| Tracker | Private manually entered completed-bet history |
| Bankroll | Recorded cash movements and aggregate settled P/L |
| CLV | Pending real closing data and benchmark contract |
| Other calculators | Existing fixture integrations unchanged |
| Wager submission | Not implemented |

This is not a completed OddsJam equivalent. No sportsbook account linking,
automatic placement, live subscription, verified grading, balance sync, email
recovery, MFA or production deployment was added.
