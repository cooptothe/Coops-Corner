import unittest
from decimal import Decimal as D
from api.catalog import FixtureCatalog
from api.database import build_raw
from corner.featured_ev import calculate_featured_ev
from corner.featured_tools import MatchedMarket, Offer, ToolInputError
from corner.prop_markets import build_bets, normalize_event, market_meta
from tests.test_database_catalog import q, PEOPLE, NOW

class SoccerReferences(unittest.TestCase):
    def main_catalog(self, book, sport='soccer_epl', draw=True):
        rows = [dict(q(b, 'moneyline', side, odds), competition_code=sport)
                for b in (book, 'draftkings')
                for side, odds in [('home', '4.0' if b == 'draftkings' else '3.0'), ('away', '3.0'), *([('draw', '3.0')] if draw else [])]]
        return FixtureCatalog(raw=build_raw(rows, PEOPLE, now=NOW, references=(book,)))

    def test_soccer_main_lines_allow_only_approved_single_book(self):
        for book in ('pinnacle', 'betfair_ex_uk'):
            rows = [r for r in self.main_catalog(book).rows if r.kind == 'positive_ev']
            self.assertTrue(rows)
            self.assertEqual([book], [b.sportsbook_id for b in rows[0].calculation.reference_books])
        for book in ('polymarket', 'kalshi', 'betopenly', 'prophetx'):
            self.assertFalse([r for r in self.main_catalog(book).rows if r.kind == 'positive_ev'])

    def test_other_sports_still_require_two(self):
        self.assertFalse([r for r in self.main_catalog('pinnacle', 'basketball_nba', False).rows if r.kind == 'positive_ev'])

    def test_calculator_requires_complete_reference_and_never_self_references(self):
        market = MatchedMarket('c', 'h2h', ('home', 'away', 'draw'), False)
        refs = [Offer('r'+side, 'c', 'h2h', side, 'pinnacle', D(3), D(0)) for side in market.selection_ids]
        target = Offer('target', 'c', 'h2h', 'home', 'draftkings', D(4), D(0))
        with self.assertRaises(ToolInputError):
            calculate_featured_ev(market, target, refs[:-1], required_reference_books=('pinnacle',), sport_key='soccer_epl')
        with self.assertRaises(ToolInputError):
            calculate_featured_ev(market, refs[0], refs, required_reference_books=('pinnacle',), sport_key='soccer_epl')
        with self.assertRaises(ToolInputError):
            calculate_featured_ev(market, target, refs, required_reference_books=('pinnacle',))

    def props(self, book, sport):
        key = 'player_shots' if sport.startswith('soccer_') else 'player_points'
        meta = market_meta(sport, key)
        payload = {'bookmakers': [{'key': b, 'markets': [{'key': key, 'outcomes': [
            {'name': side, 'description': 'Player', 'point': 2.5, 'price': 2.2 if b == 'draftkings' else 1.91}
            for side in ('Over', 'Under')]}]} for b in (book, 'draftkings')]}
        return build_bets({'e': {'sport_key': sport, 'home_team': 'H', 'away_team': 'A',
            'commence_time': '2030-01-01T00:00:00Z', 'markets': {key: {'captured_at': 'x', 'quotes': normalize_event(payload, key, meta)}}}})

    def test_soccer_props_use_same_exception_and_exclude_self(self):
        for book in ('pinnacle', 'betfair_ex_uk'):
            bets = self.props(book, 'soccer_epl')
            self.assertTrue(bets)
            self.assertEqual({'draftkings'}, {b['book'] for b in bets})
            self.assertTrue(all(b['sharps'] == [book] for b in bets))
        self.assertEqual([], self.props('polymarket', 'soccer_epl'))
        self.assertEqual([], self.props('pinnacle', 'basketball_nba'))

    def test_fanduel_single_reference_is_only_for_soccer_props(self):
        bets = self.props('fanduel', 'soccer_epl')
        self.assertTrue(bets)
        self.assertEqual({'draftkings'}, {b['book'] for b in bets})
        self.assertTrue(all(b['sharps'] == ['fanduel'] for b in bets))
        self.assertEqual([], self.props('fanduel', 'basketball_nba'))
        self.assertFalse([r for r in self.main_catalog('fanduel').rows if r.kind == 'positive_ev'])
