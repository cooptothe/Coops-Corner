# The Corner frontend

The primary application is now the [Next.js / TypeScript frontend](../web/README.md).
This directory remains the legacy static reference and shared formatting/CSS
source used for regression coverage. Use the Next.js app on port 3000 for UI work.

Responsive, fixture-backed betting workspace served by the existing local API.
No Node build, separate frontend server, database, provider key or external assets
are needed. Tracker, bankroll and CLV remain separate backend work.

## Run

From the repository root:

```powershell
.\.venv-api\Scripts\python.exe -m api --port 8000
```

Open http://127.0.0.1:8000/ and stop the foreground server with Ctrl+C.
For fresh installation see [the API setup](../api/README.md). Keep this unauthenticated
development app on loopback; it is not a public or production deployment.

## Views

- Dark Positive EV, arbitrage, middles and low-hold cards with server-side filtering,
  sorting and pagination. Calculation drawers expose source quotes, payoff states
  and full-precision API output.
- Games directory and sportsbook comparison grids for the six featured markets.
  A back quote can be carried directly into the promo calculator.
- Promo conversion for four explicit bonus/refund models, using same-selection
  lay or eligible opposite-back hedges. Cash profit and noncash token face are
  displayed separately. Inputs describe assumptions, not verified eligibility.

All views label synthetic data. Reloading the snapshot does not make fixture
timestamps current. No bet is placed or saved; no Opportunity or work ledger is
mutated. Conditional EV, decisive profit and all-modeled-state minimum payoff
have separate labels. Odds display in signed American format, rounded to whole
lines; stakes, liabilities and payoffs display as USD with two decimal places
and thousands separators. The fixture calculator's unit maps to $1 for display.
Raw API decimal values remain inspectable in calculation details.

## Client boundaries

`app.js` handles views and interactions; `client.mjs` handles API envelopes,
timeouts, cancellation, pagination and snapshot binding; `format.mjs` handles
exact base-10/BigInt formatting, American odds conversion and eligible hedge selection.
`presentation.mjs` renders bet cards and contract-separated odds grids;
`betting.css` supplies the dark workspace theme. Prices and amounts
remain decimal strings in requests. Display rounding does not change calculations.

The promo minimum-odds field accepts signed American lines such as -200 or +150.
Threshold conversion rounds upward to the API's supported 12-place precision
when a negative line has a repeating decimal. Display odds never replace source
quote values. The grid's best quoted price compares raw odds before commission
(highest back price or lowest lay price); lay fees remain visible.

The frontend has no hardcoded fallback dataset. API failures appear as errors,
not successful zero counts. Changing promo inputs clears the previous result;
changing table filters cancels the prior request. Snapshot conflicts require an
explicit reload. The backend remains the calculation and validation authority.

## Verification

```powershell
node --test tests/frontend.test.mjs
node --check frontend/app.js
.\.venv-api\Scripts\python.exe -m unittest discover -s tests -p 'test_product_api.py' -q
```

17 JavaScript tests and 38 API tests pass. Combined Python offline regression
from the frontend integration:
346 passed, 359 skipped (705 discovered); database skips are not passes.
Browser checks exercised pagination, payoff drawers, odds-to-promo navigation,
API calculation, result invalidation, empty/reset filters and responsive layouts.
Mobile testing also caught and fixed an offscreen table-header overflow. Dark-theme
verification exercised the American-odds quote-to-promo flow, USD outputs, mobile
filter disclosure and middle payoff details.

The UI uses native ES modules, native dialogs and system fonts. Bet cards stack
on mobile; filters collapse and quote grids scroll within their own container.
No tracker, bankroll, CLV, alerts,
authentication, live ingestion or Sharp Money/Insiders UI is implied.
