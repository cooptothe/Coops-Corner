# Coop's Corner

![Coop's Corner](web/public/assets/corner-banner.png)

A local, pre-game sports betting toolkit: **+EV**, **arbitrage**, **middles**,
a **promo converter**, an upcoming-games **schedule** with the best lines, and a **bet
tracker with bankroll management**, all running
over stored pre-game odds from [The Odds API](https://the-odds-api.com/).

Odds API credits are spent only when you press **Refresh odds** (which requires being signed in).
Nothing polls the provider in the background. Everything binds to loopback. Each person has their
own account (username and password) and private bet tracker; see [web/README.md](web/README.md#views-and-boundaries).

## Architecture

```
The Odds API --> pipelines/ (refresh service :8766) --> PostgreSQL
                                                          |
                    api/ tools API :8765 <----------------+
                    server/ Spring Boot :8080 (read-only /games board)
                              |
                         web/ Next.js :3000
```

| Path | Purpose |
|------|---------|
| `web/` | Next.js / TypeScript frontend ([guide](web/README.md)) |
| `api/` | FastAPI tools API over stored odds ([guide](api/README.md)) |
| `server/` | Spring Boot read-only market API ([guide](server/README.md)) |
| `pipelines/` | `refresh_service.py` (credit-aware refresh, props, media and the local bet tracker) and `odds_ingestion.py` |
| `corner/` | Canonical domain model, calculators and ledgers ([docs](corner/)) |
| `db/` | `schema.sql`, migrations ([guide](db/migrations/README.md)) and `insert.py` |
| `frontend/` | Shared formatting/hedge utilities and brand assets used by `web/` |
| `fixtures/` | Synthetic and captured sample payloads for tests and demos |
| `retained/` | Raw captures written by the refresh service |
| `acceptance/`, `source-approval/` | Deployment-acceptance harness and source dossiers ([guide](acceptance/README.md)) |

## Leagues

NFL, NCAAF, NBA, WNBA, NCAAB (men and women), MLB, NHL, MMA, ATP and WTA tennis
(active tournaments are discovered automatically), MLS, Premier League, La Liga,
Bundesliga, Serie A, Ligue 1 and Champions League.

A refresh costs 3 credits per in-season league. Out-of-season leagues are checked
against the free `/sports` catalog first and are not charged. The refresh service
enforces a cooldown (`CORNER_REFRESH_COOLDOWN_SECONDS`, default 30) and a daily cap
(`CORNER_REFRESH_DAILY_CAP`, default 50).

## Setup

Requirements: Python 3.12+, PostgreSQL 18, Node 20.9+ with pnpm, and Java 25 +
Maven 3.9+ (only for the `/games` Spring service).

1. Create `.env` in the repository root:

   ```
   ODDS_API_KEY=...
   DB_HOST=localhost
   DB_PORT=5432
   DB_NAME=odds_data_pipeline
   DB_USER=...
   DB_PASSWORD=...
   ```

2. Create the database from `db/schema.sql`, then apply the migrations in
   `db/migrations/` in order (see the [migration guide](db/migrations/README.md)).
3. Install Python dependencies: `pip install -r requirements.txt -r requirements-api.txt`
   (a `.venv-api` virtual environment is used below).
4. In `web/`: `pnpm install --frozen-lockfile --ignore-scripts`.

## Run

Start each process in its own terminal and stop it with Ctrl+C.

```powershell
# 1. Tools API (stored odds, no provider calls)
.\.venv-api\Scripts\python.exe -m api.run_local --port 8765

# 2. Refresh service (spends credits only when asked)
.\.venv-api\Scripts\python.exe -m pipelines.refresh_service

# 3. Frontend (the first account you create at /login adopts any existing tracker data)
cd web; pnpm dev

# Forgot a password? The person running the app resets it (there is no email):
#   .\.venv-api\Scripts\python.exe -m pipelines.accounts_admin reset-password USERNAME

# 4. Optional: Spring Boot service for the /games board (build the jar first)
.\.venv-api\Scripts\python.exe -m server.run_local
```

Open http://127.0.0.1:3000/ and create an account. After **Refresh odds** completes, the web app asks the
tools API to reload its snapshot (`POST /api/v1/catalog/reload`); the snapshot is
otherwise built once at startup. If you change `web/next.config.ts`, restart `pnpm dev`.

## Tools

| Route | Tool |
|-------|------|
| `/positive_ev` | +EV bets with no-vig fair probabilities from sharp books and uncapped Kelly stakes |
| `/arbitrage` | Two-way arbitrage only (no three-way outcomes) |
| `/middle` | Spread and total middles with window and EV |
| `/props` | Player prop +EV bets against the sharp books, with the Kelly calculator |
| `/promo` | Bonus bet, site credit, risk-free bet and profit boost conversion with a stake calculator |
| `/games` | Schedule: upcoming games by day, with the best main-line spread, total and moneyline |
| `/login` | Sign in or create an account (username + password); `/account` changes your password |
| `/tracker` | Bet tracker and bankroll: ledger with live progress, per-book balances, Kelly sizing, CLV and history charts ([details](web/README.md#views-and-boundaries)) |

Feeds can be sorted by EV, win probability, start time and other measures relevant
to each tool. Sharp reference books are Pinnacle, Novig and BetOnline; the rest of
the US sportsbooks are treated as recreational offers.

## Tests

```powershell
.\.venv-api\Scripts\python.exe -m unittest discover tests
cd web; pnpm typecheck; pnpm test
```

Some database-backed tests are skipped unless a disposable PostgreSQL database is
configured.

## Domain documentation

The `corner/` directory documents the canonical schema, conditional EV,
assessment/channel/work ledgers, reconciliation, polling, deployment and
operability contracts. Start with [corner/FEATURED_BACKEND.md](corner/FEATURED_BACKEND.md)
and [corner/FEATURED_PAYOFFS.md](corner/FEATURED_PAYOFFS.md). Production authority is
disabled; this project is not a bet-placement system.

## License

See [LICENSE](LICENSE).