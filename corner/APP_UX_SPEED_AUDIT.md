# App UX and speed audit — October 22, 2026

## Props failure
Switching to Worst case could crash the route because Decimal zero EV was emitted as `0E-12` and the exact-decimal sorter rejects exponents. The backend now emits plain decimals; the browser boundary also expands exponent strings exactly, validates rows, and isolates invalid/duplicate rows with a visible notice. Empty valid feeds remain empty feeds; service errors remain errors. Probability calculations, reference weights and positive-edge eligibility are unchanged.

Regression coverage exercises real backend comparison output and the browser selection/sort/eligibility path. The actual Props component was reviewed with 30 synthetic rows: selecting Worst case produced zero matches and the normal empty-state message without the route error.

## Runtime changes
- Tool modules load on demand. Shared loading/error UI and the live switch are independent leaf modules, removing feed/workspace import cycles.
- Unchanged snapshots avoid redundant data reconstruction. Account changes invalidate shared in-memory page requests.
- Headshot/logo requests are deduplicated while pending and limited to three concurrent batches.
- Schedule countdowns share one visibility-aware clock. Live and tracker reads cannot overlap their own polling requests.
- Search input remains immediate while expensive list filtering can be deferred.
- Mobile navigation brings the active tool into view. Mobile form sizing, Lab touch targets and bounded parlay dialogs use the existing brand styles.

## Evidence and limits
230 frontend tests and 102 relevant backend tests passed; production TypeScript/build passed. Responsive review used actual components with synthetic, non-paying data at 320/390px, Lab at 768px, and EV at 1280px. EV, Props, Arb, Middles, Schedule, Promo, Lab analysis, Tracker, bet drawer, Bankroll and Account had no page-wide horizontal overflow in the reviewed mobile states; login/signup were also reviewed at 320px. This is not a physical-device or production-data certification.

The production manifest's deduplicated Workspace + root AuthProvider entry chunks fell from 273,910 to approximately 147,491 raw bytes (46% reduction). This excludes other runtime/on-demand chunks and is not a measured network-transfer or page-load improvement.

The isolated Windows 15-member/three-round HTTP rehearsal did NOT meet the additional 750ms p95 target: capabilities measured 754.08ms; the remaining five routes measured 474.06–666.45ms. A run concurrent with a build was substantially slower. A single-member rehearsal measured 46–70ms p95. These results do not isolate the concurrency bottleneck or certify VPS/public-proxy performance. Auth denial, revocation and private no-store checks passed. Retain the stricter target and measure saved odds on the VPS before claiming it is met; do not weaken authentication or raise the target to hide a failure.

No paid provider calls, wallet transfers or production account changes were made during this audit. Provider cadence, quota reserve and membership rules are unchanged. Deployment remains required. Field LCP/INP/CLS and real iPhone Safari performance remain unverified by these local checks.
