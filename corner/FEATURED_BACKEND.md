# Featured-only product backend

Scope fixed October 2, 2026. Sharp Money / Insiders is excluded, not deferred.
The product market allowlist is exactly:

`h2h`, `spreads`, `totals`, `outrights`, `h2h_lay`, `outrights_lay`.

No player props, alternate-market keys, team totals, period markets, or parlay
builder are included in this slice. Featured spreads/totals may differ across
books; matching different offered lines for middles is still in product scope.
Historical ingestion fixtures and pinned v1/v2 implementations remain intact;
they are not the new product allowlist.

## Implemented now

- `featured_markets.py`: raw decimal-odds JSON to immutable featured quote views;
  preserves draw outcomes, outright entrants without home/away teams, lay/back
  direction, prices, points, timestamps, source IDs/links, payload digest and JSON
  pointers. Excluded markets are reported. No phase/settlement approval is inferred.
- Request planning separates game and outright sport families using an explicit
  catalog flag. Lay selections request their parent market; it does not blindly
  send all six keys together or invent available exchange quotes.
- `featured_tools.py`: complete-field back-price comparison and dutching for
  two-way, three-way, and N-way contracts; overround, rounded worst-case payoff,
  and configurable low-hold filtering. Cash allocation preserves the budget.
- Same-selection back/lay hedge calculation for h2h and outrights, explicit
  commission, rounded lay stake, liability and both decisive payoff branches.
- `featured_matching.py`: explicit event/sport/market/selection/book routes to
  canonical IDs. Exact points and back/lay direction cannot be collapsed.
- `featured_store.py`: verified ingestion of an already-retained payload into
  existing observation tables; atomic writes, exact retry comparison, original
  IDs on concurrent retries. Reads use the existing trusted-current projection.
- `featured_queries.py`: coherent read-only database snapshots feeding the cover
  and hedge calculators, with exact line pairs, complete registered winner
  populations, explicit commission and age/skew settings.
- `featured_payoffs.py` / `featured_ev.py`: explicit win/loss/push/split/dead-heat
  payoff tables and complete-field, equal-book no-vig conditional EV for the six
  featured market keys. Lay EV uses liability, not lay stake, as its denominator.
- `featured_middles.py`: bounded cross-line candidate discovery plus full integer
  score-range payoffs, including push and quarter-line boundaries. EV requires a
  separately supplied probability distribution.
- `featured_promos.py`: stake-not-returned and cash-returned bonus models, cash
  and noncash loss-refund models, rounded/capped lay or opposite-back hedges.
- Expanded +EV, payoff, middle and promo contracts: read [FEATURED_PAYOFFS.md](FEATURED_PAYOFFS.md) for exact contracts and
  integration limits. These do not alter the pinned v1/v2 engines.
- `api/`: fixture-only HTTP surface for games/odds, +EV, arbitrage/low-hold,
  middles and promo calculations. Typed OpenAPI responses, exact decimal strings,
  filters, stable pagination and snapshot-bound quote selection. See
  [the API guide](../api/README.md); no DB connection or production mode exists.

See [FEATURED_PERSISTENCE.md](FEATURED_PERSISTENCE.md) for the persistence and query
contracts. This uses the existing schema; no new migration or main-DB change.

Provider definitions: [featured markets](https://the-odds-api.com/sports-odds-data/betting-markets.html)
and [v4 odds endpoint](https://the-odds-api.com/liveapi/guides/v4/#get-odds).
`h2h` can include draw. Lay markets oppose the named outcome; lay stake is not
the amount at risk. Outrights do not imply a two-participant event.

## Calculation boundary

These are **pure calculators**, not persisted opportunity detectors or a live
scanner. They accept an explicitly matched settlement contract with a complete,
mutually exclusive decisive outcome population. A list of available quotes is
not proof that the population is complete. The caller owns event/competition,
participant, scope, exact line and settlement matching. The demo supplies those
bindings explicitly from fixture knowledge; no production resolver is installed.

For a back cover with decimal prices d_i, q = sum(1 / d_i). Reported overround is
q - 1; unrounded dutching ROI is 1/q - 1. These are different quantities. Actual
payoffs use allocated cash stakes, so rounding can remove a small apparent edge.
Allocation uses deterministic largest remainders, not an integer optimizer or a
claim that every possible profitable stake combination will be found.

Back covers currently require zero commission. Back/lay supports a single isolated
position at each of two separate books/accounts with commission charged on net
positive winnings. It does not model other positions in the exchange market,
market-net commission across multiple legs, fees, discounts or tax.

A common full-refund branch can be represented as zero profit independently from
decisive win/loss branches. Positive decisive payoff is not strictly positive in
that refund branch. Partial refunds, quarter-line split settlements, dead heats,
different void conditions between legs and nonzero exceptional payouts cannot be
collapsed into this flag. The separate `featured_payoffs.py` now models explicit
won/lost/refunded fractions and per-position states, and `featured_middles.py`
models quarter-line splits; it does not infer nonzero exceptional payouts or rules
applicability. The older cover and query contracts remain deliberately narrower.

Prices are assumed fixed and accepted by the pure calculator. The database query
adapter separately screens observation age and skew; that alone does not establish
current actionability. Limits, exchange depth, account balance and bet acceptance
are not established. Outputs explicitly retain
`availability_verified=false`. They do not promise executable or risk-free profit.
Arithmetic uses exact rational intermediates and a private 50-digit Decimal output
context, independent of ambient precision. Calculator numeric inputs are bounded
to 12 fractional digits and magnitude 1e12; raw quote capture retains more precision.

## Remaining backend work, in delivery order

1. **Matching/storage integration — implemented for explicitly provisioned
   canonical registries.** The six-market writer and read/query adapter are now
   tested with retained synthetic payloads in disposable PostgreSQL, including
   races and rollback. Automated live registry resolution, provider freshness
   policies beyond basic timestamp validation and ingestion scheduling remain
   unwired. A fixture-backed HTTP API is now available; live DB-backed HTTP
   integration remains unwired. Historical ingestion is unchanged.
2. **Broader +EV/payoff calculators — implemented.** Explicit state models and
   N-way conditional EV exist; database quote helpers feed the EV calculator.
   Broader persisted-engine/qualification/worker integration remains unwired.
3. **Middles — pure calculation/discovery implemented.** Cross-line integer and
   quarter-line payoff tables, push boundaries, loss and double-win ranges.
   Live cross-line DB discovery/API and empirical probability models remain unwired.
4. **Promo conversion — pure calculation and quote-query helpers implemented.**
   Explicit bonus/cash/token economics, constraints and hedge payout tables.
   Real promotion ingestion, eligibility verification and redemption tracking
   remain outside the calculator.
5. **Tracker / bankroll:** recorded user wagers, edits/corrections, deposits and
   withdrawals, grading and P&L. An analytical occurrence is not a placed wager.
6. **CLV:** entry quote binding and an explicit closing benchmark with historical
   coverage. Retained odds alone do not establish a valid closing price.
7. **Games, frontend API and UI — fixture slice implemented.** Exact-contract odds
   boards, tool/read DTOs, filters, pagination, typed OpenAPI and a stateless promo
   calculator are available, with a responsive browser workspace served at `/`
   by the same local API process (see `frontend/README.md`). Historical movement, tracker responses and live
   database-backed serving remain unwired.

No evidence approval research, emails, paid data calls, new runtime grants,
production loader, or production authorization are part of this work. A missing
production approval does not block fixture-backed calculators or frontend work.
