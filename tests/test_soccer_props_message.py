import unittest
from pipelines.refresh_service import props_message

class SoccerPropsMessage(unittest.TestCase):
    def test_empty_soccer_feed_explains_actual_exception_and_unsupported_market(self):
        result = {'events': 8, 'planned': 8, 'credits_used': 32, 'stopped': None}
        message = props_message('Champions League', ['player_shots', 'player_goal_scorer_anytime'], result,
                                {'bets': 0, 'positive': 0}, sport_key='soccer_uefa_champs_league')
        self.assertIn('32 credits used', message)
        self.assertIn('one Pinnacle, Betfair Exchange or FanDuel', message)
        self.assertIn('Novig alone does not qualify', message)
        self.assertIn('Yes-only goalscorer markets', message)

    def test_supported_soccer_markets_do_not_get_goalscorer_warning(self):
        message = props_message('Champions League', ['player_shots'],
                                {'events': 1, 'credits_used': 2}, {'bets': 0}, sport_key='soccer_uefa_champs_league')
        self.assertNotIn('Yes-only', message)
