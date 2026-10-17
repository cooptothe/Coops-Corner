import os
import unittest
from unittest.mock import patch
from decimal import Decimal as D, ROUND_CEILING, ROUND_HALF_EVEN, localcontext

from corner.pricing import fee_policy, no_vig_pair, contract_fee
from corner.featured_tools import MatchedMarket, Offer, calculate_back_cover
from corner.prop_markets import build_bets
from tests import test_prop_markets as prop_fixtures
from tests.test_database_catalog import q, PEOPLE, NOW
from api.database import build_raw
from api.catalog import FixtureCatalog


class ReviewedPricingTests(unittest.TestCase):
    def test_margin_cannot_create_symmetric_prop_edge(self):
        event = prop_fixtures.FanDuelReference.stored({'fanduel': (1.91, 1.91), 'pinnacle': (1.91, 1.91),
                                        'draftkings': (2, 2)})
        rows = [r for r in build_bets({'e': event}) if r['book'] == 'draftkings']
        self.assertEqual(2, len(rows))
        for row in rows:
            self.assertEqual('0.500000', row['fair_probability'])
            self.assertEqual('0.000000', row['ev'])
            self.assertEqual('not_empirically_calibrated', row['calibration_status'])

    def test_power_root_and_complement_with_asymmetric_prices(self):
        with localcontext() as ctx:
            ctx.prec = 60
            (a, b), (x, y) = no_vig_pair(D('1.4'), D('3.1'))
            self.assertLess(abs(a+b-1), D('1e-50'))
            self.assertEqual(x+y, 1)
            self.assertGreater(a, x)  # power sensitivity allocates more margin to the long shot
            k = a.ln() / (1/D('1.4')).ln()
            self.assertLess(abs((1/D('3.1'))**k-b), D('1e-48'))

    def test_power_symmetric_grid_and_extreme_valid_prices(self):
        for odds in ('1.01', '1.91', '2', '3', '1000'):
            (a, b), _ = no_vig_pair(D(odds), D(odds))
            self.assertAlmostEqual(float(a), .5, places=14)
            self.assertAlmostEqual(float(b), .5, places=14)
        for value in ('NaN', 'Infinity', '1', '0', '1.00000000000000001'):
            with self.assertRaises(ValueError):
                no_vig_pair(D(value), D(2))

    def test_fees_are_not_all_zero_and_unknown_is_not_free(self):
        self.assertEqual(D('.02'), fee_policy('prophetx').commission)
        self.assertEqual(D(0), fee_policy('novig').commission)
        with patch.dict(os.environ, {'CORNER_BETFAIR_COMMISSION': ''}):
            for book in ('betfair_ex_uk', 'kalshi', 'polymarket', 'polymarket_us', 'betopenly', 'prizepicks', 'underdog'):
                self.assertIsNone(fee_policy(book).commission, book)
        with patch.dict(os.environ, {'CORNER_BETFAIR_COMMISSION': '.02'}):
            self.assertEqual(D('.02'), fee_policy('betfair_ex_uk').commission)
        for invalid in ('NaN', '-.1', '1', 'garbage'):
            with patch.dict(os.environ, {'CORNER_BETFAIR_COMMISSION': invalid}):
                self.assertIsNone(fee_policy('betfair_ex_uk').commission)

    def test_official_contract_fee_examples_and_distinct_rounding(self):
        common = dict(price=D('.5'), quantity=D(100), quantum=D('.01'))
        self.assertEqual(D('1.75'), contract_fee(venue='kalshi', coefficient=D('.07'), rounding=ROUND_CEILING, **common))
        self.assertEqual(D('1.74'), contract_fee(venue='polymarket_us', coefficient=D('.0695'), rounding=ROUND_HALF_EVEN, **common))
        self.assertEqual(D('1.25'), contract_fee(venue='polymarket', coefficient=D('.05'), rounding=ROUND_HALF_EVEN, **common))
        # Centicent fee + position cost rounding, not an assumed old whole-cent rule.
        self.assertEqual(D('.0175'), contract_fee(venue='kalshi', price=D('.4999'), quantity=D(1),
                          coefficient=D('.07'), quantum=D('.0001'), rounding=ROUND_CEILING))

    def test_commission_removes_apparent_cover_profit(self):
        market = MatchedMarket('c', 'h2h', ('a', 'b'), False)
        offers = [Offer('a', 'c', 'h2h', 'a', 'prophetx', D('2.01'), D('.02')),
                  Offer('b', 'c', 'h2h', 'b', 'draftkings', D('2.01'), D(0))]
        result = calculate_back_cover(market, offers, total_stake=D(200))
        self.assertFalse(result.decisive_arbitrage)
        self.assertLess(result.minimum_decisive_profit, 0)

    def test_unknown_fee_quotes_remain_visible_but_cannot_create_profit_rows(self):
        rows = [q(b, 'moneyline', s, odds) for b, odds in [('kalshi','3'), ('pinnacle','2'), ('prophetx','2')]
                for s in ('home','away')]
        cat = FixtureCatalog(raw=build_raw(rows, PEOPLE, now=NOW))
        unknown = {q.id for q in cat.quotes if q.sportsbook_id == 'kalshi'}
        self.assertEqual(2, len(unknown))
        self.assertTrue(all(q.fee_status == 'requires_contract_fee_context' for q in cat.quotes if q.id in unknown))
        self.assertFalse(any(r.kind == 'arbitrage' for r in cat.rows))
        self.assertFalse(any(r.calculation.target_quote_id in unknown for r in cat.rows if r.kind == 'positive_ev'))

    def test_props_fee_and_sensitivity_applied_to_ev(self):
        event = prop_fixtures.FanDuelReference.stored({'fanduel': (1.91, 1.91), 'pinnacle': (1.91, 1.91), 'prophetx': (2,2)})
        rows = [r for r in build_bets({'e': event}) if r['book'] == 'prophetx']
        self.assertEqual(2, len(rows))
        self.assertTrue(all(D(r['ev']) == D('-.01') and D(r['net_decimal_odds']) == D('1.98') for r in rows))

    def test_one_sided_and_dfs_cannot_supply_missing_probability(self):
        event = prop_fixtures.FanDuelReference.stored({'prizepicks': (2,2), 'underdog':(2,2), 'draftkings':(3,3)})
        self.assertEqual([], build_bets({'e':event}))

    def test_duplicate_reference_side_is_not_silently_overwritten(self):
        event = prop_fixtures.FanDuelReference.stored({'pinnacle':(2,2), 'fanduel':(2,2), 'draftkings':(3,3)})
        quotes = event['markets']['player_points']['quotes']
        quotes.append(dict(quotes[0], price='4'))
        self.assertEqual([], build_bets({'e': event}))
        event = prop_fixtures.FanDuelReference.stored({'pinnacle': (2,2), 'fanduel': (2,2), 'draftkings': (3,3)})
        event['markets']['player_points']['quotes'] = [q for q in event['markets']['player_points']['quotes'] if q['side'] == 0]
        self.assertEqual([], build_bets({'e':event}))


if __name__ == '__main__':
    unittest.main()
