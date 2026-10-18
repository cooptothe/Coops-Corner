"""Pure featured-market cover/hedge calculators, independent of the v1/v2 engine.

Inputs are already matched to an explicit exhaustive settlement contract. These
functions do not establish applicability, execute bets, or persist opportunities.
They model fixed accepted prices and explicitly supplied commission, not liquidity.
"""
from dataclasses import dataclass
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from fractions import Fraction

VERSION = "corner.featured_tools/1"
from corner.additional_markets import ADDITIONAL_MARKETS, LINE_MARKETS, PROP_KEYS
BACK_MARKETS = {"h2h", "spreads", "totals", "outrights", *ADDITIONAL_MARKETS, *PROP_KEYS}
LAY_MARKETS = {"h2h_lay": "h2h", "outrights_lay": "outrights"}
ZERO = Decimal("0")
ONE = Decimal("1")
CALCULATION_CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN)


class ToolInputError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise ToolInputError(message)


def _id(value):
    _require(isinstance(value, str) and bool(value.strip()), "nonblank identity required")


def _decimal(value, label, *, positive=False):
    _require(isinstance(value, Decimal) and value.is_finite(), f"{label}: finite Decimal required")
    _require(value >= 0 and (not positive or value > 0), f"invalid {label}")
    # This product-facing calculator is not an arbitrary precision input sink.
    _require(value <= Decimal("1e12") and value.as_tuple().exponent >= -12,
             f"{label}: maximum 12 fractional digits and magnitude 1e12")
    return value


def _decimal_ratio(value):
    with localcontext(CALCULATION_CONTEXT):
        return Decimal(value.numerator) / Decimal(value.denominator)


def _cash_units(amount, increment):
    _decimal(amount, "amount", positive=True)
    _decimal(increment, "stake increment", positive=True)
    units = Fraction(amount) / Fraction(increment)
    _require(units.denominator == 1, "amount must be a whole number of stake increments")
    return units.numerator


@dataclass(frozen=True)
class MatchedMarket:
    """Caller-supplied canonical matching, never inferred from available quotes.

    contract_id includes event/competition, scope, line and compatible settlement
    semantics. selection_ids must enumerate every decisive result (including draw
    or all outright entrants). refund_possible is a separate modeled zero-return
    branch, not a probability estimate. Dead heats/partial settlements are outside
    this calculator and must not be represented as mutually exclusive winners.
    """
    contract_id: str
    market_key: str
    selection_ids: tuple[str, ...]
    refund_possible: bool

    def __post_init__(self):
        _id(self.contract_id)
        _require(self.market_key in BACK_MARKETS, "supported back market required")
        _require(type(self.selection_ids) is tuple and len(self.selection_ids) >= 2,
                 "explicit exhaustive selection tuple required")
        for selection in self.selection_ids:
            _id(selection)
        _require(len(set(self.selection_ids)) == len(self.selection_ids), "duplicate contract selection")
        if self.market_key in LINE_MARKETS:
            _require(len(self.selection_ids) == 2, "spread/total requires two decisive selections")
        _require(type(self.refund_possible) is bool, "explicit refund branch required")
        if self.market_key in ADDITIONAL_MARKETS:
            _require(len(self.selection_ids) == 2, "additional markets require two decisive selections")
        if self.market_key == "draw_no_bet":
            _require(self.refund_possible, "Draw No Bet requires draw refund branch")


@dataclass(frozen=True)
class Offer:
    quote_id: str
    contract_id: str
    market_key: str
    selection_id: str
    sportsbook_id: str
    decimal_odds: Decimal
    commission_rate: Decimal

    def __post_init__(self):
        for identifier in (self.quote_id, self.contract_id, self.selection_id, self.sportsbook_id):
            _id(identifier)
        _require(self.market_key in BACK_MARKETS | LAY_MARKETS.keys(), "unsupported market")
        _decimal(self.decimal_odds, "odds", positive=True)
        _require(self.decimal_odds > 1, "decimal odds must exceed one")
        _decimal(self.commission_rate, "commission")
        _require(self.commission_rate < 1, "commission must be less than one")


@dataclass(frozen=True)
class CoverLeg:
    quote_id: str
    selection_id: str
    sportsbook_id: str
    decimal_odds: Decimal
    stake: Decimal
    profit_if_selection_wins: Decimal


@dataclass(frozen=True)
class BackCover:
    contract_id: str
    market_key: str
    total_stake: Decimal
    implied_probability_sum: Decimal
    overround: Decimal
    unrounded_dutching_roi: Decimal
    legs: tuple[CoverLeg, ...]
    minimum_decisive_profit: Decimal
    refund_profit: Decimal | None
    minimum_modeled_profit: Decimal
    decisive_arbitrage: bool
    all_modeled_states_profitable: bool
    format: str = VERSION
    availability_verified: bool = False
    commission_basis: str = 'isolated_leg_conservative_net_winnings'

    def is_low_hold(self, maximum_loss_ratio: Decimal):
        """Low-hold ranking uses actual rounded worst-case loss / total stake.

        This is not the same quantity as overround. Negative modeled loss (profit)
        qualifies too. No claim is made about promotional rollover eligibility.
        """
        _decimal(maximum_loss_ratio, "maximum loss ratio")
        _require(maximum_loss_ratio <= 1, "maximum loss ratio cannot exceed one")
        return -Fraction(self.minimum_modeled_profit) <= Fraction(maximum_loss_ratio) * Fraction(self.total_stake)


def calculate_back_cover(market: MatchedMarket, offers, *, total_stake: Decimal,
                         stake_increment: Decimal = Decimal("0.01")) -> BackCover:
    """Best back price per explicit selection, equal-return dutching, cash rounding.

    Allocates a fixed budget using largest fractional remainders; returns actual
    per-outcome profit after stake rounding. Missing selections fail, so a partial
    soccer or outright field cannot silently become a two-outcome arbitrage.
    Fee-bearing legs use net win returns. If multiple legs share a fee-bearing
    book, charging the winning leg before market netting is a conservative bound;
    losing stakes at that book can only reduce the actual market-net commission.
    """
    _require(type(market) is MatchedMarket, "matched market required")
    units = _cash_units(total_stake, stake_increment)
    offers = tuple(offers)
    _require(bool(offers), "at least one offer required")
    _require(all(type(offer) is Offer for offer in offers), "validated offers required")
    _require(len({offer.quote_id for offer in offers}) == len(offers), "duplicate quote id")
    for offer in offers:
        _require((offer.contract_id, offer.market_key) == (market.contract_id, market.market_key),
                 "mixed contracts or back/lay direction")
        _require(offer.selection_id in market.selection_ids, "unexpected contract selection")
    chosen = []
    for selection in sorted(market.selection_ids):
        candidates = [offer for offer in offers if offer.selection_id == selection]
        _require(bool(candidates), f"missing expected selection: {selection}")
        chosen.append(min(candidates, key=lambda x: (-(1 + (Fraction(x.decimal_odds)-1) *
                                                      (1-Fraction(x.commission_rate))), x.sportsbook_id, x.quote_id)))
    net_odds = [1 + (Fraction(o.decimal_odds)-1) * (1-Fraction(o.commission_rate)) for o in chosen]
    implied = [1 / odds for odds in net_odds]
    total_implied = sum(implied)
    targets = [units * probability / total_implied for probability in implied]
    allocated = [target.numerator // target.denominator for target in targets]
    remaining = units - sum(allocated)
    order = sorted(range(len(chosen)), key=lambda i: (-(targets[i] - allocated[i]), chosen[i].selection_id))
    for index in order[:remaining]:
        allocated[index] += 1
    _require(all(amount > 0 for amount in allocated), "budget too small to cover every selection")
    legs = []
    for offer, amount, net in zip(chosen, allocated, net_odds):
        stake = Fraction(stake_increment) * amount
        profit = stake * net - Fraction(total_stake)
        legs.append(CoverLeg(offer.quote_id, offer.selection_id, offer.sportsbook_id,
                             offer.decimal_odds, _decimal_ratio(stake), _decimal_ratio(profit)))
    minimum = min(leg.profit_if_selection_wins for leg in legs)
    modeled = min(minimum, ZERO) if market.refund_possible else minimum
    return BackCover(market.contract_id, market.market_key, total_stake,
                     _decimal_ratio(total_implied), _decimal_ratio(total_implied - 1),
                     _decimal_ratio(1 / total_implied - 1), tuple(legs), minimum,
                     ZERO if market.refund_possible else None, modeled,
                     minimum > 0, modeled > 0)


@dataclass(frozen=True)
class BackLayHedge:
    contract_id: str
    back_quote_id: str
    lay_quote_id: str
    back_stake: Decimal
    lay_stake: Decimal
    lay_liability: Decimal
    conservative_capital_required: Decimal
    profit_if_selection_wins: Decimal
    profit_if_selection_loses: Decimal
    minimum_decisive_profit: Decimal
    minimum_modeled_profit: Decimal
    refund_profit: Decimal | None
    format: str = VERSION
    availability_verified: bool = False


def calculate_back_lay(market: MatchedMarket, back: Offer, lay: Offer, *,
                       back_stake: Decimal, stake_increment: Decimal = Decimal("0.01")):
    """Hedge the SAME selection: lay stake is winnings, not liability.

    Assumes isolated positions in separate accounts/books with explicit commission
    on positive net winnings, no other positions, fees or dead heats. No exchange
    depth, stake limits, available balance, or bet acceptance is inferred.
    """
    _require(type(market) is MatchedMarket and type(back) is Offer and type(lay) is Offer,
             "validated market and offers required")
    _require(market.market_key in {"h2h", "outrights"}, "featured lays exist only for h2h/outrights")
    _require(back.contract_id == lay.contract_id == market.contract_id, "mixed contracts")
    _require(back.market_key == market.market_key and LAY_MARKETS.get(lay.market_key) == back.market_key,
             "matching back and lay market directions required")
    _require(back.selection_id == lay.selection_id and back.selection_id in market.selection_ids,
             "back/lay must bind the same expected selection")
    _require(back.quote_id != lay.quote_id, "distinct quotes required")
    _require(back.sportsbook_id != lay.sportsbook_id, "same-account market-net commission is unsupported")
    _cash_units(back_stake, stake_increment)
    stake, back_odds, lay_odds = map(Fraction, (back_stake, back.decimal_odds, lay.decimal_odds))
    back_commission, lay_commission = map(Fraction, (back.commission_rate, lay.commission_rate))
    increment = Fraction(stake_increment)
    ideal_lay = stake * (1 + (back_odds - 1) * (1 - back_commission)) / (lay_odds - lay_commission)
    ideal_units = ideal_lay / increment
    floor_units = ideal_units.numerator // ideal_units.denominator
    candidates = {floor_units, floor_units + 1}
    candidates.discard(0)

    def profits(units):
        lay_stake = units * increment
        return (stake * (back_odds - 1) * (1 - back_commission) - lay_stake * (lay_odds - 1),
                -stake + lay_stake * (1 - lay_commission))

    best_units = max(candidates, key=lambda units: (min(profits(units)), -units))
    win_profit, lose_profit = profits(best_units)
    lay_stake = best_units * increment
    liability = lay_stake * (lay_odds - 1)
    minimum = min(win_profit, lose_profit)
    modeled = min(minimum, Fraction(0)) if market.refund_possible else minimum
    return BackLayHedge(market.contract_id, back.quote_id, lay.quote_id, back_stake,
                        _decimal_ratio(lay_stake), _decimal_ratio(liability),
                        _decimal_ratio(stake + liability), _decimal_ratio(win_profit),
                        _decimal_ratio(lose_profit), _decimal_ratio(minimum),
                        _decimal_ratio(modeled), ZERO if market.refund_possible else None)
