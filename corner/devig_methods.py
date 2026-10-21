"""Margin-model sensitivity, never a change to the product's headline policy."""
from decimal import Decimal as D, localcontext
from functools import lru_cache
from corner.pricing import no_vig_pair


@lru_cache(maxsize=4096)
def distributions(odds):
    """Immutable complete-market distributions. Invalid additive/Shin are omitted."""
    with localcontext() as ctx:
        ctx.prec = 40
        if len(odds) < 2 or any(not isinstance(x, D) or not x.is_finite() or x <= 1 or x > D('1e12') or x.as_tuple().exponent < -12 for x in odds):
            raise ValueError('complete validated decimal odds required')
        q = tuple(1/x for x in odds)
        total = sum(q)
        result = [('multiplicative', tuple(x/total for x in q))]
        additive = tuple(x-(total-1)/len(q) for x in q)
        if all(0 <= x <= 1 for x in additive):
            result.append(('additive', additive))
        if len(odds) == 2:
            power, _ = no_vig_pair(*odds)
        elif len(set(odds)) == 1:
            power = tuple(D(1)/len(q) for _ in q)
        else:
            logs = tuple(x.ln() for x in q)
            low, high = D(0), D(1)
            def terms(k):
                return tuple((k*x).exp() for x in logs)
            while sum(terms(high)) > 1:
                high *= 2
            for _ in range(110):
                k = (low+high)/2
                if sum(terms(k)) > 1: low = k
                else: high = k
            power = terms((low+high)/2)
        result.append(('power', power))
        # Classical nonnegative informed-fraction Shin model requires overround.
        if total >= 1:
            if len(odds) == 2:
                shin = additive
            elif total == 1:
                shin = q
            else:
                def shin_terms(z):
                    return tuple(((z*z+4*(1-z)*x*x/total).sqrt()-z)/(2*(1-z)) for x in q)
                low, high = D(0), D(1)-D('1e-30')
                for _ in range(110):
                    z = (low+high)/2
                    if sum(shin_terms(z)) > 1: low = z
                    else: high = z
                shin = shin_terms((low+high)/2)
            result.append(('shin', shin))
        return tuple(result)


@lru_cache(maxsize=4096)
def pooled_distributions(populations):
    """Devig each complete book first, then pool the same reference weights."""
    with localcontext() as ctx:
        ctx.prec = 40
        if not populations:
            raise ValueError('complete reference populations required')
        modeled = [(dict(distributions(odds)), weight) for odds, weight in populations]
        names = [name for name in ('multiplicative', 'additive', 'power', 'shin')
                 if all(name in models for models, _ in modeled)]
        total = sum(weight for _, weight in modeled)
        n = len(populations[0][0])
        if not total > 0 or any(len(odds) != n or weight <= 0 for odds, weight in populations):
            raise ValueError('positive weights and matching populations required')
        result = [(name, tuple(sum(models[name][side]*weight for models, weight in modeled)/total
                              for side in range(n))) for name in names]
        # Per-outcome minima are stress estimates, not a normalized distribution.
        result.append(('worst_case', tuple(min(p[side] for _, p in result) for side in range(n))))
        return tuple(result)


def comparisons(populations, side, odds, commission=D(0), *, lay=False):
    with localcontext() as ctx:
        ctx.prec = 40
        distributions = pooled_distributions(populations)
        rows = []
        for name, values in distributions:
            p = max(v[side] for n, v in distributions if n != 'worst_case') if lay and name == 'worst_case' else values[side]
            ev = (1-p)*(1-commission)/(odds-1)-p if lay else p*(1+(odds-1)*(1-commission))-1
            rows.append({'method': name, 'probability': p.quantize(D('1e-12')), 'ev': ev.quantize(D('1e-12'))})
        return tuple(rows)
