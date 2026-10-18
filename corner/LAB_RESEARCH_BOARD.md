# The Lab: research board and fair-price filters

The Lab is a research browser, not an EV shortlist. Its inventory comes from all eligible collected player-prop quotes, independently of build_bets, reference-book availability, EV sign, projection eligibility or execution-fee coverage. Quotes still need valid player/side/line identities, upcoming games, executable price formatting and fresh source timestamps. No unsupported player stats are fabricated.

The board groups identical event/player/market/side/line offers and shows the best listed price before fees when All books is selected. Choose a sportsbook to inspect its offers. League, Central date, matchup, team-in-matchup, player search, market, side, book and American-odds filters operate on inventory. No fair probability is adjusted by those filters. Player details keep existing game logs, venue/result/H2H/workload splits, news and exact parlay selection controls.

The board displays L5/L10/L20/current-season historical hit rates, with wins/decisive-games and push counts. Hit-rate and minimum-sample filters/sorting use loaded history only, explicitly labeled. Unknown history remains visible by default. Current-season counts use available current-season appearances; they are not a complete-season coverage promise.

Default board reads are cached-only, at most 40 requested identities. Loading missing rates is an explicit user action, at most five contracts per backend request and one bounded visible page per frontend action. Existing free-source cache, single-flight and 240-request/hour limits remain. No odds-provider requests are made by inventory, board filtering, cached rate reads or free research warming.

The previous EV-based shortlist endpoint and UI are removed. Unknown fees no longer block statistical research. Such quotes suppress return/break-even estimates, and are not eligible for direct Lab-to-parlay routing until fees can be modeled; their game logs and hit rates remain available. Existing market fair-probability calculations are unchanged.

Main EV and player-prop feed Min/Max Odds now filter the model's unrounded fair American price. The labels say Min/Max Fair Odds. A shared exact-rational matcher compares probability and American bounds without binary rounding or changing probabilities. Invalid/inverted bounds fail closed with a visible correction message. EV% continues to filter fee-adjusted expected return. Displayed sportsbook prices are unchanged.

## Research references

Props.cash's own publisher overview describes player searches, game/stat trends, historical opponent performance, clear charts and cross-book odds comparison: https://play.google.com/store/apps/details?id=cash.props.app&hl=en

Its official app release notes describe a hit-rate homepage, deeper filtering and player headshots: https://apps.apple.com/us/app/props-cash-prop-pick-finder/id1606752641

Those sources inform the workflow, not a claim of access to proprietary algorithms or paid datasets. The Corner branding and existing source limits remain.
