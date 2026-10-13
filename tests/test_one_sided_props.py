import unittest
from decimal import Decimal as D
from corner.prop_markets import build_bets, _sharp_side_probability

def event(books, market='player_shots', sport='soccer_epl'):
    return {'sport_key': sport, 'home_team': 'H', 'away_team': 'A', 'commence_time': '2030-01-01T00:00:00Z',
            'markets': {market: {'captured_at': 'now', 'quotes': [
                {'book': book, 'player': 'Player', 'side': side, 'point': None if 'scorer' in market else '2.5', 'price': str(price)}
                for book, sides in books.items() for side, price in sides.items()]}}}

class OneSidedProps(unittest.TestCase):
    def test_over_only_prices_use_existing_weights_and_do_not_invent_under(self):
        bets = build_bets({'e': event({'fanduel': {0: 2}, 'pinnacle': {0: 4}, 'draftkings': {0: 3, 1: 2}})})
        self.assertEqual(1, len(bets))
        bet = bets[0]
        self.assertEqual(('draftkings', 'Over', '0.416667', '0.250000'),
                         (bet['book'], bet['side'], bet['fair_probability'], bet['ev']))
        self.assertEqual(['fanduel', 'pinnacle'], bet['sharps'])
        self.assertEqual('weighted_sharp_implied', bet['probability_basis'])

    def test_under_is_priced_independently(self):
        prices = {'fanduel': {0: D(2), 1: D(4)}, 'pinnacle': {0: D(4), 1: D(2)}}
        over, _ = _sharp_side_probability(prices, 0, sport_key='soccer_epl')
        under, _ = _sharp_side_probability(prices, 1, sport_key='soccer_epl')
        self.assertEqual(D(1)/D(3), under)
        self.assertNotEqual(1-over, under)

    def test_soccer_always_requires_two_other_books(self):
        for sharp in ('pinnacle', 'betfair_ex_uk', 'fanduel', 'novig'):
            self.assertEqual([], build_bets({'e': event({sharp: {0: 2}, 'draftkings': {0: 3}})}))

    def test_yes_only_goalscorer_is_supported_without_inventing_no(self):
        bets = build_bets({'e': event({'pinnacle': {0: 4}, 'fanduel': {0: 5}, 'draftkings': {0: 6}}, 'player_goal_scorer_anytime')})
        self.assertEqual(1, len(bets))
        self.assertEqual(('Yes', '0.300000'), (bets[0]['side'], bets[0]['ev']))

    def test_line_and_side_must_match(self):
        data = event({'pinnacle': {0: 2}, 'fanduel': {0: 2}, 'draftkings': {0: 3}})
        data['markets']['player_shots']['quotes'][1]['point'] = '3.5'
        self.assertEqual([], build_bets({'e': data}))

    def test_reference_book_cannot_reference_itself(self):
        bets = build_bets({'e': event({'pinnacle': {0: 2}, 'fanduel': {0: 2}, 'novig': {0: 3}})})
        self.assertEqual({'pinnacle', 'fanduel', 'novig'}, {b['book'] for b in bets})
        self.assertTrue(all(len(b['sharps']) == 2 and b['book'] not in b['sharps'] for b in bets))
