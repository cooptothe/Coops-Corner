"""Versioned reputation priors, not fitted accuracy or verified liquidity scores.

Weights are relative influence after each book is devigged. Missing books do not
contribute, and callers exclude the target before normalizing. No closing prices
or future observations are used to estimate current EV.
"""
from decimal import Decimal
from corner.book_policy import supported_book

WEIGHT_VERSION = 'reputation-priors/5-expanded-props'
EXCHANGES = frozenset({'betfair_ex_uk', 'betfair_ex_eu', 'betfair_ex_au'})
OTHER_EXCHANGES = frozenset({'prophetx', 'kalshi', 'betopenly', 'polymarket', 'novig'})

# Interpret the supplied guide as conservative relative tiers, not measured facts.
MAIN_PROFILES = {
    'soccer': {'pinnacle': '4', 'betfair_exchange': '3'},
    'tennis': {'pinnacle': '4', 'betfair_exchange': '3'},
    'basketball': {'pinnacle': '4', 'betfair_exchange': '1'},
    'baseball': {'pinnacle': '4', 'betfair_exchange': '1'},
    'americanfootball': {'pinnacle': '4', 'betfair_exchange': '1'},
    'icehockey': {'pinnacle': '5', 'betfair_exchange': '1'},
    'mma': {'pinnacle': '3', 'betfair_exchange': '1'},
    'boxing': {'pinnacle': '3', 'betfair_exchange': '1'},
}
MAJOR_PROP_FAMILIES = frozenset({'basketball', 'americanfootball', 'baseball', 'icehockey'})

def reference_weight(book, sport_key='', *, player_props=False):
    if not supported_book(book):
        return Decimal('0')
    # Legacy calculator callers and synthetic fixtures retain equal weighting.
    if not sport_key:
        return Decimal('1')
    family = sport_key.split('_', 1)[0]
    if player_props:
        if book == 'fanduel':
            return Decimal('5' if family in MAJOR_PROP_FAMILIES else '4' if family == 'soccer' else '2')
        if book == 'pinnacle':
            return Decimal('2')
        if book in EXCHANGES:
            return Decimal('2' if family == 'soccer' else '1')
        return Decimal('1')
    # The guide does not establish a dominant WNBA or challenger benchmark.
    if sport_key == 'basketball_wnba' or 'challenger' in sport_key:
        return Decimal('1')
    # Owner-selected main references; unit weight is a policy prior, not a
    # claim of empirically established sharpness or equivalence to Pinnacle.
    if book in {'betonlineag', 'bovada'}:
        return Decimal('1')
    profile = MAIN_PROFILES.get(family, {})
    key = 'betfair_exchange' if book in EXCHANGES else book
    return Decimal(profile.get(key, '0.5' if book in OTHER_EXCHANGES else '1'))

def normalized_reference_weights(books, sport_key='', *, player_props=False):
    weights = {book: reference_weight(book, sport_key, player_props=player_props) for book in books if supported_book(book)}
    total = sum(weights.values(), Decimal(0))
    return {book: weight / total for book, weight in weights.items()} if total else {}
