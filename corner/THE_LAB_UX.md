# The Lab and member experience review — October 17, 2026

## What changed

The Lab lives at `/lab`, available from workspace navigation and personal-page
navigation. Compact Trends links in player-prop rows open the exact retained
selection. Research no longer expands inside the props feed.

Members search players, teams or markets and filter by sport and sportsbook.
Selection cards show American odds, matchup and Central-time event dates. Cards
load in batches of 24. Hit-rate windows, matchup context and news remain visible;
technical methodology and detailed evidence are expandable. Selecting a player
moves keyboard focus to the completed research report.

The existing parlay builder is available in The Lab. It uses retained target
prices, including one-sided quotes, and enforces the existing same-book,
cross-game and maximum-leg rules. Its price-review step reads current retained
Lab contracts, detects withdrawals and requires the existing confirmation for
changed prices. Historical hit rates are not multiplied into a parlay probability.

The UI review covered shared navigation, login, account settings, membership
preview, games, EV, arbitrage, middles, props, promo tools, tracker and parlay
components. Existing responsive layouts, focus handling, persisted filters and
financial calculations were preserved. Concrete cross-app fixes include readable
connection errors, support links for account recovery, membership-load timeout
and retry, and consistent missing-page and unexpected-page-error recovery.

## Verification and limits

- 154 frontend tests pass, including exact Lab contract binding, date formatting,
  changed-price review and withdrawal detection. Existing link safety, American
  odds entry, calculator math, tracker accounting and settings tests pass.
- TypeScript and the production webpack build pass, including the `/lab` route.
- 23 targeted Trends backend tests pass. The combined Trends, accounts, props,
  scheduled-only policy and billing-preparation regression run passes 118 tests.
- No odds-provider calls, payment activation, live-worker activation or deployment.
- Browser visual/interaction acceptance is still required: the browser tool could
  not connect to the isolated local preview. Responsive CSS and static-render
  checks are not a substitute for real-device acceptance.

## Staging acceptance after deployment

1. Sign in as an invited member; open The Lab from navigation and from a prop row.
   Verify the row shortcut selects the correct player, line, side and book.
2. Search and filter, load more cards, inspect a player report, expand evidence,
   follow a source link and check the event/date labels.
3. Repeat at phone width and with keyboard navigation. Check the compact row link,
   report focus, filter controls, history-table scrolling and parlay panel.
4. Select a parlay book, add cross-game legs and review prices. A changed price
   requires confirmation; a withdrawn selection blocks handoff. Research-only
   percentages never become an implied parlay win probability.
5. Visit login, account, games, each feed and tracker. Verify empty/loading/error
   states and the existing saved preferences. Test membership Retry during a
   simulated service failure. Keep manual fetching disabled in deployed beta.

## Release position

These changes complete implementation for this UI scope, subject to staging
acceptance. The project is behind its original feature-freeze plan. Paid-beta
launch still requires two-day trial enforcement, verified crypto-payment access,
supervised live collection/quota reconciliation and final member acceptance.
October 20 is conditional, not an assured launch date. Automated offserver backup
delivery remains a deferred operational item.
