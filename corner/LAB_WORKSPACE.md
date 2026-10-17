# The Lab workspace

The three-pane research layout follows the user-supplied props.cash interaction guide while preserving The Corner logo, navigation, typography, plum surfaces, burgundy actions and pink focus/selection accents. Native accessible controls and the existing declarative SVG chart avoid adding a charting or styling runtime.

Desktop: league/date/game/player browser, central player/stat/chart analysis, and contextual splits. On smaller displays the splits move below the chart; mobile browsing can collapse independently. Player lists render in bounded batches, search is deferred, and retained odds are loaded without provider calls.

Line, Over/Under, L5/L10/L20, available-season, venue, verified W/L, head-to-head and minimum-workload changes recalculate in memory. Exact pushes are excluded from decisive hit rates and remain visible. Season logs can include all verified available appearances while statistical projection history stays capped at 40 and its baseline at 30. No full-season completeness claim is made.

Bars above the line are green, below it red, and exact pushes neutral; this is independent of the selected betting side. Hover/focus reveals date, opponent, stat and correctly labeled workload. Research lines never alter sportsbook contract identity or probabilities. Teammate lineup splits remain disabled without verified historical availability.

## Local startup fix

The existing trusted quote view scanned approximately 1.16 million observations before the upcoming-market filter and exceeded the local eight-second statement timeout. The query now narrows to eligible outcomes first and uses the same trusted view within an outcome-partitioned lateral join. Quote-state and age conditions remain outside latest-quote selection. No grant, index, data or view changes are required.

Read-only repeatable-read comparison: original 8,287.95 ms; optimized 1,913.11 ms; both returned exactly the same 7,312 rows. These are local measurements, not production latency guarantees. Existing source-cache invalidation and fail-closed scheduled authority remain in place.

The Windows launcher no longer keeps a failed service shell alive with NoExit; it propagates the child exit code so startup failures are detected promptly. A disposable hidden process verified exit-code propagation.

Validation: 175 frontend tests; 120 backend tests; TypeScript and production build passed. Interactive synthetic preview verified line changes, Home splits, and immediate matchup/player filtering. No live collection, billing or trial activation changed.
