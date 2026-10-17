import unittest
from decimal import Decimal as D
from corner.prop_markets import build_bets, _sharp_side_probability

def event(books, market='player_shots', sport='soccer_epl'):
    return {'sport_key': sport, 'home_team': 'H', 'away_team': 'A', 'commence_time': '2030-01-01T00:00:00Z',
            'markets': {market: {'captured_at': 'now', 'quotes': [
                {'book': book, 'player': 'Player', 'side': side, 'point': None if 'scorer' in market else '2.5', 'price': str(price)}
                for book, sides in books.items() for side, price in sides.items()]}}}

class OneSidedProps(unittest.TestCase):
    def test_over_only_prices_do_not_identify_fair_probability(self):
        bets = build_bets({'e': event({'fanduel': {0: 2}, 'pinnacle': {0: 4}, 'draftkings': {0: 3, 1: 2}})})
        self.assertEqual([], bets)

    def test_matched_binary_estimates_are_complementary(self):
        prices = {'fanduel': {0: D(2), 1: D(4)}, 'pinnacle': {0: D(4), 1: D(2)}}
        over, _ = _sharp_side_probability(prices, 0, sport_key='soccer_epl')
        under, _ = _sharp_side_probability(prices, 1, sport_key='soccer_epl')
        self.assertAlmostEqual(float(over+under), 1, places=14)
        self.assertGreater(under, 0)

    def test_soccer_always_requires_two_other_books(self):
        for sharp in ('pinnacle', 'betfair_ex_uk', 'fanduel', 'novig'):
            self.assertEqual([], build_bets({'e': event({sharp: {0: 2}, 'draftkings': {0: 3}})}))

    def test_yes_only_goalscorer_requires_separate_probability_model(self):
        bets = build_bets({'e': event({'pinnacle': {0: 4}, 'fanduel': {0: 5}, 'draftkings': {0: 6}}, 'player_goal_scorer_anytime')})
        self.assertEqual([], bets)

    def test_line_and_side_must_match(self):
        data = event({'pinnacle': {0: 2}, 'fanduel': {0: 2}, 'draftkings': {0: 3}})
        data['markets']['player_shots']['quotes'][1]['point'] = '3.5'
        self.assertEqual([], build_bets({'e': data}))

    def test_reference_book_cannot_reference_itself(self):
        bets = build_bets({'e': event({'pinnacle': {0: 2, 1: 2}, 'fanduel': {0: 2, 1: 2}, 'novig': {0: 3, 1: 2}})})
        self.assertEqual({'pinnacle', 'fanduel', 'novig'}, {b['book'] for b in bets})
        self.assertTrue(all(len(b['sharps']) == 2 and b['book'] not in b['sharps'] for b in bets))
