"""Prop normalization and edge tests: pure, no provider or database access."""
import unittest

from corner import prop_markets as pm

EVENT = {'bookmakers': [
    {'key': 'pinnacle', 'markets': [{'key': 'player_points', 'outcomes': [
        {'name': 'Over', 'description': 'A Player', 'price': 1.91, 'point': 24.5},
        {'name': 'Under', 'description': 'A Player', 'price': 1.91, 'point': 24.5}]}]},
    {'key': 'prophetx', 'markets': [{'key': 'player_points', 'outcomes': [
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
        self.assertEqual(len(quotes), 6)
        event = {'sport_key': 'basketball_nba', 'home_team': 'H', 'away_team': 'A',
                 'commence_time': '2030-01-01T00:00:00Z',
                 'markets': {'player_points': {'captured_at': 'x', 'quotes': quotes}}}
        bets = pm.build_bets({'e1': event})
        self.assertEqual({b['book'] for b in bets}, {'fanduel', 'pinnacle', 'prophetx'})
        over = next(b for b in bets if b['side'] == 'Over' and b['book'] == 'fanduel')
        self.assertEqual(over['sharps'], ['pinnacle', 'prophetx'])
        self.assertEqual(over['fair_probability'], '0.500000')
        self.assertEqual(over['ev'], '0.100000')
        self.assertLess(float(next(b for b in bets if b['side'] == 'Under' and b['book'] == 'fanduel')['ev']), 0)

    def test_bets_carry_only_validated_links(self):
        import copy
        event = copy.deepcopy(EVENT)
        fanduel = event['bookmakers'][2]
        fanduel['link'] = 'https://sportsbook.fanduel.com/basketball/nba/game-1'
        fanduel['markets'][0]['link'] = 'https://evil.example/market'  # not a FanDuel domain: dropped
        fanduel['markets'][0]['outcomes'][0]['link'] = 'https://sportsbook.fanduel.com/addToBetslip?marketId=1&selectionId=2'
        meta = pm.market_meta('basketball_nba', 'player_points')
        quotes = pm.normalize_event(event, 'player_points', meta)
        stored = {'sport_key': 'basketball_nba', 'home_team': 'H', 'away_team': 'A', 'commence_time': '2030-01-01T00:00:00Z',
                  'markets': {'player_points': {'captured_at': 'x', 'quotes': quotes}}}
        bets = {b['side']: b for b in pm.build_bets({'e1': stored}) if b['book'] == 'fanduel'}
        self.assertEqual(bets['Over']['links'], {'event': 'https://sportsbook.fanduel.com/basketball/nba/game-1',
                                                 'outcome': 'https://sportsbook.fanduel.com/addToBetslip?marketId=1&selectionId=2'})
        self.assertIsNone(bets['Under']['links'] and bets['Under']['links'].get('market'))
        plain = pm.normalize_event(EVENT, 'player_points', meta)
        self.assertTrue(all('links' not in q for q in plain))
    def test_one_sharp_is_not_enough(self):
        meta = pm.market_meta('basketball_nba', 'player_points')
        quotes = [q for q in pm.normalize_event(EVENT, 'player_points', meta) if q['book'] != 'prophetx']
        event = {'sport_key': 'basketball_nba', 'home_team': 'H', 'away_team': 'A',
                 'commence_time': '2030-01-01T00:00:00Z',
                 'markets': {'player_points': {'captured_at': 'x', 'quotes': quotes}}}
        self.assertEqual(pm.build_bets({'e1': event}), [])

    def test_no_sharp_reference_no_bets(self):
        meta = pm.market_meta('basketball_nba', 'player_points')
        quotes = [q for q in pm.normalize_event(EVENT, 'player_points', meta)
                  if q['book'] not in ('pinnacle', 'prophetx')]
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


class FanDuelReference(unittest.TestCase):
    """FanDuel counts as a sharp reference for props, and its own props are still bets."""
    @staticmethod
    def stored(books):
        def outcomes(over, under):
            return [{'name': 'Over', 'description': 'A Player', 'price': over, 'point': 24.5},
                    {'name': 'Under', 'description': 'A Player', 'price': under, 'point': 24.5}]
        payload = {'bookmakers': [{'key': k, 'markets': [{'key': 'player_points', 'outcomes': outcomes(*p)}]}
                                  for k, p in books.items()]}
        meta = pm.market_meta('basketball_nba', 'player_points')
        return {'sport_key': 'basketball_nba', 'home_team': 'H', 'away_team': 'A', 'commence_time': '2030-01-01T00:00:00Z',
                'markets': {'player_points': {'captured_at': 'x', 'quotes': pm.normalize_event(payload, 'player_points', meta)}}}

    def test_fanduel_is_a_reference_for_props_only(self):
        self.assertIn('fanduel', pm.PROP_SHARP_BOOKS)
        self.assertIn('fanduel', pm.SHARP_BOOKS)

    def test_fanduel_plus_one_sharp_now_prices_other_books(self):
        bets = pm.build_bets({'e': self.stored({'pinnacle': (1.91, 1.91), 'fanduel': (1.91, 1.91), 'draftkings': (2.2, 1.65)})})
        dk = [b for b in bets if b['book'] == 'draftkings']
        self.assertEqual({b['side'] for b in dk}, {'Over', 'Under'})
        self.assertEqual(dk[0]['sharps'], ['fanduel', 'pinnacle'])
        over = next(b for b in dk if b['side'] == 'Over')
        self.assertEqual((over['fair_probability'], over['ev']), ('0.500000', '0.100000'))

    def test_fanduel_bets_are_still_shown_and_never_priced_against_itself(self):
        books = {'pinnacle': (1.91, 1.91), 'prophetx': (1.91, 1.91), 'fanduel': (2.2, 1.65)}
        bets = pm.build_bets({'e': self.stored(books)})
        bets = [b for b in bets if b['book'] == 'fanduel']
        self.assertEqual({b['side'] for b in bets}, {'Over', 'Under'})
        self.assertEqual(bets[0]['sharps'], ['pinnacle', 'prophetx'])
        # unchanged from before FanDuel became a reference
        self.assertEqual(next(b for b in bets if b['side'] == 'Over')['ev'], '0.100000')

    def test_fanduel_alone_with_one_sharp_is_still_not_enough_for_its_own_bet(self):
        bets = pm.build_bets({'e': self.stored({'pinnacle': (1.91, 1.91), 'fanduel': (2.2, 1.65)})})
        self.assertEqual(bets, [])

    def test_reference_books_are_bets_without_self_reference(self):
        books = {'pinnacle': (1.91, 1.91), 'prophetx': (1.91, 1.91), 'fanduel': (1.91, 1.91), 'draftkings': (2.2, 1.65)}
        shown = {b['book'] for b in pm.build_bets({'e': self.stored(books)})}
        self.assertEqual(shown, set(books))
        for bet in pm.build_bets({'e': self.stored(books)}):
            self.assertNotIn(bet['book'], bet['sharps'])

    def test_new_props_references_and_targets(self):
        books = {'prizepicks': (1.91, 1.91), 'underdog': (1.91, 1.91),
                 'polymarket': (1.91, 1.91), 'betopenly': (2.2, 1.65)}
        bets = pm.build_bets({'e': self.stored(books)})
        self.assertEqual(bets, [])  # Indicative DFS odds and unverified execution fees are not standalone EV inputs.
        for bet in bets:
            self.assertNotIn(bet['book'], bet['sharps'])
            self.assertGreaterEqual(len(bet['sharps']), 2)

    def test_main_ev_feed_references_are_unchanged(self):
        from api.database import DEFAULT_REFERENCES
        self.assertIn('fanduel', DEFAULT_REFERENCES)


if __name__ == '__main__':
    unittest.main()
