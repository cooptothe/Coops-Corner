# Closing-line coverage

Every tracked single and parlay is assessed from retained pregame quotes, including settled bets. The tracker refreshes this assessment on load/refocus and once a minute while visible. No provider call is made. Bets without an exact selection/start, missing close, lay liability basis, or unsupported payout receive an explicit unavailable status. Before closing they remain pending.

Numeric CLV = accepted decimal odds × proportional no-vig closing probability − 1. This is a gross price comparison before account fees, not realized return or calibrated predictive accuracy. Integer lines and draw-no-bet are conditional on a decisive settlement. Exact player, market, side and line must match. One-sided scorer quotes without a complete opposite price are unavailable; assumed margins are never substituted for a closing benchmark.

Main-market observations use the latest active eligible per-outcome quote within 180 seconds before kickoff, with both observation and provider timestamps fenced before kickoff. Team totals also require the exact team contract. Props require a complete reference-book pair and a retained scope captured/updated within 180 seconds of kickoff. Scheduler scope versions are retained transactionally in clv_scopes (including empty withdrawals) inside the existing backed-up ledger. Local manual props retain last per-book scopes in the existing latest.json; this is local research data, not the VPS checkpoint source. Pre-upgrade closes cannot be reconstructed if already overwritten.

Parlays store per-leg CLV in their parent record. Combined CLV is unavailable without a true combined closing quote: same-game correlations and joint payout are never inferred from multiplying marginal probabilities. Existing account-database backups include all stored bet CLV records. Full scheduler-ledger backups include the new scope table without changing activation settings.

Historical prices remain historical evidence; these scope versions are never used to revive expired member-feed quotes. Capture cadence and paid API usage are unchanged.
