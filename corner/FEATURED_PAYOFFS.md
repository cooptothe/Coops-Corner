# Featured payoff, +EV, middles and promo calculators

These are new, independent pure contracts. They do **not** replace the pinned
`corner.ev` / conditional-v2 engines or register new work-dispatch implementations.
No migration, domain ledger write, source approval, service or production switch
is introduced. The feature allowlist remains h2h, spreads, totals, outrights,
h2h_lay and outrights_lay. Sharp Money / Insiders remains excluded.


## Explicit payoff states — `featured_payoffs.py`

Supply an exhaustive, named state set and a settlement for every position in
every state. A settlement divides the **back stake** into won, lost and refunded
fractions summing exactly to one. Examples:

| Settlement | Won | Lost | Refunded |
| --- | ---: | ---: | ---: |
| Win | 1 | 0 | 0 |
| Push / full refund | 0 | 0 | 1 |
| Half win, half push | .5 | 0 | .5 |
| Half loss, half push | 0 | .5 | .5 |
| Two-way dead heat, stake-division rules | .5 | .5 | 0 |

At decimal odds `d` and stake `s`, back profit is
`s * (won * (d - 1) - lost)`. A lay is its counterparty before commission.
Thus a dead heat is not implemented as simply dividing the winning profit.
Actual nonrunner/dead-heat/quarter-line rules remain caller-supplied authority;
the calculator does not classify a real contract from its name. Fractions must
be exactly representable within the input precision; arbitrary repeating
dead-heat fractions and nonzero exceptional payouts are not inferred.

Commission is charged on positive **net** profit of each explicitly identified
account/market commission group in each state. Conflicting rates in one group
are rejected. Separate groups must genuinely settle commission independently.
Capital is conservative summed back stakes plus lay liabilities, not a margin
offset or an account-balance check.

Without probabilities, the result is a payoff table, minimum and maximum—not EV.
With probabilities, all declared states must be present, nonnegative and sum
exactly to one, with an explicit probability-model ID and basis:

- `conditional_on_declared_states`: excludes other states deliberately.
- `exhaustive_settlement_states`: caller asserts that this is the full population.

Push/void probability is never silently set to zero. The returned result retains
positions, settlements and probabilities. This API can model asymmetric refunds
with explicit joint states and probabilities; the simpler cover/middle/promo
calculators' common-refund flag cannot.

## Broader conditional +EV — `featured_ev.py`

`calculate_featured_ev(market, target, reference_offers,
required_reference_books=(...), stake=...)` supports:

- Two- and three-way h2h, including draw.
- Complete N-way outright fields.
- Exact-line spreads and totals, conditional on decisive settlement.
- Same-selection h2h_lay / outrights_lay targets, with EV divided by lay liability.

Every required reference book must supply exactly one back quote for every
declared selection. At least two distinct reference books are required. Missing
draws, missing books, duplicate selections, unexpected books, incompatible
contract IDs, lay references and nonzero reference commissions fail validation.
The target book cannot contribute to its own reference estimate. No convenient
subset is selected after validation failure.

Each reference book is devigged proportionally: `(1/d_i) / sum(1/d_j)`.
The resulting distributions are averaged with equal weight per book. This is an
explicit estimator, not a guarantee of true probability or an implied advanced
vig model. Exact Fraction intermediates avoid aggregation of rounded probabilities.

For selection probability `p`, target decimal odds `d`, commission `c`:

- Back EV per stake: `p*(d-1)*(1-c) - (1-p)`.
- Lay EV per liability: `((1-p)*(1-c) - p*(d-1)) / (d-1)`.

Outputs identify decisive-settlement conditional probability/EV and leave
unconditional EV null. Ordinary prices do not supply push, void, nonrunner or
dead-heat probabilities. Use the explicit payoff model with a separate probability
model for those states. Shared contract identity asserts compatible conditioning;
this calculator does not approve rules applicability.

`CalculationInputs.expected_value()` connects eligible quotes from the existing
read-only database adapter to this calculator. It retains the required book
population even when an eligible quote is absent, causing validation to fail.

## Middles — `featured_middles.py`

`calculate_middle()` accepts two opposing `LineBet`s with an identical
event/scope/rules coordinate contract, distinct books and fixed cash stakes.
The lines may differ. Totals use nonnegative integer total points; spreads use
integer **home minus away** margin. Other scoring domains require another model.

It partitions the entire integer domain into compact, contiguous score ranges,
including integer push boundaries. Quarter lines split equally across adjacent
half lines. It reports per-leg settlement, net payoff, the full-double-win
intervals and worst modeled loss. Reversed lines correctly show double-loss
ranges, not a middle. The common-refund branch is explicit.

`find_middles()` groups caller-bound quotes by contract and featured market,
checks opposite-side cross-book pairs and returns full-double-win candidates in
deterministic order. It rejects oversized pair sets rather than silently truncating
the reference population. This is pure bounded discovery, not live scanning.

A middle window supplies no probability estimate. EV stays null unless the
caller supplies an identified distribution over **every returned score-range
state**, including common refund when present. Stakes are caller inputs, not a
bankroll recommendation. Separate cross-line database discovery/HTTP wiring is
not added here; the existing exact-line query adapter still rejects quarter lines.

## Promo conversion — `featured_promos.py`

The immutable `PromoTerms` requires a terms revision ID, caller eligibility
evidence ID, face/stake, eligible cap, minimum odds, loss-refund cap and explicit
void treatment. Four distinct economic types are supported:

| Kind | Initial cash wager cost | Win cash net before hedge | Loss benefit |
| --- | ---: | --- | --- |
| `bonus_stake_not_returned` | 0 | face × (odds − 1) | None |
| `bonus_stake_returned_as_cash` | 0 | face × odds | None |
| `loss_refund_cash` | face | face × (odds − 1) | Capped cash refund |
| `loss_refund_bonus` | face | face × (odds − 1) | Capped **noncash** token |

Bonus modes assume an already-owned token with zero acquisition cost. Returned
stake must explicitly be cash for the returned-as-cash mode; site credit with
wagering restrictions is not interchangeable. Cash profit for loss-refund modes
subtracts the original cash stake on loss. Token face is reported separately,
without an assumed cash conversion rate. No generic "risk-free bet" alias hides
these distinctions. In common void, cash stakes return with zero net cash; bonus
restoration is separate and explicit.

`convert_promo()` uses a same-selection lay for h2h/outrights. Lay stake and
liability are distinct; commission applies to isolated positive lay winnings.
`convert_promo_back_hedge()` instead uses one opposite back in a complete two-way
featured contract. It rejects three-way/large-field single-opponent hedges because
they do not cover the remaining outcomes. Different lines cannot be substituted.

Both maximize minimum **decisive cash profit** on the permitted stake grid, check
the floor/ceiling of the exact break-even hedge plus bounds, and deterministically
prefer a lower stake on ties. Optional stake/liability caps can leave an unbalanced
hedge, which is reflected in the outcome table. Zero hedge is permitted by a zero
cap. Lay caps are configured bounds, not verified exchange depth.

The result reports hedge size, liability where applicable, upfront cash required,
both decisive outcomes, optional void, noncash returns and minimum modeled cash
profit. `decisive_cash_to_face_ratio` is not an unconditional return, expected
value or a guarantee of available cash. Query helpers `promo_conversion()` and
`promo_back_conversion()` bind these calculations to eligible persisted quotes.

## What this does not claim

No real promotion eligibility, phase, settlement approval, stake acceptance,
exchange depth, price availability, taxes, fees or payout rounding is established.
`eligibility_verified` and `availability_verified` stay false. Payouts are exact
model amounts, not a claim about a book's currency-rounding implementation.
Cash/odds/probability inputs use Decimal (bounded to 12 fractional places and
magnitude 1e12); internal arithmetic is exact Fraction, outputs private-context
50-digit Decimal. No ambient Decimal precision controls the answer.

These product calculators are not persisted `EngineEvaluation`s or qualified
`Opportunity`s. Broader engine-journal/worker dispatch and API endpoints remain
separate integration work, without changing historical command meaning.
