"""Closing-line value: how the price a bet took compares with the sharp market's last price before the game.

Pure math over closing rows already fetched from the odds ledger. A closing price is only used when
sharp books priced the very same line on every side, and probabilities are the proportional no-vig
shares, so the result is a fair-price comparison rather than a line-movement guess.
"""
from decimal import Decimal, ROUND_HALF_UP

MAIN_MARKETS = ('h2h', 'spreads', 'totals')
OPPOSITE = {'home': 'away', 'away': 'home', 'over': 'under', 'under': 'over'}
NO_CLOSE = 'No sharp closing price was captured for this exact line before the game started'


def _six(value):
    return format(Decimal(value).quantize(Decimal('0.000001'), ROUND_HALF_UP).normalize(), 'f')


def devig(prices):
    """Proportional no-vig probabilities for a complete set of decimal odds."""
    inverse = [1 / Decimal(p) for p in prices]
    total = sum(inverse)
    return [i / total for i in inverse]


def _by_book(rows, sharps):
    books = {}
    for row in rows:
        if row['book'] in sharps:
            books.setdefault(row['book'], []).append(row)
    return books


def fair_probability(market_key, side, point, rows, sharps):
    """(mean fair probability of `side`, books used) from closing rows, or None if the line was not priced."""
    if market_key not in MAIN_MARKETS:
        return None
    point = None if point is None else Decimal(str(point))
    shares, used = [], []
    for book, cells in sorted(_by_book(rows, sharps).items()):
        by = {}
        for c in cells:
            by[(c['side'], None if c['point'] is None else Decimal(str(c['point'])))] = Decimal(c['decimal_odds'])
        if market_key == 'h2h':
            sides = ['home', 'away'] + (['draw'] if any(s == 'draw' for s, _ in by) else [])
            keys = [(s, None) for s in sides]
            if side not in sides:
                continue
        else:
            if point is None or side not in OPPOSITE:
                return None
            other = OPPOSITE[side]
            if market_key == 'spreads':
                keys = [(side, point), (other, -point)]
            else:
                keys = [(side, point), (other, point)]
        if any(k not in by for k in keys):
            continue
        probs = devig([by[k] for k in keys])
        shares.append(probs[[k[0] for k in keys].index(side)])
        used.append(book)
    if not shares:
        return None
    return sum(shares) / len(shares), used


def measure(ref, our_decimal, rows, sharps, *, at):
    """The CLV record to store for a bet, always with a reason when it cannot be measured."""
    found = fair_probability(ref.get('market_key'), ref.get('side'), ref.get('point'), rows, sharps)
    if not found:
        return {'pct': None, 'reason': NO_CLOSE, 'at': at}
    fair, books = found
    return {'pct': _six(Decimal(our_decimal) * fair - 1), 'fair_prob': _six(fair), 'close_odds': _six(1 / fair),
            'books': books, 'at': at}
