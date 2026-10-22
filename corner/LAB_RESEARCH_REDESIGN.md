# The Lab research workspace

Research reference: props.cash public product page, official app listings and
official newsletter describing game-log charts, filters, matchup context and
odds comparison. The Corner retains its own branding, access gates and data.

Desktop uses a game-slate strip, 350px master list and analytics pane; narrower
desktops move contextual splits below the chart. Phones use Players / Player
analysis views with a collapsed slate and horizontally scrollable market tabs.
Native SVG keeps the chart bundle small; no charting/state/virtualization
dependencies were added. The fixed 44px row virtualizer mounts a bounded
viewport plus overscan. Search is deferred; detail rendering is memoized.

Research includes every collected supported prop, regardless of market EV or
fee eligibility. Main research line is an actual quoted line with the most
distinct bookmaker coverage; opposite sides do not add extra votes. Users can
choose actual saved lines or adjust a clearly marked what-if threshold. Parlay
actions bind the original exact quote, never a synthetic line or probability.

Historical windows: L5/L10/L20/current available season/H2H. Venue, verified
game result, opponent and workload filters recompute locally. Values equal to
the line remain pushes, excluded from decisive hit rates. They are gray in the
chart. Above/below line bars remain green/red regardless of research side;
tooltips name the selected side's actual hit/miss result. Dates progress oldest
to newest. Mobile bars and tick labels scale to available chart width.

Player/team media uses the existing batched, cached resolver with initials on
missing images. Recent-form dots use five verified historical values, never
random or generated outcomes. Board summaries read cached logs only; explicit
Load hit rates warms at most 24 rows in batches of four via free sources. No
Odds API acquisition endpoint, key, market scope or cadence was changed.

With/without teammate splits need per-game participation evidence that the
existing source does not supply; unavailable controls explain that limitation.
No invented injury status, opponent rank, matchup grade, win probability or
predictive edge is presented. Injury/news links and timestamps remain available.

Visual QA uses an isolated local synthetic fixture preview at desktop and
390px phone widths. It does not demonstrate live data coverage or calibrated
prediction accuracy. The production route retains normal authentication.
