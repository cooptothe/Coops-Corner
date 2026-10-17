"""One-sided scorer sensitivity research, separate from certified prediction.

For binary quotes q_yes=p+v_yes, q_no=1-p+v_no with v>=0 and
v_yes+v_no<=H, p lies in [max(0,q_yes-H), q_yes]. This is an
assumption-conditional identification interval, not a confidence interval.
"""
import math
from decimal import Decimal as D


def allocation_bounds(implied, maximum_overround):
    q, high = D(str(implied)), D(str(maximum_overround))
    if not q.is_finite() or not high.is_finite() or not 0 < q < 1 or not 0 <= high <= D('.5'):
        raise ValueError('Finite implied probability and explicit overround bound required.')
    return max(D(0), q-high), q


def scorer_sensitivity(references, *, net_decimal_odds):
    """Explicit reference weights, prices and assumed overround ceilings only.

    Each input is already an eligible non-target reference on the same contract.
    No inferred precision, liquidity or data independence is claimed.
    """
    odds=D(str(net_decimal_odds))
    if not odds.is_finite() or odds<=1 or len(references)<2:
        raise ValueError('Two references and finite net decimal odds >1 required.')
    total=D(0); low=D(0); upper=D(0)
    for ref in references:
        price,weight=D(str(ref['price'])),D(str(ref['weight']))
        if not price.is_finite() or price<=1 or not weight.is_finite() or weight<=0:
            raise ValueError('Finite reference prices >1 and positive weights required.')
        lower,higher=allocation_bounds(1/price,ref['maximum_overround'])
        total+=weight;low+=weight*lower;upper+=weight*higher
    low/=total;upper/=total
    return {'probability_min':str(low),'probability_max':str(upper),
            'ev_min':str(low*odds-1),'ev_max':str(upper*odds-1),
            'basis':'assumed_nonnegative_vig_allocation_bounds',
            'confidence_interval':False,'empirically_calibrated':False}


def poisson_anytime(rate):
    """P(N>=1) for a supplied expected count; rate is not inferred from odds."""
    if not math.isfinite(rate) or rate<0:raise ValueError('Finite nonnegative rate required.')
    return -math.expm1(-rate)


def negative_binomial_anytime(rate, dispersion):
    """Gamma-Poisson mixture: tests sensitivity to count overdispersion."""
    if not math.isfinite(rate) or rate<0 or not math.isfinite(dispersion) or dispersion<=0:
        raise ValueError('Finite rate and positive dispersion required.')
    return -math.expm1(-dispersion*math.log1p(rate/dispersion))
