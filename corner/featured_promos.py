"""Explicit bonus/cash-refund economics and a bounded, rounded isolated lay hedge.

Promotion eligibility is attested by the caller, not inferred from a market name.
Noncash refunds are never valued as cash. No promotion, bet acceptance or liquidity
is verified here. Hedges are same-selection h2h/outright lays or opposite backs
in explicit two-way featured contracts.
"""
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from corner.featured_tools import MatchedMarket, Offer, LAY_MARKETS, _id, _require, _decimal, _decimal_ratio, _cash_units

FORMAT = "corner.featured_promos/1"
PROMO_KINDS = {"bonus_stake_not_returned", "bonus_stake_returned_as_cash", "loss_refund_cash", "loss_refund_bonus"}


@dataclass(frozen=True)
class PromoTerms:
    terms_id: str
    kind: str
    face_value: Decimal
    eligible_stake_cap: Decimal
    minimum_decimal_odds: Decimal
    loss_refund_cap: Decimal
    eligibility_evidence_id: str
    bonus_restored_on_void: bool

    def __post_init__(self):
        _id(self.terms_id)
        _id(self.eligibility_evidence_id)
        _require(self.kind in PROMO_KINDS, "unsupported promo kind")
        for name in ("face_value", "eligible_stake_cap", "minimum_decimal_odds"):
            _decimal(getattr(self, name), name, positive=True)
        _require(self.minimum_decimal_odds > 1, "invalid minimum odds")
        _require(self.face_value <= self.eligible_stake_cap, "promo stake exceeds eligibility cap")
        _decimal(self.loss_refund_cap, "refund cap")
        _require(type(self.bonus_restored_on_void) is bool, "explicit void treatment required")
        if self.kind.startswith("bonus_"):
            _require(self.loss_refund_cap == 0, "bonus stake cannot also have a loss refund")
        else:
            _require(not self.bonus_restored_on_void, "cash wager void returns cash stake, not bonus")


@dataclass(frozen=True)
class PromoOutcome:
    state: str
    net_cash_profit: Decimal
    noncash_bonus_face_returned: Decimal


@dataclass(frozen=True)
class PromoConversion:
    contract_id: str
    terms: PromoTerms
    back_quote_id: str
    lay_quote_id: str
    lay_stake: Decimal
    lay_liability: Decimal
    upfront_cash_required: Decimal
    outcomes: tuple[PromoOutcome, ...]
    minimum_decisive_cash_profit: Decimal
    minimum_modeled_cash_profit: Decimal
    decisive_cash_to_face_ratio: Decimal
    format: str = FORMAT
    optimization_basis: str = "maximum_minimum_decisive_cash_profit"
    noncash_valuation: None = None
    eligibility_verified: bool = False
    availability_verified: bool = False


def _cash_branches(terms, odds):
    amount = Fraction(terms.face_value)
    is_bonus = terms.kind.startswith("bonus_")
    win = amount * (odds if terms.kind == "bonus_stake_returned_as_cash" else odds - 1)
    loss = Fraction(0) if is_bonus else -amount
    refund = min(amount, Fraction(terms.loss_refund_cap))
    token = Fraction(0)
    if terms.kind == "loss_refund_cash":
        loss += refund
    elif terms.kind == "loss_refund_bonus":
        token = refund
    return win, loss, token


def _best_hedge(win, loss, cost_on_win, return_on_loss, increment, ceiling_units):
    ideal = (win - loss) / (cost_on_win + return_on_loss)
    floor = (ideal / increment).__floor__()
    candidates = {0, floor, floor + 1}
    if ceiling_units is not None:
        candidates = {min(n, ceiling_units) for n in candidates}

    def cash(n):
        return win - n * increment * cost_on_win, loss + n * increment * return_on_loss

    chosen = max(candidates, key=lambda n: (min(cash(n)), -n))
    return chosen * increment, cash(chosen)


def _outcomes(win, loss, token, terms, refund_possible):
    result = [PromoOutcome("selection_wins", _decimal_ratio(win), Decimal(0)),
              PromoOutcome("selection_loses", _decimal_ratio(loss), _decimal_ratio(token))]
    if refund_possible:
        result.append(PromoOutcome("common_void", Decimal(0), terms.face_value if terms.bonus_restored_on_void else Decimal(0)))
    return tuple(result)


def convert_promo(market, back, lay, terms, *, stake_increment=Decimal("0.01"),
                  maximum_lay_stake=None, maximum_lay_liability=None):
    """Hedge a fixed face/stake at fixed accepted prices; no token cash valuation.

    Bonus modes assume zero cash cost of the token and no acquisition cost. The
    returned-stake variant explicitly requires the returned stake to be CASH.
    Loss-refund modes use a cash wager: cash refunds increase loss-state cash,
    token refunds only increase noncash face value. Caps constrain the hedge.
    A common void refunds cash stakes and optionally restores a bonus token.
    """
    _require(type(market) is MatchedMarket and type(back) is Offer and type(lay) is Offer and type(terms) is PromoTerms,
             "validated contract, offers and terms required")
    _require(market.market_key in {"h2h", "outrights"} and back.market_key == market.market_key
             and LAY_MARKETS.get(lay.market_key) == back.market_key, "same-selection featured back/lay required")
    _require(back.contract_id == lay.contract_id == market.contract_id and back.selection_id == lay.selection_id
             and back.selection_id in market.selection_ids, "promo hedge contract mismatch")
    _require(back.sportsbook_id != lay.sportsbook_id and back.quote_id != lay.quote_id, "distinct books/quotes required")
    _require(back.commission_rate == 0, "promo back commission unsupported")
    _require(back.decimal_odds >= terms.minimum_decimal_odds, "price fails promo minimum odds")
    _cash_units(terms.face_value, stake_increment)
    amount, odds, lay_odds, commission, increment = map(Fraction, (terms.face_value, back.decimal_odds,
                                                               lay.decimal_odds, lay.commission_rate, stake_increment))
    is_bonus = terms.kind.startswith("bonus_")
    win, loss, token = _cash_branches(terms, odds)
    ceiling_units = None
    for limit, multiplier in ((maximum_lay_stake, Fraction(1)), (maximum_lay_liability, lay_odds - 1)):
        if limit is not None:
            _decimal(limit, "hedge limit")
            units = (Fraction(limit) / multiplier / increment).__floor__()
            ceiling_units = units if ceiling_units is None else min(ceiling_units, units)
    hedge, (win_cash, loss_cash) = _best_hedge(win, loss, lay_odds - 1, 1 - commission, increment, ceiling_units)
    liability = hedge * (lay_odds - 1)
    outcomes = _outcomes(win_cash, loss_cash, token, terms, market.refund_possible)
    minimum = min(win_cash, loss_cash)
    return PromoConversion(market.contract_id, terms, back.quote_id, lay.quote_id, _decimal_ratio(hedge),
                           _decimal_ratio(liability), _decimal_ratio(liability + (0 if is_bonus else amount)),
                           tuple(outcomes), _decimal_ratio(minimum), min(o.net_cash_profit for o in outcomes),
                           _decimal_ratio(minimum / amount))


@dataclass(frozen=True)
class PromoBackConversion:
    contract_id: str
    terms: PromoTerms
    promo_quote_id: str
    hedge_quote_id: str
    hedge_stake: Decimal
    upfront_cash_required: Decimal
    outcomes: tuple[PromoOutcome, ...]
    minimum_decisive_cash_profit: Decimal
    minimum_modeled_cash_profit: Decimal
    decisive_cash_to_face_ratio: Decimal
    format: str = FORMAT
    optimization_basis: str = "maximum_minimum_decisive_cash_profit"
    noncash_valuation: None = None
    eligibility_verified: bool = False
    availability_verified: bool = False


def convert_promo_back_hedge(market, promo, hedge, terms, *, stake_increment=Decimal("0.01"), maximum_hedge_stake=None):
    """Opposite back hedge for an explicitly TWO-way contract, including lines.

    A single opponent in three-way h2h or an N-way outright is not a complete
    hedge. Integer-line pushes require the common refund flag. This function
    cannot combine different lines: use the middle payoff table for those.
    """
    _require(type(market) is MatchedMarket and type(promo) is Offer and type(hedge) is Offer and type(terms) is PromoTerms,
             "validated market, offers and terms required")
    _require(len(market.selection_ids) == 2, "opposite back promo hedge requires two exhaustive selections")
    _require(promo.contract_id == hedge.contract_id == market.contract_id
             and promo.market_key == hedge.market_key == market.market_key, "promo hedge contract/direction mismatch")
    _require({promo.selection_id, hedge.selection_id} == set(market.selection_ids), "complementary selections required")
    _require(promo.sportsbook_id != hedge.sportsbook_id and promo.quote_id != hedge.quote_id, "distinct books/quotes required")
    _require(promo.commission_rate == 0, "promo back commission unsupported")
    _require(promo.decimal_odds >= terms.minimum_decimal_odds, "price fails promo minimum odds")
    _cash_units(terms.face_value, stake_increment)
    win, loss, token = _cash_branches(terms, Fraction(promo.decimal_odds))
    increment = Fraction(stake_increment)
    cap = None
    if maximum_hedge_stake is not None:
        _decimal(maximum_hedge_stake, "hedge limit")
        cap = (Fraction(maximum_hedge_stake) / increment).__floor__()
    amount, (win_cash, loss_cash) = _best_hedge(win, loss, Fraction(1),
                  (Fraction(hedge.decimal_odds) - 1) * (1 - Fraction(hedge.commission_rate)), increment, cap)
    outcomes = _outcomes(win_cash, loss_cash, token, terms, market.refund_possible)
    minimum = min(win_cash, loss_cash)
    capital = amount + (0 if terms.kind.startswith("bonus_") else Fraction(terms.face_value))
    return PromoBackConversion(market.contract_id, terms, promo.quote_id, hedge.quote_id, _decimal_ratio(amount),
                               _decimal_ratio(capital), outcomes, _decimal_ratio(minimum),
                               min(o.net_cash_profit for o in outcomes), _decimal_ratio(minimum / Fraction(terms.face_value)))
