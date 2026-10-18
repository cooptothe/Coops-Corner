"""Cross-line featured spreads/totals over an explicit integer score coordinate.

Totals use total points >= 0; spreads use HOME minus AWAY margin (all integers).
The caller must establish common event, scope, scoring and settlement semantics.
Quarter lines split equally over adjacent half lines; no distribution is guessed.
"""
from dataclasses import dataclass
from functools import lru_cache
from types import SimpleNamespace
from decimal import Decimal
from fractions import Fraction

from corner.featured_payoffs import Settlement, REFUND, PayoffPosition, PayoffResult, calculate_payoffs
from corner.featured_tools import _id, _require, _decimal, _decimal_ratio, _cash_units

FORMAT = "corner.featured_middles/1"


@dataclass(frozen=True)
class LineBet:
    quote_id: str
    sportsbook_id: str
    contract_id: str  # common event/scope/rules coordinate, excluding offered line
    market_key: str
    side: str
    line: Decimal
    decimal_odds: Decimal
    stake: Decimal
    commission_rate: Decimal

    def __post_init__(self):
        _id(self.quote_id)
        _id(self.sportsbook_id)
        _id(self.contract_id)
        _require(self.market_key in {"spreads", "totals"}, "middle requires featured spread or total")
        _require(self.side in ({"home", "away"} if self.market_key == "spreads" else {"over", "under"}),
                 "side does not match market")
        _require(isinstance(self.line, Decimal) and self.line.is_finite(), "finite Decimal line required")
        _require(self.line.copy_abs() <= 1000000 and self.line.as_tuple().exponent >= -12,
                 "line magnitude <= 1000000 and at most 12 fractional digits")
        _require((Fraction(self.line) * 4).denominator == 1,
                 "integer, half or quarter line required; magnitude <= 1000000")
        _require(self.market_key != "totals" or self.line >= 0, "negative total")
        _decimal(self.decimal_odds, "odds", positive=True)
        _require(self.decimal_odds > 1, "odds must exceed one")
        _decimal(self.stake, "stake", positive=True)
        _decimal(self.commission_rate, "commission")
        _require(self.commission_rate < 1, "invalid commission")


def _lines(leg):
    line = Fraction(leg.line)
    if (line * 2).denominator == 1:
        return (line,)
    lower = (line * 2).__floor__() / Fraction(2)
    return (lower, lower + Fraction(1, 2))


def _thresholds(leg):
    return tuple(-line if leg.side == "home" else line for line in _lines(leg))


def _settle(leg, score):
    return _settle_line(leg.line, leg.side, score)


@lru_cache(maxsize=32768)
def _settle_line(line, side, score):
    # Settlement depends on geometry, never on quote/player/book identity.
    leg = SimpleNamespace(line=line, side=side)
    wins = losses = 0
    thresholds = _thresholds(leg)
    for threshold in thresholds:
        difference = score - threshold
        if leg.side in {"away", "under"}:
            difference = -difference
        wins += difference > 0
        losses += difference < 0
    n = len(thresholds)
    return Settlement(_decimal_ratio(Fraction(wins, n)), _decimal_ratio(Fraction(losses, n)),
                      _decimal_ratio(Fraction(n - wins - losses, n)))


@dataclass(frozen=True)
class MiddleRange:
    state_id: str
    minimum_score: int | None
    maximum_score: int | None
    first_settlement: Settlement
    second_settlement: Settlement
    both_win: bool


@dataclass(frozen=True)
class MiddleResult:
    contract_id: str
    coordinate: str
    legs: tuple[LineBet, LineBet]
    ranges: tuple[MiddleRange, ...]
    double_win_ranges: tuple[tuple[int | None, int | None], ...]
    payoff: PayoffResult
    format: str = FORMAT
    availability_verified: bool = False


def calculate_middle(*, contract_id, first, second, refund_possible,
                     stake_increment=Decimal("0.01"), state_probabilities=None, probability_model_id=None):
    """Return a complete range payoff table even when there is no double-win window.

    Separate sportsbooks only: no guessed cross-line exchange commission netting.
    Probabilities, if supplied, refer to the returned range IDs and optional
    'common_refund' state. They must cover all states and sum to one exactly.
    Refund flag asserts COMMON full-stake invalidation; asymmetric voids need an
    explicit featured_payoffs model instead. Stakes are input, not recommended.
    """
    _id(contract_id)
    _require(type(first) is LineBet and type(second) is LineBet, "validated line bets required")
    _require(first.market_key == second.market_key, "mixed middle market families")
    _require(first.contract_id == second.contract_id == contract_id, "incompatible middle event/scope/rules")
    _require({first.side, second.side} == ({"home", "away"} if first.market_key == "spreads" else {"over", "under"}),
             "opposing sides required")
    _require(first.quote_id != second.quote_id and first.sportsbook_id != second.sportsbook_id,
             "distinct quotes and books required")
    _require(type(refund_possible) is bool, "explicit refund branch required")
    for leg in (first, second):
        _cash_units(leg.stake, stake_increment)
    minimum = 0 if first.market_key == "totals" else None
    cuts = set()
    for threshold in _thresholds(first) + _thresholds(second):
        floor = threshold.__floor__()
        cuts.update((floor, floor + 1))
    cuts = sorted(c for c in cuts if minimum is None or c > minimum)
    segments = []
    lower = minimum
    for upper in cuts:
        segments.append((lower, upper - 1))
        lower = upper
    segments.append((lower, None))
    merged = []
    for lower, upper in segments:
        sample = lower if lower is not None else upper
        settlements = (_settle(first, sample), _settle(second, sample))
        if merged and merged[-1][2:] == settlements:
            merged[-1] = (merged[-1][0], upper, *settlements)
        else:
            merged.append((lower, upper, *settlements))
    ranges = tuple(MiddleRange(f"score:{lo if lo is not None else '-inf'}:{hi if hi is not None else '+inf'}",
                               lo, hi, a, b, a.won == 1 and b.won == 1) for lo, hi, a, b in merged)
    states = tuple(r.state_id for r in ranges) + (("common_refund",) if refund_possible else ())
    positions = []
    for i, leg in enumerate((first, second)):
        settlements = tuple((r.state_id, r.first_settlement if i == 0 else r.second_settlement) for r in ranges)
        if refund_possible:
            settlements += (("common_refund", REFUND),)
        positions.append(PayoffPosition(leg.quote_id, leg.market_key, leg.decimal_odds, leg.stake,
                                       leg.sportsbook_id, leg.commission_rate, settlements))
    payoff = calculate_payoffs(model_id=contract_id, state_ids=states, positions=positions,
                              probability_basis="exhaustive_settlement_states", probabilities=state_probabilities,
                              probability_model_id=probability_model_id)
    return MiddleResult(contract_id, "home_minus_away" if first.market_key == "spreads" else "total_points",
                        (first, second), ranges, tuple((r.minimum_score, r.maximum_score) for r in ranges if r.both_win), payoff)


def find_middles(line_bets, *, refund_possible, stake_increment=Decimal("0.01"), maximum_pair_checks=10000):
    """Bounded discovery over explicitly bound quotes; no probability-based ranking.

    Partitions by common event/scope/rules contract and market family. Every
    opposite-side, cross-book pair is checked; returns only full double-win
    windows, in stable quote-identity order. Too large a request fails rather
    than silently dropping books or truncating the candidate population.
    """
    bets = tuple(line_bets)
    _require(type(maximum_pair_checks) is int and 1 <= maximum_pair_checks <= 100000, "invalid pair-check bound")
    _require(len(bets) <= 2000 and all(type(b) is LineBet for b in bets), "at most 2000 validated line bets required")
    _require(len({b.quote_id for b in bets}) == len(bets), "duplicate quote identity")
    _require(type(refund_possible) is bool, "explicit refund branch required")
    groups = {}
    for bet in sorted(bets, key=lambda b: b.quote_id):
        high, low = groups.setdefault((bet.contract_id, bet.market_key), ([], []))
        (high if bet.side in {"home", "over"} else low).append(bet)
    _require(sum(len(high) * len(low) for high, low in groups.values()) <= maximum_pair_checks, "middle pair-check bound exceeded")
    results = []
    for (contract, _), (high, low) in sorted(groups.items()):
        for first in high:
            for second in low:
                if first.sportsbook_id == second.sportsbook_id:
                    continue
                result = calculate_middle(contract_id=contract, first=first, second=second,
                                          refund_possible=refund_possible, stake_increment=stake_increment)
                if result.double_win_ranges:
                    results.append(result)
    return tuple(results)
