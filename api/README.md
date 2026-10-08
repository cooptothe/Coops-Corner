# The Corner: tools API

This is a runnable local HTTP API for frontend development. It serves three
synthetic events (NBA-style basketball, three-way soccer and an outright
tournament), 60 linked quotes, betting-tool results and a promo calculator.
All calculations call the existing pure featured-market backend.

**No database, `.env`, credentials, provider requests, background workers or
production authorization are involved.** The API cannot be switched to live
mode. It is not an authenticated/public deployment and must remain local.

## Run

From the repository root, using the already-created API environment:

```powershell
.\.venv-api\Scripts\python.exe -m api --port 8000
```

The foreground process listens only on `127.0.0.1`. Stop it with Ctrl+C. Nothing
is installed as a Windows service. The launcher does not accept a public host or
a live-mode flag. Do not deploy the ASGI api with an externally bound server.

- Primary frontend: Next.js on http://127.0.0.1:3000/ (see [UI guide](../web/README.md);
  its default API upstream uses port 8765).
- Legacy static reference: http://127.0.0.1:8000/ (see [legacy guide](../frontend/README.md))
- Interactive endpoint documentation: http://127.0.0.1:8000/docs
- Machine-readable contract: http://127.0.0.1:8000/openapi.json
- Readiness: http://127.0.0.1:8000/api/v1/health

For a fresh checkout/environment:

```powershell
python -m venv .venv-api
.\.venv-api\Scripts\python.exe -m iii install -r requirements-api.txt
.\.venv-api\Scripts\python.exe -m api --port 8000
```

API dependencies are separate from `requirements.txt`; a fresh API-only environment
does not require PostgreSQL. This workspace's API environment inherits the existing
backend packages to allow the combined regression suite. No global packages were
changed. The environment is ignored by Git.

## Endpoints

| Method | Path | Response data |
| --- | --- | --- |
| GET | `/api/v1/health` | Fixture readiness, explicitly not DB/live readiness |
| GET | `/api/v1/capabilities` | Six-market allowlist, tools, books, sports, calculation defaults, unsupported features |
| GET | `/api/v1/games` | Paginated games/tournaments |
| GET | `/api/v1/games/{game_id}` | One event with participants, scope and market keys |
| GET | `/api/v1/games/{game_id}/odds` | Paginated exact-contract quote rows |
| GET | `/api/v1/quotes` | The same quote rows for every game, in large pages (`limit` up to 1000, `offset` up to 100000); the UI loads a snapshot with this instead of one request per game |
| GET | `/api/v1/tools/positive_ev` | Positive conditional-EV rows |
| GET | `/api/v1/tools/arbitrage` | Positive decisive back-cover and back/lay results |
| GET | `/api/v1/tools/low_hold` | Back-cover and back/lay results meeting a modeled-loss bound |
| GET | `/api/v1/tools/middle` | Cross-line middle payoff tables |
| POST | `/api/v1/calculators/promo` | Stateless calculation using selected fixture quote IDs and explicit promo terms |

The odds board is flat and paginated. Group by `contract_id`, then `selection_id`,
then book in the frontend. A quote carries its market direction, exact line and
selection label. Do not group solely by display name: two lines or back/lay
directions are not interchangeable.

## Response contract

Successful responses have `{meta, data}`. Lists put
`{items, total, offset, limit, next_offset}` inside `data`. Errors have
`{meta, error: {code, message, fields}}`, not empty successful results.

Every data/error envelope identifies:

- `format = corner.product_api/1`;
- `data_mode = fixture`;
- stable `snapshot_id` covering the fixture **and calculated outputs**;
- original `captured_at`, fixed `reference_clock_at`, actual response `served_at`;
- `production_authorized = false`, `availability_verified = false`;
- explicit synthetic-data and fixture-clock warnings.

The capture clock is intentionally fixed in 2030. Future start times do not
establish pregame status: game `phase` remains `unknown`. Do not present these
quotes as live, recently refreshed or bettable. Original `observed_at` does not
change on repeated HTTP reads. `provider_updated_at` is null because these are
synthetic quotes, not real provider responses.

Money, prices, points, probabilities and ratios are **JSON decimal strings**.
Counts, offsets and score-range integer bounds are JSON integers. Treat ratios
as ratios: `"0.03"` displays as 3%, not 0.03%. Do not convert values to binary
floats before sending calculator requests. Timestamps are offset-aware UTC.

Tool rows share ID, game, contract, sportsbook/quote references, oldest observation
time and numeric summary columns. `kind` discriminates the typed calculation
payload in OpenAPI. Follow `quote_ids` to the odds board for source display.
IDs are deterministic presentation/calculation identities, **not** persisted
Opportunity IDs, WorkRequest keys or a durable idempotency API.

## Filtering, sorting and paging

All list routes accept `offset` (0–10000), `limit` (1–100, default 25; `/api/v1/quotes` allows `limit` 1–1000 and `offset` 0–100000),
optional `snapshot_id`, `sort`, and `descending` (default false).

| List | Filters | Sort keys |
| --- | --- | --- |
| Games | `sport_key`, case-insensitive `search`, `market_key` | `starts_at` (default), `name`, `id` |
| Odds | `market_key`, `sportsbook_id`, `contract_id` | `id` (default), `decimal_odds`, `observed_at` |
| Tools | `game_id`, `sport_key`, `market_key`, `sportsbook_id` | `id` (default), `conditional_ev_ratio`, `minimum_profit`, `capital_required` |

`minimum_ev_ratio` applies to positive EV only (default `0`; the underlying list
already excludes zero/negative EV). `maximum_loss_ratio` applies to low hold only
(default `0.01`, range 0–1). For low hold, the test is modeled worst loss divided
by the calculation's capital requirement, not overround. Arbitrage uses positive
**decisive** profit; a common refund can still have zero profit.

`conditional_ev_ratio` sorting is available only for +EV;
`minimum_profit` sorting is unavailable for +EV. Other inapplicable nondefault
filters, unknown query fields, duplicate query parameters and unsupported market
keys return 422 instead of being silently ignored on list routes. Numeric sorts
use Decimal, never lexicographic string ordering. Equal values use stable row-ID
tie-breaks; nulls sort last.

`sportsbook_id` matches any book participating in the row, including a reference
book in an EV result. The response retains the exact target/reference identities
so the frontend need not guess which role that book played.

Carry the response's `snapshot_id` onto subsequent list pages. A changed snapshot
returns 409 `snapshot_changed`; reload page zero. Omitting this optional parameter
requests the currently loaded fixture. Empty pages retain the filtered total and
return `next_offset = null`.

```powershell
$base = 'http://127.0.0.1:8000/api/v1'
$games = Invoke-RestMethod "$base/games?sport_key=basketball_nba"
$board = Invoke-RestMethod "$base/games/demo-nba/odds?limit=100"
$ev = Invoke-RestMethod "$base/tools/positive_ev?game_id=demo-nba&sort=conditional_ev_ratio&descending=true"
$middles = Invoke-RestMethod "$base/tools/middle?game_id=demo-nba"
```

Fixed list calculations use 100-unit EV/back-lay stakes, 200-unit cover budgets,
100 units per middle leg and .01 stake increments. These defaults are exposed
by capabilities. They are not bankroll recommendations. Middle expected profit
remains null: the API does not invent a scoring probability distribution.

## Promo calculation example

Request the board first, then bind exact quotes. A matching `snapshot_id` is
**required** for this POST. No prices or authorization overrides are accepted.

```powershell
$base = 'http://127.0.0.1:8000/api/v1'
$board = Invoke-RestMethod "$base/games/demo-nba/odds?limit=100"
$promo = $board.data.items | Where-Object {
    $_.contract_id -eq 'nba-h2h' -and $_.sportsbook_id -eq 'demo_target' -and $_.selection_id -eq 'home'
}
$hedge = $board.data.items | Where-Object {
    $_.contract_id -eq 'nba-h2h' -and $_.market_key -eq 'h2h_lay' -and $_.selection_id -eq 'home'
}
$command = @{
    snapshot_id = $board.meta.snapshot_id
    contract_id = 'nba-h2h'
    promo_quote_id = $promo.id
    hedge_quote_id = $hedge.id
    hedge_type = 'lay'
    stake_increment = '0.01'
    maximum_lay_liability = '500'
    terms = @{
        terms_id = 'fixture:user-terms/1'
        kind = 'bonus_stake_not_returned'
        face_value = '100'
        eligible_stake_cap = '100'
        minimum_decimal_odds = '1.5'
        loss_refund_cap = '0'
        eligibility_evidence_id = 'fixture:eligibility'
        bonus_restored_on_void = $true
    }
}
$body = $command | ConvertTo-Json -Depth 6
Invoke-RestMethod "$base/calculators/promo" -Method Post -ContentType 'application/json' -Body $body
```

The alternative `hedge_type = opposite_back` requires a different selection in
the same complete two-way contract. A single other outcome cannot hedge a draw
market or multi-entrant field. `maximum_hedge_stake` applies to either hedge type;
`maximum_lay_liability` is rejected for opposite-back hedges.

Supported promo kinds:

- `bonus_stake_not_returned`
- `bonus_stake_returned_as_cash`
- `loss_refund_cash`
- `loss_refund_bonus`

Terms identify caller-supplied assumptions, not verified eligibility. Returned
noncash token face is never added to cash profit. Promo requests neither persist
records nor place bets. Identical requests produce identical `data` and result
IDs; only response metadata such as `served_at` can differ.

## Local transport and errors

- CORS allows only localhost/127.0.0.1 on frontend ports 3000 and 5173 by default,
  without credentials or wildcard origins. An explicitly supplied local origin
  can be configured through `create_app(cors_origins=(...))`.
- Local Host checks reduce DNS-rebinding exposure; this is not authentication.
- JSON bodies are limited to 16 KiB and a ten-second total body-read deadline.
  Queries are limited to 2048 bytes. Compressed bodies are not accepted.
- Invalid/duplicate-field/nonfinite JSON: 400. Missing resource: 404. Snapshot
  conflict: 409. Oversized body: 413. Unsupported content type: 415. Invalid
  request or calculation: 422. Unexpected failure: generic 500, not a zero result.
- Decimal inputs must be strings without exponents, at most 12 fractional places;
  domain calculators enforce their value bounds, odds minimums and stake grid.
- Data responses use `Cache-Control: no-store`. No request-body access logging or
  internal exception text is returned. Standard framework CORS preflight handling
  is separate from the data/error envelope contract.

## Tests and boundaries

```powershell
.\.venv-api\Scripts\python.exe -m unittest discover -s tests -p 'test_product_api.py' -v
```

38 API checks pass, including static-asset/repository isolation and real temporary loopback startup/request/termination,
OpenAPI generation, source-quote linking, precision, pagination, filters, errors,
snapshot conflicts, concurrent promo requests, fixture isolation and no mutations.
The temporary-server test proves startup and cleanup, not Windows SCM graceful
shutdown or production supervision. Existing host acceptance remains separate.

Combined offline regression in this environment: **346 passed, 359 skipped**
(705 discovered). Skipped DB tests are not counted as passed. The API test module
is optional and skips if the API dependencies are not installed. The pinned
Starlette release currently emits a non-failing HTTPX TestClient deprecation
warning; the runtime API and test assertions still pass.

This tools API has no tracker/bankroll endpoints (the tracker lives in the local refresh
service), no historical movement, live ingestion or broader persisted-engine/worker
integration in this slice. No existing engine,
database schema, credentials or production approval has been changed.

Framework references: [response models](https://fastapi.tiangolo.com/tutorial/response-model/),
[testing](https://fastapi.tiangolo.com/tutorial/testing/),
[CORS](https://fastapi.tiangolo.com/tutorial/cors/).

## Database-backed tools (stored pre-game odds)

`python -m api.run_local --port 8765` serves the same `/api/v1/*` contract from retained PostgreSQL quotes instead of the fixture. It creates an ephemeral SELECT-only login (dropped on Ctrl+C), makes no provider requests and never polls. Prices are only as fresh as the last "Fetch fresh odds" click in the Stored Odds view.

- Responses carry `meta.data_mode = "database"`, `x-corner-data-mode: database`, quote `evidence_kind = "retained_provider_quote"` and warnings stating the quotes are not live and rule equivalence is assumed.
- Inputs: trusted, `active` quotes for `moneyline`/`spread`/`total` full-game markets on events that have not started, observed within `CORNER_TOOLS_MAX_AGE_SECONDS` (default 7200). Contracts are one per event/market/line; only books that price every selection are included; quarter lines and unmatched participants are skipped.
- Tools: arbitrage and low hold use all books; +EV needs at least two sharp books (`CORNER_TOOLS_REFERENCE_BOOKS`, default `pinnacle,betfair_ex_uk,prophetx,kalshi`; database mode uses whichever fully price the contract, minimum two) priced on the contract and targets every non-sharp book in the data (set `CORNER_TOOLS_TARGET_BOOKS` to restrict; the UI lets the user pick books). Refresh requests name ten bookmakers (draftkings, fanduel, espnbet, betmgm, novig, betrivers plus the four sharps), so a league still costs 3 credits; Caesars (williamhill_us) was swapped out to keep ten books, and bet365 is not in the US region and is not requested; middles pair different lines of the same game/market across books; promo conversion uses the opposite-back hedge (no exchange/lay prices are retained).
- **Rebuild cost.** `POST /api/v1/catalog/reload` (the UI calls it once per page load and after a refresh) first reads a cheap fingerprint of what the quote query depends on (observation count and newest time, decisions, links, events). If it is unchanged the stored rows are reused and only the time cut-offs are re-applied, and if the resulting catalog input is identical the existing catalog is kept, so a page reload costs about half a second instead of re-running the 1.5 s `trusted_current_quotes` view and the whole calculation. The per-game middle search is memoized by its exact bets, and bets that cannot be half of any window are skipped (the window depends only on the two lines, never on the odds). Sorted and filtered feed lists are kept for the life of a snapshot, so paging a feed sorts it once. Output, ids and `snapshot_id` are unchanged. The session login is granted read access to `observation_dispositions` for the fingerprint; without it caching is simply off.
- The catalog is rebuilt from the database at most every 15 seconds. If a rebuild fails the last good snapshot keeps being served; a changed snapshot gives clients a 409 `snapshot_changed`.
- Assumptions to review: reference-book choice, `refund_possible=true`, and that all books settle main lines identically. `production_authorized` and `availability_verified` stay false.
