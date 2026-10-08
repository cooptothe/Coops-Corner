"""Prop normalization and edge tests: pure, no provider or database access."""
import unittest

from corner import prop_markets as pm

EVENT = {'bookmakers': [
    {'key': 'pinnacle', 'markets': [{'key': 'player_points', 'outcomes': [
        {'name': 'Over', 'description': 'A Player', 'price': 1.91, 'point': 24.5},
        {'name': 'Under', 'description': 'A Player', 'price': 1.91, 'point': 24.5}]}]},
    {'key': 'fanduel', 'markets': [{'key': 'player_points', 'outcomes': [
        {'name': 'Over', 'description': 'A Player', 'price': 2.2, 'point': 24.5},
        {'name': 'Under', 'description': 'A Player', 'price': 1.65, 'point': 24.5}]}]},
]}


class Props(unittest.TestCase):
    def test_catalog_defaults_exist(self):
        for fam, keys in pm.DEFAULT_MARKETS.items():
            for key in keys:
                self.assertIn(key, {m.key for m in pm.FAMILIES[fam]})

    def test_bets(self):
        meta = pm.market_meta('basketball_nba', 'player_points')
        quotes = pm.normalize_event(EVENT, 'player_points', meta)
        self.assertEqual(len(quotes), 4)
        event = {'sport_key': 'basketball_nba', 'home_team': 'H', 'away_team': 'A',
                 'commence_time': '2030-01-01T00:00:00Z',
                 'markets': {'player_points': {'captured_at': 'x', 'quotes': quotes}}}
        bets = pm.build_bets({'e1': event})
        self.assertEqual({(b['book'], b['side']) for b in bets}, {('fanduel', 'Over'), ('fanduel', 'Under')})
        over = next(b for b in bets if b['side'] == 'Over')
        self.assertEqual(over['sharps'], ['pinnacle'])
        self.assertEqual(over['fair_probability'], '0.500000')
        self.assertEqual(over['ev'], '0.100000')
        self.assertLess(float(next(b for b in bets if b['side'] == 'Under')['ev']), 0)

    def test_no_sharp_reference_no_bets(self):
        meta = pm.market_meta('basketball_nba', 'player_points')
        quotes = [q for q in pm.normalize_event(EVENT, 'player_points', meta) if q['book'] != 'pinnacle']
        event = {'sport_key': 'basketball_nba', 'home_team': 'H', 'away_team': 'A',
                 'commence_time': '2030-01-01T00:00:00Z',
                 'markets': {'player_points': {'captured_at': 'x', 'quotes': quotes}}}
        self.assertEqual(pm.build_bets({'e1': event}), [])

    def test_yes_only_first_scorer_has_no_edge(self):
        meta = pm.market_meta('icehockey_nhl', 'player_goal_scorer_first')
        payload = {'bookmakers': [{'key': 'fanduel', 'markets': [{'key': 'player_goal_scorer_first', 'outcomes': [
            {'name': 'Some Skater', 'price': 9.0}]}]}]}
        (quote,) = pm.normalize_event(payload, 'player_goal_scorer_first', meta)
        self.assertEqual((quote['player'], quote['side'], quote['point']), ('Some Skater', 0, None))

    def test_unattributed_over_under_skipped(self):
        meta = pm.market_meta('basketball_nba', 'player_points')
        payload = {'bookmakers': [{'key': 'fanduel', 'markets': [{'key': 'player_points', 'outcomes': [
            {'name': 'Over', 'price': 2.0, 'point': 1.5}]}]}]}
        self.assertEqual(pm.normalize_event(payload, 'player_points', meta), [])


if __name__ == '__main__':
    unittest.main()
