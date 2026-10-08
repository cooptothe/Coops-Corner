import unittest
from decimal import Decimal

from corner import clv

SHARPS = frozenset({'pinnacle', 'betfair_ex_uk'})


def row(book, side, odds, point=None):
    return {'book': book, 'side': side, 'point': point, 'decimal_odds': Decimal(str(odds))}


class Devig(unittest.TestCase):
    def test_proportional_shares_sum_to_one(self):
        probs = clv.devig(['1.91', '1.91'])
        self.assertAlmostEqual(float(probs[0]), 0.5, places=12)
        three = clv.devig(['2.5', '3.4', '3.0'])
        self.assertAlmostEqual(float(sum(three)), 1.0, places=12)
        self.assertGreater(three[0], three[2])


class Moneyline(unittest.TestCase):
    def test_beating_the_close_is_positive(self):
        close = [row('pinnacle', 'home', 1.95), row('pinnacle', 'away', 1.95)]
        out = clv.measure({'market_key': 'h2h', 'side': 'home'}, '2.1', close, SHARPS, at='t')
        self.assertEqual(out['pct'], '0.05')
        self.assertEqual(out['close_odds'], '2')
        self.assertEqual(out['books'], ['pinnacle'])

    def test_worse_than_close_is_negative_and_books_average(self):
        close = [row('pinnacle', 'home', 1.80), row('pinnacle', 'away', 2.10),
                 row('betfair_ex_uk', 'home', 1.90), row('betfair_ex_uk', 'away', 2.00)]
        out = clv.measure({'market_key': 'h2h', 'side': 'home'}, '1.80', close, SHARPS, at='t')
        self.assertEqual(out['books'], ['betfair_ex_uk', 'pinnacle'])
        self.assertLess(Decimal(out['pct']), 0)

    def test_three_way_uses_the_draw(self):
        close = [row('pinnacle', 'home', 2.5), row('pinnacle', 'away', 3.0), row('pinnacle', 'draw', 3.4)]
        out = clv.measure({'market_key': 'h2h', 'side': 'draw'}, '3.6', close, SHARPS, at='t')
        fair = Decimal(out['fair_prob'])
        self.assertTrue(Decimal('0.25') < fair < Decimal('0.30'))
        # A book missing one leg of the three-way market cannot be used.
        partial = [row('pinnacle', 'home', 2.5), row('pinnacle', 'draw', 3.4)]
        self.assertIsNone(clv.measure({'market_key': 'h2h', 'side': 'home'}, '2.6', partial, SHARPS, at='t')['pct'])


class Lines(unittest.TestCase):
    def test_spread_needs_the_same_line_on_both_sides(self):
        close = [row('pinnacle', 'home', 1.95, Decimal('-3.5')), row('pinnacle', 'away', 1.95, Decimal('3.5'))]
        ref = {'market_key': 'spreads', 'side': 'home', 'point': -3.5}
        self.assertEqual(clv.measure(ref, '2.1', close, SHARPS, at='t')['pct'], '0.05')
        self.assertEqual(clv.measure({**ref, 'side': 'away', 'point': 3.5}, '1.9', close, SHARPS, at='t')['pct'], '-0.05')
        # The line moved to -4.5 by the close: there is no price at our line, so nothing is claimed.
        moved = [row('pinnacle', 'home', 1.95, Decimal('-4.5')), row('pinnacle', 'away', 1.95, Decimal('4.5'))]
        out = clv.measure(ref, '2.1', moved, SHARPS, at='t')
        self.assertIsNone(out['pct'])
        self.assertEqual(out['reason'], clv.NO_CLOSE)

    def test_total(self):
        close = [row('pinnacle', 'over', 1.87, Decimal('230.5')), row('pinnacle', 'under', 2.0, Decimal('230.5'))]
        out = clv.measure({'market_key': 'totals', 'side': 'over', 'point': 230.5}, '1.95', close, SHARPS, at='t')
        self.assertIsNotNone(out['pct'])
        self.assertGreater(Decimal(out['fair_prob']), Decimal('0.5'))

    def test_only_sharp_books_count_and_props_are_not_measured(self):
        soft = [row('draftkings', 'home', 1.5), row('draftkings', 'away', 2.6)]
        self.assertIsNone(clv.measure({'market_key': 'h2h', 'side': 'home'}, '2', soft, SHARPS, at='t')['pct'])
        close = [row('pinnacle', 'over', 1.9, Decimal('5.5')), row('pinnacle', 'under', 1.9, Decimal('5.5'))]
        self.assertIsNone(clv.measure({'market_key': 'prop', 'side': 'over', 'point': 5.5}, '2', close, SHARPS, at='t')['pct'])
        self.assertIsNone(clv.measure({'market_key': 'totals', 'side': 'over'}, '2', close, SHARPS, at='t')['pct'])


if __name__ == '__main__':
    unittest.main()
