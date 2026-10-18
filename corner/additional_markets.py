"""Reviewed full-game event markets; acquisition and contract identities stay explicit."""
ADDITIONAL_MARKETS = ('alternate_spreads', 'alternate_totals', 'btts', 'draw_no_bet', 'team_totals')
SCHEDULED_ADDITIONAL_MARKETS = ADDITIONAL_MARKETS
ADDITIONAL_MARKETS += ('alternate_team_totals',)
MARKET_TYPES = {'alternate_spreads':'alternate_spread', 'alternate_totals':'alternate_total',
                'alternate_team_totals':'alternate_team_total', 'btts':'btts', 'draw_no_bet':'draw_no_bet', 'team_totals':'team_total'}
LINE_MARKETS = {'spreads','totals','alternate_spreads','alternate_totals','team_totals','alternate_team_totals'}
SPREAD_MARKETS = {'spreads','alternate_spreads'}
TOTAL_MARKETS = {'totals','alternate_totals','team_totals','alternate_team_totals'}
def coordinate(key):
    return 'spreads' if key in SPREAD_MARKETS else 'totals' if key in TOTAL_MARKETS else None

# Props share the exact binary payoff calculators, while retaining their own keys.
from corner.prop_markets import FAMILIES
PROP_KEYS = frozenset(m.key for family in FAMILIES.values() for m in family)
PROP_LINE_KEYS = frozenset(m.key for family in FAMILIES.values() for m in family if m.sides == ('Over', 'Under'))
LINE_MARKETS.update(PROP_LINE_KEYS)
TOTAL_MARKETS.update(PROP_LINE_KEYS)
