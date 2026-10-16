"""American-odds width for complete two-sided reference markets, in cents."""
from decimal import Decimal


def widest_market_width(groups):
    widths = []
    for prices in groups:
        if len(prices) != 2:
            return None
        prices = [Decimal(p) for p in prices]
        if any(not p.is_finite() or p <= 1 for p in prices):
            return None
        cents = [100 * (p - 2) if p >= 2 else 100 - 100 / (p - 1) for p in prices]
        widths.append(abs(sum(cents)))
    return str(max(widths).quantize(Decimal('0.000001'))) if widths else None
