"""Explicit finite settlement models for featured markets. No inferred probabilities.

This is a new pure calculator contract, not a revision of either pinned EV engine.
The caller supplies an exhaustive state universe and the applicable settlement of
each position in every state. Commission groups are isolated account/market pools.
"""
from dataclasses import dataclass, replace
from decimal import Decimal
from fractions import Fraction

from corner.featured_tools import (
    BACK_MARKETS, LAY_MARKETS, _decimal, _decimal_ratio, _id, _require,
)

FORMAT = "corner.featured_payoffs/1"
D = Decimal


@dataclass(frozen=True)
class Settlement:
    """Fractions of BACK stake won, lost, refunded. Lay is the counterparty.

    A half-win/half-push is (0.5, 0, 0.5). A two-way dead heat under
    stake-division rules is (0.5, 0.5, 0), NOT half the winning profit.
    Actual rules must establish these fractions; labels do not do that.
    """
    won: Decimal
    lost: Decimal
    refunded: Decimal

    def __post_init__(self):
        for value in (self.won, self.lost, self.refunded):
            _decimal(value, "settlement fraction")
        _require(sum(map(Fraction, (self.won, self.lost, self.refunded))) == 1,
                 "settlement fractions must sum exactly to one")


WIN = Settlement(D(1), D(0), D(0))
LOSS = Settlement(D(0), D(1), D(0))
REFUND = Settlement(D(0), D(0), D(1))


@dataclass(frozen=True)
class PayoffPosition:
    position_id: str
    market_key: str
    decimal_odds: Decimal
    stake: Decimal  # lay stake means counterparty stake, not liability
    commission_group: str
    commission_rate: Decimal
    settlements: tuple[tuple[str, Settlement], ...]

    def __post_init__(self):
        _id(self.position_id)
        _id(self.commission_group)
        _require(self.market_key in BACK_MARKETS | LAY_MARKETS.keys(), "unsupported market")
        _decimal(self.decimal_odds, "odds", positive=True)
        _require(self.decimal_odds > 1, "odds must exceed one")
        _decimal(self.stake, "stake", positive=True)
        _decimal(self.commission_rate, "commission")
        _require(self.commission_rate < 1, "commission must be less than one")
        _require(type(self.settlements) is tuple and bool(self.settlements), "settlement tuple required")
        for entry in self.settlements:
            _require(type(entry) is tuple and len(entry) == 2, "state/settlement pair required")
            _id(entry[0])
            _require(type(entry[1]) is Settlement, "validated settlement required")
        _require(len(dict(self.settlements)) == len(self.settlements), "duplicate settlement state")


def probability_weights(probabilities, state_ids):
    """Exact normalization; no tolerance, float coercion, missing-state defaults."""
    probabilities = tuple(probabilities)
    for entry in probabilities:
        _require(type(entry) is tuple and len(entry) == 2, "state/probability pair required")
        _id(entry[0])
        _decimal(entry[1], "probability")
        _require(entry[1] <= 1, "probability exceeds one")
    weights = dict(probabilities)
    _require(len(weights) == len(probabilities), "duplicate probability state")
    _require(set(weights) == set(state_ids), "probabilities must cover exactly every modeled state")
    _require(sum(map(Fraction, weights.values())) == 1, "probabilities must sum exactly to one")
    return {key: Fraction(value) for key, value in weights.items()}


def gross_profit(position, settlement):
    stake, odds = Fraction(position.stake), Fraction(position.decimal_odds)
    back = stake * (Fraction(settlement.won) * (odds - 1) - Fraction(settlement.lost))
    return -back if position.market_key in LAY_MARKETS else back


@dataclass(frozen=True)
class StatePayoff:
    state_id: str
    gross_profit: Decimal
    commission: Decimal
    net_profit: Decimal


@dataclass(frozen=True)
class PayoffResult:
    model_id: str
    probability_basis: str
    probability_model_id: str | None
    probabilities: tuple[tuple[str, Decimal], ...] | None
    positions: tuple[PayoffPosition, ...]
    states: tuple[StatePayoff, ...]
    conservative_capital_required: Decimal
    minimum_modeled_profit: Decimal
    maximum_modeled_profit: Decimal
    expected_profit: Decimal | None
    ev_ratio_on_capital: Decimal | None
    format: str = FORMAT
    availability_verified: bool = False


def calculate_payoffs(*, model_id, state_ids, positions, probability_basis,
                      probabilities=None, probability_model_id=None):
    """Price every declared state; compute EV only with a full explicit distribution.

    conditional_on_declared_states deliberately excludes unspecified branches;
    exhaustive_settlement_states is a CALLER assertion of completeness, not an
    approval. Zero-return push/void probabilities cannot be silently omitted from
    an exhaustive model. Fraction intermediates avoid ambient Decimal rounding.
    """
    _id(model_id)
    _require(probability_basis in {"conditional_on_declared_states", "exhaustive_settlement_states"},
             "explicit probability basis required")
    state_ids, positions = tuple(state_ids), tuple(positions)
    _require(bool(state_ids) and len(set(state_ids)) == len(state_ids), "unique nonempty states required")
    for state in state_ids:
        _id(state)
    _require(bool(positions) and all(type(p) is PayoffPosition for p in positions), "validated positions required")
    _require(len({p.position_id for p in positions}) == len(positions), "duplicate position")
    rates = {}
    for position in positions:
        _require(set(dict(position.settlements)) == set(state_ids), "position must cover exactly every state")
        previous = rates.setdefault(position.commission_group, Fraction(position.commission_rate))
        _require(previous == Fraction(position.commission_rate), "conflicting commission rates in one group")
    weights = None
    if probabilities is not None:
        _id(probability_model_id)
        weights = probability_weights(probabilities, state_ids)
    else:
        _require(probability_model_id is None, "probability model without probabilities")
    rows, exact_profits = [], []
    for state in sorted(state_ids):
        pools = {}
        for position in positions:
            amount = gross_profit(position, dict(position.settlements)[state])
            group = position.commission_group
            pools[group] = pools.get(group, Fraction(0)) + amount
        gross = sum(pools.values(), Fraction(0))
        commission = sum((max(Fraction(0), amount) * rates[group] for group, amount in pools.items()), Fraction(0))
        net = gross - commission
        rows.append(StatePayoff(state, _decimal_ratio(gross), _decimal_ratio(commission), _decimal_ratio(net)))
        exact_profits.append((state, net))
    capital = sum((Fraction(p.stake) * (Fraction(p.decimal_odds) - 1 if p.market_key in LAY_MARKETS else 1)
                   for p in positions), Fraction(0))
    expected = None if weights is None else sum((weights[state] * value for state, value in exact_profits), Fraction(0))
    return PayoffResult(model_id, probability_basis, probability_model_id,
                        None if weights is None else tuple((s, _decimal_ratio(weights[s])) for s in sorted(weights)),
                        tuple(replace(p, settlements=tuple(sorted(p.settlements)))
                              for p in sorted(positions, key=lambda p: p.position_id)), tuple(rows), _decimal_ratio(capital),
                        _decimal_ratio(min(v for _, v in exact_profits)), _decimal_ratio(max(v for _, v in exact_profits)),
                        None if expected is None else _decimal_ratio(expected),
                        None if expected is None else _decimal_ratio(expected / capital))
