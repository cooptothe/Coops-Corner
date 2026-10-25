"""Researched, versioned policy priors; not fitted accuracy or liquidity scores.

Every supported book may contribute comparable prices. Each book is devigged
before pooling; targets are excluded by callers. Sparse research gets a modest
baseline, not a fabricated sport/stat-specific superiority claim. No network.
"""
from decimal import Decimal
from functools import lru_cache
from collections import Counter
from corner.reference_policy import reference_source
from corner.book_policy import supported_book, props_book_eligible
from corner.pricing import SPORTSBOOKS

WEIGHT_VERSION = 'configured-policy-priors/8-ev-anchors-2026-10-25'
EXCHANGES = frozenset({'betfair_ex_uk','betfair_ex_eu','betfair_ex_au'})
OTHER_EXCHANGES = frozenset({'prophetx','kalshi','betopenly','polymarket','polymarket_us','novig'})
REFERENCE_BOOKS = SPORTSBOOKS | EXCHANGES | OTHER_EXCHANGES

# Owner-configured top tier for non-prop Positive EV, including alternate lines.
# This is a product policy ratio, not a claim of measured forecasting accuracy.
EV_ANCHORS = frozenset({'pinnacle','kalshi','novig'})
EV_ANCHOR_WEIGHT = Decimal('4')

# Other market reputation priors retained where research supports an anchor.
# Numbers are our policy ratios, not measured prediction accuracy.
MAIN_PROFILES = {
 'soccer': {'pinnacle':'4','betfair_exchange':'3'},
 'tennis': {'pinnacle':'4','betfair_exchange':'3'},
 'basketball': {'pinnacle':'4','betfair_exchange':'1'},
 'baseball': {'pinnacle':'4','betfair_exchange':'1'},
 'americanfootball': {'pinnacle':'4','betfair_exchange':'1'},
 'icehockey': {'pinnacle':'5','betfair_exchange':'1'},
 'mma': {'pinnacle':'3','betfair_exchange':'1'},
 'boxing': {'pinnacle':'3','betfair_exchange':'1'},
}
# Outlier publishes NBA 100:25 and MLB 75:50:25 examples; NFL's named
# anchors are equal. Lower baseline for other books is our conservative prior.
PROP_PROFILES = {
 'basketball_nba': {'fanduel':'4','pinnacle':'1','draftkings':'1','williamhill_us':'1','betonlineag':'1'},
 'baseball_mlb': {'fanduel':'3','pinnacle':'2','draftkings':'1','williamhill_us':'1','betonlineag':'1'},
 'americanfootball_nfl': {'fanduel':'2','pinnacle':'2','betonlineag':'2','draftkings':'1','williamhill_us':'1'},
}
MAIN_KEYS = frozenset({'h2h','spreads','totals','h2h_lay','spreads_lay','totals_lay'})


@lru_cache(maxsize=8192)
def reference_weight(book, sport_key='', *, player_props=False, market_key=''):
    if not supported_book(book) or player_props and not props_book_eligible(book):return Decimal(0)
    if not sport_key:return Decimal(1)  # Legacy pure-calculator fixtures.
    family=sport_key.split('_',1)[0]
    if player_props:
        if book in EXCHANGES or book in OTHER_EXCHANGES:return Decimal('0.5')
        # No verified stat-by-stat ranking: an ATD, ATG or alternate line does
        # not inherit an invented extra sharpness multiplier.
        profile=PROP_PROFILES.get(sport_key,{})
        return Decimal(profile.get(book,'0.5' if profile else '1'))
    if book in EV_ANCHORS:return EV_ANCHOR_WEIGHT
    if sport_key=='basketball_wnba' or 'challenger' in sport_key:
        return Decimal('0.5' if book in OTHER_EXCHANGES else '1')
    key='betfair_exchange' if book in EXCHANGES else book
    profile=MAIN_PROFILES.get(family,{})
    weight=Decimal(profile.get(key,'0.5' if book in OTHER_EXCHANGES else '1'))
    # Liquid main-market reputation is not evidence for an equally strong
    # alternate/team-total/BTTS/DNB exchange book. Keep it eligible, cautiously.
    if market_key and market_key not in MAIN_KEYS and book in EXCHANGES:
        return min(weight,Decimal(1))
    return weight


def normalized_reference_weights(books, sport_key='', *, player_props=False, market_key=''):
    books=tuple(dict.fromkeys(b for b in books if supported_book(b) and (not player_props or props_book_eligible(b))))
    counts=Counter(reference_source(b) for b in books)
    weights={b:reference_weight(b,sport_key,player_props=player_props,market_key=market_key)/counts[reference_source(b)] for b in books}
    total=sum(weights.values(),Decimal(0))
    return {b:w/total for b,w in weights.items()} if total else {}
