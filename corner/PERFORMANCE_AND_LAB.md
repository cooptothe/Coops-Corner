# Performance and Lab dashboard — October 17, 2026

## Measured bottleneck and fix

The local app was running `next dev`, and each quote-age label had a separate
one-second timer. On retained odds, the larger bottleneck was cold power devig:
180 repeated high-precision fractional-power iterations per new price pair.

A controlled offline comparison loaded one fixed snapshot (16 events, 5,715
quotes), blocked outbound HTTP and calculated both implementations in one process:

| Calculation | Time | Priced rows |
|---|---:|---:|
| Original cold solver | 37.198 s | 1,709 |
| Safeguarded Decimal Newton solver | 0.701 s | 1,709 |

Every complete output row compared equal. The measured pricing speedup was 53.1x.
An earlier cProfile run took 52.19 s and attributed 51.74 s to the old solver;
profiling overhead means that is not the comparison baseline above. These are
local computation results, not end-to-end browser latency or a guaranteed VPS SLA.

The optimized method retains 60-digit Decimal arithmetic, the same power equation,
existing input limits, symmetric-price shortcut and bounded memoization. It uses
cached logarithms, safeguarded Newton steps and a bisection fallback. Tests compare
against the original solver to 45 decimal places, including extreme valid odds.
No probability model, pricing policy, fee or eligibility rule is changed.

Quote ages share one 15-second display clock, stop while the tab is hidden and
clean up after their last subscriber. Price expiry and eligibility still use the
existing authority checks; this does not cache stale feed data. A test checks that
500 labels share one timer and release it correctly.

For local production-mode responsiveness, stop local services and use
`Start-Corner.cmd -Fast` (or `scripts/start-services.ps1 -Fast`). This builds the
web app before starting services and uses `pnpm start`. Existing local manual
fetching, credentials and environment settings are unchanged. The ordinary
launcher remains available for development. No scheduled collector is enabled.

## The Lab reference adaptation

The user-supplied reference guides an original master-detail research layout:
sticky sport/stat/book/search controls, an autocomplete player search, a compact
selection browser, player/team/matchup context and a detailed research workspace.
No OddsJam proprietary formula, source code, assets or data feed is used.

L5/L10/L20 and H2H use up to 40 already validated historical games. Bar/line chart
switching, research-line edits and hit-rate/average/median calculations run locally
without refetching. H2H uses the adapter's exact matched opponent; missing opponent
context shows no matched history. Pushes are excluded from decisive hit rates.
The source history is bounded and may span seasons; it is not called a full season.

The pink target line, hit/miss/push coloring and hover/keyboard result labels make
the chart readable. Actual retained quotes at the exact event/player/market/line
appear below, with best listed prices per side highlighted. That label is not
best fee-adjusted EV. Selecting another actual offer preserves sportsbook-bound
parlay handling. A what-if research line never becomes an invented bet or changes
the selected parlay leg. No quote at a research line yields an explicit empty state.

Existing methodology, news and detailed evidence remain available. Loaded-history
interactions do not request stats repeatedly; initial research may still wait on
an uncached external free source. Responsive CSS and static rendering are checked;
desktop/phone visual and interaction acceptance remains required after deployment.

## Acceptance

1. Restart both Python services so they load the new solver; hot-reloading web
   assets alone does not update Python code. Use local Fast mode or VPS production.
2. Open props after a new retained capture. Review matching prices and EV before
   and after; there should be no numerical change from this optimization.
3. Open The Lab, search/filter, choose a player and switch L5/L10/L20/H2H, chart
   style and research line. Confirm these interactions do not trigger new requests.
4. Compare actual sportsbook quotes and build a parlay from those offers. A what-if
   line must not alter a recorded selection. Test keyboard navigation and phone width.
5. Keep existing beta collection and payment activation gates unchanged.
