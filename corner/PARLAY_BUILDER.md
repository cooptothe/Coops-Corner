# Shared cross-game parlay builder

The main-line +EV and props feeds share one account-scoped browser draft. Parlay mode chooses one sportsbook and filters both feeds without replacing the user's saved feed filters. Drafts do not affect bankrolls. The initial limit is 2–8 legs with one leg per game; mixed main-line and prop sources are supported.

Before handoff or recording, Review current odds rereads retained API data. It never calls the paid provider. Missing/started selections block continuation. Changed odds require explicit acceptance; review expires after one minute. The estimated product of leg prices is a cross-game display estimate, not a combined EV or confirmed sportsbook quote.

FanDuel's multi-selection adapter combines the native marketId/selectionId pairs from provider-supplied addToBetslip links into indexed parameters. It requires one destination, validates every pair and rejects missing/duplicate identifiers. Native props IDs are explicitly captured with includeSids; existing main-line captures already retain them, and the tools API exposes the FanDuel IDs embedded in persisted selection URLs. Other books use Copy slip and individual links; the app does not pretend a single-event link transfers a whole parlay. Structural link tests do not confirm that a sportsbook account will accept or price a slip: that confirmation remains at the sportsbook.

Recording requires the user to confirm actual placement, accepted decimal odds, stake and placement time. The tracker creates one ordinary monetary parent wager with strategy parlay and serialized child leg records in parlay_legs. The SQLite column is added automatically when opening an older tracker database. No PostgreSQL migration is required. User scoping, client-key idempotency, exports and existing single bets are preserved. Child legs carry no stake or payout.

The tracker grades child results independently and suggests a parent result. Parent settlement remains explicit. Winning parlays containing pushed or void legs require the sportsbook's actual returned amount, and note edits preserve that amount. Aggregate stake, profit, ROI and bankroll use the parent once. Single-game live grading/CLV are not applied to the aggregate parlay.

Tests cover matching/duplicate rules, persistence, complete-slip parameter assembly, native ID retention, changed/missing prices, idempotent recording, account isolation, child grading, void returns and bankroll accounting. Live sportsbook acceptance needs an authenticated sportsbook check and never places a wager automatically.
