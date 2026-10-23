# App performance audit — October 23, 2026

Reviewed shared shell/authentication, EV, props, arbitrage, middles, schedule, promo, Lab, Tracker, Account, Help, and live paths. Existing snapshot reuse, hidden-tab polling guards, pure pricing caches, indexed quote access, lazy tool imports and virtualized lists remain in place. No provider requests were made during this audit; acquisition cadence, Premium access and quota guards are unchanged.

## Changes

- Moved shared menus, copy controls and Kelly sizing out of full feed modules. Props no longer imports EV or arbitrage feed implementations, and schedule/promo/middles no longer import arbitrage just for small controls. Re-exports keep existing tests/imports compatible. Pricing math is unchanged.
- Avatar updates notify subscribers for the completed name only; unrelated mounted players/teams no longer perform external-store checks for every batch.
- Mobile feed height indexes rebuild on data/measurement/layout changes, with binary search on each scroll. Previously every scroll walked every row. Measured heights and window boundaries remain equivalent.
- Compress retained market GETs at gzip level 3 above 2 KB: tools, quotes, games, props, Lab research and live. Auth, billing, Tracker, settings and write requests bypass this middleware. Existing no-store, auth and expiry behavior is preserved; no shared response cache was added.
- Props status disk reads now run in the thread pool, including the status portion of a bets response. This avoids blocking other requests on the async server event loop.
- Deployment restarts both API and account/refresh services so backend changes actually load.

## Local evidence and limits

Production build and TypeScript passed. 241 frontend tests and 102 backend tests passed, including unchanged-price/pagination checks, auth/live checks, compression round trips, identity/small/private/write bypasses, targeted avatar notifications and equivalent virtual windows.

Loopback fixture API: quote response 29,373 bytes identity vs 1,600 bytes gzip (94.6% smaller); EV 28,061 vs 3,037 (89.2% smaller). Game response below threshold stayed 1,389 bytes. Compared the data fields; per-request metadata can differ. Compression unit tests also compare an identical full response body. These fixture sizes are not production traffic measurements.

10,000-row pure TypeScript benchmark, 2,000 scroll calculations: rebuilding index 343.28 ms, reused index 3.58 ms, identical checksum 720669. This is a local algorithm benchmark, not a browser frame-rate or end-to-end latency claim. Deployment still needs real-device/network observation and VPS timing. No claim of a universal maximum speed or field Core Web Vitals score is made.
