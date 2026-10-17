"""Reviewed fee boundaries and deterministic no-vig estimates, not fitted probabilities.

Account fees change execution returns, not the market prices used to infer consensus.
Unknown fees must never become an implicit zero-fee financial opportunity.
"""
from dataclasses import dataclass
from decimal import Decimal, localcontext, ROUND_CEILING, ROUND_HALF_EVEN
import os
from functools import lru_cache

D = Decimal
VERSION = 'reviewed-pricing/2026-10-16.1'
SPORTSBOOKS = frozenset({'draftkings', 'fanduel', 'espnbet', 'betmgm', 'betrivers', 'pinnacle'})
DFS = frozenset({'prizepicks', 'underdog'})


@dataclass(frozen=True)
class FeePolicy:
    status: str
    commission: Decimal | None
    basis: str


def fee_policy(book):
    if book in SPORTSBOOKS:
        return FeePolicy('modeled', D(0), 'fixed_odds_straight')
    if book == 'novig':
        return FeePolicy('modeled', D(0), 'pregame_straight_only')
    if book == 'prophetx':
        return FeePolicy('modeled', D('.02'), 'positive_market_net_gains')
    if book.startswith('betfair_ex_'):
        raw = os.environ.get('CORNER_BETFAIR_COMMISSION', '')
        try:
            rate = D(raw)
            if rate.is_finite() and D(0) <= rate <= D('.2'):
                return FeePolicy('modeled', rate, 'operator_configured_market_net_rate')
        except Exception:
            pass
        return FeePolicy('requires_account_rate', None, 'account_and_market_dependent')
    if book in DFS:
        return FeePolicy('requires_lineup_payoff', None, 'indicative_dfs_prices')
    if book in {'kalshi', 'polymarket', 'polymarket_us'}:
        return FeePolicy('requires_contract_fee_context', None, 'venue_series_quantity_and_rounding')
    return FeePolicy('unverified', None, 'fee_basis_not_verified')


def reference_eligible(book):
    # Provider DFS odds are indicative assigned prices, not standalone market probabilities.
    return book not in DFS


def contract_fee(*, venue, price, quantity, coefficient, quantum, rounding):
    """Explicit single-fill buy fee. No implied venue/product/series classification.

    Caller supplies the current venue/series coefficient and verified rounding.
    This utility does not authorize feed use without those execution inputs.
    """
    if venue not in {'kalshi', 'polymarket_us', 'polymarket'}:
        raise ValueError('explicit supported venue required')
    values = (price, quantity, coefficient, quantum)
    if any(type(v) is not Decimal or not v.is_finite() for v in values):
        raise ValueError('finite exact decimals required')
    if not (0 < price < 1 and quantity > 0 and 0 <= coefficient <= 1 and quantum > 0):
        raise ValueError('invalid contract fee inputs')
    if rounding not in {ROUND_CEILING, ROUND_HALF_EVEN}:
        raise ValueError('explicit rounding required')
    with localcontext() as ctx:
        ctx.prec = 60
        fee = coefficient * quantity * price * (1-price)
        # Kalshi's centicent rule rounds combined position cost + fee, not fee alone.
        cost = quantity * price
        if venue == 'kalshi':
            return ((cost+fee) / quantum).to_integral_value(rounding=rounding) * quantum - cost
        return (fee / quantum).to_integral_value(rounding=rounding) * quantum


@lru_cache(maxsize=8192)
def no_vig_pair(first, second):
    """Power no-vig with proportional sensitivity comparator over an exact binary pair.

    q0**k + q1**k = 1 has one positive root for valid odds. No probabilities
    for a missing opposite selection, pushes, or invalidations are manufactured.
    """
    with localcontext() as ctx:
        ctx.prec = 60
        odds = tuple(D(str(x)) for x in (first, second))
        if any(not x.is_finite() or x <= 1 or x > D('1e12') or x.as_tuple().exponent < -12 for x in odds):
            raise ValueError('valid paired decimal odds required')
        q = tuple(1/x for x in odds)
        total = sum(q)
        proportional = q[0] / total
        if odds[0] == odds[1]:
            return (D('.5'), D('.5')), (D('.5'), D('.5'))
        low, high = D(0), D(1)
        while sum(x**high for x in q) > 1:
            high *= 2
        for _ in range(180):
            mid = (low+high)/2
            if sum(x**mid for x in q) > 1:
                low = mid
            else:
                high = mid
        first_probability = q[0] ** ((low+high)/2)
        return (first_probability, 1-first_probability), (proportional, 1-proportional)
