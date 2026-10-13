import unittest
from corner.native_ids import native_ids
from corner.prop_markets import normalize_event, market_meta

class NativeIds(unittest.TestCase):
    def test_fanduel_ids_survive_existing_selection_links(self):
        self.assertEqual({'market': '42.123', 'outcome': '456'}, native_ids('fanduel', link='https://sportsbook.fanduel.com/addToBetslip?marketId=42.123&selectionId=456'))
    def test_provider_ids_are_retained_for_props_even_without_a_link(self):
        payload = {'bookmakers': [{'key': 'fanduel', 'sid': 'event-1', 'markets': [{'key': 'player_points', 'sid': '42.1', 'outcomes': [{'name': 'Over', 'description': 'Player', 'point': 20.5, 'price': 2.0, 'sid': '123'}]}]}]}
        quote = normalize_event(payload, 'player_points', market_meta('basketball_nba', 'player_points'))[0]
        self.assertEqual({'event': 'event-1', 'market': '42.1', 'outcome': '123'}, quote['source_ids'])
    def test_invalid_ids_are_not_retained(self):
        self.assertIsNone(native_ids('fanduel', market='x<script>', outcome='foo bar'))
