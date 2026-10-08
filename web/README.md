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

**Accounts.** The app opens on `/login` (sign in or create an account with a unique username and
a password). Everything else requires a session; signed-out visitors are redirected to `/login`
and returned to the page they wanted. Usernames are 3-24 characters (letters, numbers, `.`, `-`,
`_`), unique ignoring case; passwords are 8-128 characters. Passwords are stored only as salted
scrypt hashes. A session is a signed 7-day JWT in an HttpOnly, SameSite=Strict cookie that page
scripts cannot read; sign out clears it. Repeated failed sign-ins for a username lock it for a few
minutes. Accounts live in the same SQLite file as the ledger and need no Java backend; the signing key is
created at `retained/auth_secret` (or set `CORNER_AUTH_SECRET`, 32+ characters). If you used the
tracker before accounts existed, the first account you create adopts that data.

`/tracker` is the bet tracker and bankroll manager. The refresh service
(`python -m pipelines.refresh_service`) stores each account's ledger in
`retained/tracker.sqlite3` and the page reads and writes it through `/api/refresh/v1/tracker`.
Every query is scoped to the signed-in account, so users never see each other's bets or cash.
It does not submit wagers or move money.

- **Bets**: a KPI ribbon (net P&L with a sparkline, bankroll, ROI and W-L-P record, CLV beat rate,
  open bets), filters (sportsbook, league, status, strategy, search) and a ledger whose rows show
  live progress for open bets (a progress bar for player props and totals, the score otherwise).
  Click a bet to settle it (won, lost, push, void, cash-out), correct it, reopen or delete it.
  When ESPN reports a game final the row offers a suggested result; nothing settles until you click.
- **Bankroll**: balances per sportsbook and a vault, deposits, withdrawals, rebalancing transfers
  and balance adjustments, a running net-bankroll ledger, a bankroll timeline, max and current
  drawdown, 7-day / 30-day / all-time performance, and expected value versus realized profit for
  bets logged with an edge. Kelly sizing (quarter, half or full) is in the log-a-bet drawer and
  can use your tracked bankroll.
- Every tool's **One-click bet** records the play (all legs together) here, with its odds, edge,
  teams and line. Bets saved in the old browser-only log are imported once, as pending manual bets.
- Money is whole cents; balances, the ledger and the charts are derived from your bets and cash
  entries, so edits and deletes cannot leave a total stale. A bonus bet costs no cash and pays
  winnings only; site credit also pays its stake on a win.
- Live progress is polled about every 30 seconds while a game is under way (ESPN public data; NFL,
  NCAAF, NBA, NCAAB, WNBA, MLB and NHL main lines and common player props can be graded; soccer,
  tennis and MMA show status only). It is not a WebSocket feed.
- Closing-line value compares the price you took with the sharp books' last no-vig price at the same
  line before the game started, from the odds ledger. It is only available when a refresh captured
  that close, for moneyline, spread and total bets (not player props or lays), and the ribbon says
  how many bets were measured.
- Back up by copying `retained/tracker.sqlite3` or with **Export backup** on the Bankroll tab.

Routes: `/positive_ev`, `/arbitrage`, `/middle`, `/props`, `/games`, `/promo`, `/tracker`.
`/` opens Positive EV. Unknown view routes return 404. `/games` is the schedule: upcoming games grouped by day (ESPN style, with team
logos), a league filter, and for each game the main line of the spread, total
and moneyline with the best available price on every side and the sportsbook
offering it. Choose which sportsbooks count under "Odds from" (the sharp
reference books are off by default). It reads the same stored quotes and
Refresh odds button as the other tools.
The other tools calculate over stored provider quotes under `api.run_local`, and over synthetic fixtures under `python -m api`.

- Typed React cards, filters, sorting and pagination for all six featured markets.
- Exact-contract sportsbook matrix, with back quotes routed into promo conversion.
- Native payoff dialogs, raw decimal inspection and explicit conditional-EV basis.
- `/promo` is a conversion feed: pick the promo type (bonus bet, site credit,
  risk-free bet or profit boost), your sportsbook and the promo size, and every upcoming two-way
  market is ranked by conversion efficiency against the best cash hedge at the
  other books. The efficiency badge is red below 65%, amber to 75%, lime to 80%
  and emerald from 80%. The calculator drawer switches promo type live and shows
  the hedge stake (with copy), total capital and guaranteed net cash return, and
  warns when the hedge passes your limit or the market is over 30¢ wide. A profit
  boost takes the boost %, the max boosted stake and an optional cap on extra
  winnings, and is graded on return over the cash tied up on both legs. The math
  is client-side estimates in `lib/promo-math.ts`; the exact promo API remains
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
