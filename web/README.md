# The Corner — Next.js / TypeScript frontend

This is the primary frontend. It uses Next.js App Router, React and strict
TypeScript, with the supplied original logo/banner and a responsive red/charcoal
theme. Dependencies are exact-pinned in `package.json` and `pnpm-lock.yaml`.

## Run locally

For the database-backed `/games` route, start the [Spring API](../server/README.md) 
from the repository root with `python -m server.run_local` after building its jar.
The board reads PostgreSQL only. Odds API credits are spent only by the
"Fetch fresh odds" button, served by `python -m pipelines.refresh_service`.

For the betting tools, start the database-backed tools API over stored pre-game odds
(`python -m api` serves a synthetic fixture for demos):

```powershell
.\.venv-api\Scripts\python.exe -m api.run_local --port 8765
```

In another terminal, from `web/`, with Node 20.9+ and pnpm installed:

```powershell
pnpm install --frozen-lockfile --ignore-scripts
$env:NEXT_TELEMETRY_DISABLED = '1'
pnpm dev
```

Open http://127.0.0.1:3000/. Both servers bind to loopback. Stop the foreground
processes with Ctrl+C. To test a production bundle use `pnpm build` then
`pnpm start` instead of `pnpm dev` (stop dev before starting on the same port).

`CORNER_API_ORIGIN` defaults to `http://127.0.0.1:8765`. It is server-only and
restricted to a plain loopback HTTP origin. Browser requests use same-origin
`/api/v1` rewrites. No provider keys, database credentials or `.env` secrets are
needed or imported. Configuration changes require restarting/rebuilding Next.

## Views and boundaries

`/tracker` adds local accounts and private retrospective recordkeeping. Enable
the backend as described in [Personal records](../server/PERSONAL_RECORDS.md).
It does not submit wagers or move money. CLV remains explicitly unavailable.

Routes: `/positive_ev`, `/arbitrage`, `/middle`, `/props`, `/games`, `/promo`.
`/` opens Positive EV. Unknown view routes return 404. `/games` is the odds screen: a sportsbook-by-game grid with Spreads, Moneyline\nand Totals tabs, best-price highlights and sticky headers, fed by the same\nstored quotes and Refresh odds button as the other tools.
The other tools calculate over stored provider quotes under `api.run_local`, and over synthetic fixtures under `python -m api`.

- Typed React cards, filters, sorting and pagination for all six featured markets.
- Exact-contract sportsbook matrix, with back quotes routed into promo conversion.
- Native payoff dialogs, raw decimal inspection and explicit conditional-EV basis.
- `/promo` is a conversion feed: pick the promo type (bonus bet, site credit or
  no-sweat), your sportsbook and the promo value, and every upcoming two-way
  market is ranked by conversion rate against the best cash hedge at the other
  books. The calculator gives the hedge stake and both outcomes. The math is
  client-side estimates in `lib/promo-math.ts`; the exact promo API remains
  available but is not used by this page.
- Signed American odds and USD money formatting, without converting analytical
  strings through floating-point numbers. Decimal input strings remain unchanged
  except the explicitly conservative American minimum-odds conversion.
- Abortable and snapshot-bound requests. Input changes cancel calculations and
  clear results; errors never masquerade as successful empty/zero responses.

`lib/contracts.ts` defines the API boundary; `lib/api.ts` enforces environment,
snapshot, request timeout and paging bounds. React owns rendering and event
handling; the legacy DOM controller is not loaded. The tested exact display and
hedge utilities in `../frontend/format.mjs` and CSS are currently shared source,
not another implementation of the domain math.

The earlier static frontend remains an API regression/reference surface, not
the primary application. No duplicate calculations, new migrations or runtime
grants were introduced.

## Branding and architecture

The supplied square logo is the navigation identity/favicon. The supplied wide
banner is displayed above the tools. Assets remain byte-identical to the
originals and preserve aspect ratios; tests verify their hashes. The talk-show,
waiting-scene and MockUI videos informed the visual review but are not shipped
or autoplayed in the tool screens.

The four-page architecture PDF specifies Next.js/React/TypeScript plus a future
Spring Boot API over the Python/PostgreSQL domain. This slice implements that
frontend choice while preserving the working FastAPI fixture boundary. It does
not claim Spring Boot migration, authentication, real-time transport or a fully
installable/offline PWA. Redis/Kafka/cloud services are not needed for this UI.

This reads stored pre-game quotes only (no live in-play prices); there is no private membership authentication,
production-positive authorization, tracking, CLV, alerts or bet placement. No
service worker caches market quotes as if they were current.

## Verification

```powershell
pnpm typecheck
pnpm test
pnpm format:check
pnpm build
```

Shared exact-format/API regressions run from the repository root:

```powershell
node --test tests/frontend.test.mjs
.\.venv-api\Scripts\python.exe -m unittest discover -s tests -p 'test_product_api.py' -q
```
