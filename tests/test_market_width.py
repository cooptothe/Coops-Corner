import unittest
from decimal import Decimal as D
from corner.market_width import widest_market_width
from corner.prop_markets import build_bets


class MarketWidthTests(unittest.TestCase):
    def test_cents_cross_even_money_and_use_widest_reference(self):
        self.assertEqual('20.000000', widest_market_width([[D('2.2'), 1 + D(100)/140], [D(2), D(2)]]))
        self.assertEqual('20.000000', widest_market_width([[1 + D(100)/110] * 2]))
        self.assertEqual('0.000000', widest_market_width([[D(2), D(2)]]))

    def test_incomplete_or_nonbinary_reference_has_no_width(self):
        for groups in ([], [[D(2)]], [[D(2), D(3), D(4)]], [[D(1), D(2)]]):
            self.assertIsNone(widest_market_width(groups))

    def test_props_width_comes_from_references_not_the_target(self):
        quotes = [dict(book=b, player='Player', point='20.5', side=s, price=p)
                  for b, prices in [('draftkings', ['2.5', '1.4']), ('fanduel', ['2', '2']),
                                    ('pinnacle', ['1.90909090909', '1.90909090909'])]
                  for s, p in enumerate(prices)]
        event = dict(sport_key='basketball_nba', home_team='Home', away_team='Away',
                     commence_time='2030-01-01T00:00:00Z', markets={'player_points': {'quotes': quotes}})
        bets = [b for b in build_bets({'event': event}) if b['book'] == 'draftkings']
        self.assertEqual(2, len(bets))
        self.assertTrue(all(b['market_width_cents'] == '20.000000' for b in bets))
        event['markets']['player_points']['quotes'] = [q for q in quotes if not(q['book'] == 'pinnacle' and q['side'] == 1)]
        bets = [b for b in build_bets({'event': event}) if b['book'] == 'draftkings']
        self.assertTrue(bets)
        self.assertTrue(all(b['market_width_cents'] is None for b in bets))
