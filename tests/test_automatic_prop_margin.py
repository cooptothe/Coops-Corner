"""Recorded-price margin transfer without provider calls or fitted win rates."""
from copy import deepcopy
from decimal import Decimal as D
import unittest
from corner.prop_markets import build_bets
from tests.test_one_sided_props import event


def fixture():
    data = {'e': event({'pinnacle': {0: 2}, 'fanduel': {0: 2}, 'draftkings': {0: 3}})}
    quotes = data['e']['markets']['player_shots']['quotes']
    for player, margin in [('One', '.06'), ('Two', '.10'), ('Three', '.14')]:
        for book in ('pinnacle', 'fanduel'):
            for side in (0, 1):
                quotes.append({'player': player, 'book': book, 'side': side,
                               'point': '2.5', 'price': str(D(2)/(1+D(margin)))})
    return data


def target(data):
    return [b for b in build_bets(data) if b['player']=='Player' and b['book']=='draftkings']


class AutomaticMargin(unittest.TestCase):
    def test_observed_median_and_maximum_have_independent_expected_arithmetic(self):
        data = fixture()
        before = deepcopy(data)
        row, = target(data)
        self.assertEqual(row['fair_probability'], '0.454545')  # .5 / 1.10
        self.assertEqual(row['probability_lower'], '0.438596')  # .5 / 1.14
        self.assertEqual(row['ev'], '0.315789')  # 3 * .5 / 1.14 - 1
        self.assertEqual(row['probability_basis'], 'observed_margin_transfer')
        self.assertIsNone(row['assumed_margin'])
        self.assertEqual(set(row['margin_evidence']), {'pinnacle', 'fanduel'})
        self.assertTrue(all(e['players']==3 for e in row['margin_evidence'].values()))
        self.assertEqual(data, before)

    def test_two_samples_or_many_lines_of_one_player_do_not_qualify(self):
        for mode in ('missing', 'same_player', 'target_player'):
            data = fixture()
            quotes = data['e']['markets']['player_shots']['quotes']
            if mode=='missing':
                quotes[:] = [q for q in quotes if q['player']!='Three']
            else:
                for i, q in enumerate(quotes[3:]):
                    q['player'] = 'Other' if mode=='same_player' else 'Player'
                    q['point'] = str(i//4 + 10) + '.5'
            self.assertEqual(target(data), [])

    def test_no_cross_event_market_or_book_transfer(self):
        for mode in ('event', 'market', 'book'):
            data = fixture()
            stored = data['e']['markets']['player_shots']
            samples = stored['quotes'][3:]
            stored['quotes'] = stored['quotes'][:3]
            if mode=='event':
                data['other'] = deepcopy(data['e'])
                data['other']['markets']['player_shots']['quotes'] = samples
            elif mode=='market':
                data['e']['markets']['player_shots_on_target'] = {'quotes':samples}
            else:
                stored['quotes'].extend([{**q, 'book':'novig'} for q in samples])
            self.assertEqual(target(data), [])

    def test_withdrawal_removes_model_without_cached_margin(self):
        data = fixture()
        self.assertTrue(target(data))
        quotes = data['e']['markets']['player_shots']['quotes']
        quotes[:] = [q for q in quotes if not (q['player']=='Three' and q['side']==1)]
        self.assertEqual(target(data), [])

    def test_duplicate_sample_quotes_do_not_support_model(self):
        data = fixture()
        quotes = data['e']['markets']['player_shots']['quotes']
        quotes.append(deepcopy(quotes[-1]))
        self.assertEqual(target(data), [])
