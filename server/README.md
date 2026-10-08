# Database-backed Games & Odds

Spring Boot 4.0.8 / Java 25 supplies the read-only API; Next.js/TypeScript
renders `/games`. This is a local development service, not an installed service
or a production-authorized betting engine. No provider requests occur on reads.

## Run

Build with Java 25 and Maven 3.9+: `mvn -f server/pom.xml package`.
From the repository root, run:

```powershell
.\.venv-api\Scripts\python.exe -m server.run_local
```

The launcher uses existing server-side `DB_CONFIG` to create a randomly named,
temporary SELECT-only login. Java receives that login's secret in its environment,
not command-line arguments or frontend configuration. It binds `127.0.0.1:8080`.
Ctrl+C stops Java and removes the login/grants; it does not remove retained data.
The launcher expects the ignored local Java runtime under `.tools`, or a
`CORNER_JAVA` executable path. It is not a credential provisioning solution for
deployment. Abruptly killing the launcher can leave its temporary login behind;
inspect `corner_board_session_*` roles and revoke only the exact abandoned role.

Alternatively, supply an independently provisioned read-only login via
`CORNER_MARKET_JDBC_URL`, `CORNER_MARKET_DB_USER`, and
`CORNER_MARKET_DB_PASSWORD`, and run the jar directly. Never give the Java
process migration-owner credentials. The login needs CONNECT, schema USAGE,
and SELECT on the fourteen named tables/view in `run_local.py`.

Start Next.js in `web` with `pnpm dev` or `pnpm build` then `pnpm start`.
Open http://127.0.0.1:3000/games. The other tools use the tools API on
8765 (`python -m api.run_local --port 8765`).

## Contract

- `GET /api/market/v1/health`: verifies database access and enforced read-only transaction.
- `GET /api/market/v1/games`: `search`, `market_key`, `offset`, `limit`.
- `GET /api/market/v1/games/{event UUID}/odds`: optional `market_key`.

Markets: h2h, spreads, totals, outrights, h2h_lay, outrights_lay only.
Page limit is 1–100; offset is 0–10000. Board limits are 100 books, 1000
outcomes and 10000 cells; oversized boards fail rather than silently truncate.
Invalid filters/IDs return 400, absent events 404, DB errors 503—not empty data.
Each response is no-store and carries `corner.market_api/1` metadata.

Each request runs in one repeatable-read, enforced read-only transaction.
Separate pages/refreshes are separate snapshots, not a globally frozen browse.
Existing observation dispositions and trusted-current selection determine cells.
Suspensions do not fall back to older active prices. Missing cells are explicit.
Books shown are those with retained featured observations for the event, not
proof of every configured provider book's coverage.

Decimals remain strings. Exact outcome, line, market and back/lay identities are
preserved. The UI formats American odds; source details retain decimal prices,
observation/payload IDs, JSON source pointer and original timestamps.

`fresh` means observed/receipt age <= configured `CORNER_MARKET_MAX_AGE_SECONDS`
(default 120), not proof of current executable availability. Future observation
times or provider update times beyond receipt are invalid. Provider update time
is separately exposed and is not positive phase authority. All responses set
`production_authorized=false`, `availability_verified=false`, phase `unknown`.
The browser advances quote age between reads; refreshing never re-dates evidence.

## Credit protection and retained capture

On 2026-10-03, one deliberate NFL request captured 28 events / 400 observations
from DraftKings, Pinnacle and BetOnline for h2h/spreads/totals. It cost **3 credits**;
the response reported **6 used / 494 remaining**. Raw bytes, SHA-256, request
parameters (without API key), receipt time and quota headers are retained in
`retained/board-capture-20261003/`.

No recurring provider fetch is enabled. The 15-second UI refresh only reads
PostgreSQL. Re-importing the retained capture is quota-free and idempotent:

```powershell
.\.venv-api\Scripts\python.exe -m pipelines.odds_ingestion --ingest retained/board-capture-20261003
```

## User-triggered pre-game refresh

The `/games` page has a **Fetch fresh odds** button. It calls a separate loopback service
that captures h2h/spreads/totals from DraftKings, Pinnacle and BetOnline for 13 leagues
(NFL, NCAAF, NBA, NCAAB, MLB, NHL, MLS, EPL, La Liga, Bundesliga, Serie A, Ligue 1, Champions
League) with `commenceTimeFrom=now` (pre-game only) and ingests each into PostgreSQL. Cost is
3 credits per in-season league (ceiling 39 per click; out-of-season leagues are skipped free).
Leagues run independently; a failed capture stops the run. The page has a league checklist
(All/None); only ticked leagues are requested and the confirm prompt shows the credit ceiling.
Start it from the
repo root (needs `ODDS_API_KEY` and the owner `DB_CONFIG`, so keep it local):

```powershell
.\.venv-api\Scripts\python.exe -m pipelines.refresh_service   # 127.0.0.1:8766
```

Guards: one fetch at a time, 10-minute cooldown (`CORNER_REFRESH_COOLDOWN_SECONDS`),
4 clicks/UTC day (`CORNER_REFRESH_DAILY_CAP`), failed attempts still count, POSTs require
the local UI origin, and state persists in `retained/refresh_state.json`. Each fetch is
retained under `retained/board-refresh-*`. Without the service the button is inert and the
board still reads stored data. The 15-second re-read checkbox is now off by default.

Do not run `--capture` again without an explicit new credit budget. A one-shot
capture is historical market data, not a continuously live feed. No settlement
approval, quote availability, qualification or Opportunity is implied.

## Verification

- Maven: 3 unit tests.
- `python -m acceptance.market_api`: 8 real HTTP/PostgreSQL tests using a disposable
  database and non-owner SELECT-only login, including mutation denial, suspension,
  withdrawal, late commit, precision, provenance, and database failure behavior.
- `pnpm test` in `web`: 13 tests; `pnpm build`: TypeScript and production build.
- Browser: real captured NFL prices, search, market filtering, source details.

Accounts/authentication, tool-to-real-data integration, tracker/bankroll and CLV
remain separate work. Do not expose these loopback development services publicly.
