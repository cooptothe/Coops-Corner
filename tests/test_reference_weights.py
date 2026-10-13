import unittest
from decimal import Decimal as D
from corner.reference_weights import reference_weight, normalized_reference_weights
from corner.featured_ev import calculate_featured_ev
from corner.featured_tools import MatchedMarket, Offer
from corner import prop_markets as pm

class Weights(unittest.TestCase):
    def test_sport_profiles_follow_reputation_tiers(self):
        self.assertGreater(reference_weight('pinnacle', 'icehockey_nhl'), reference_weight('betonlineag', 'icehockey_nhl'))
        self.assertGreater(reference_weight('betonlineag', 'mma_mixed_martial_arts'), reference_weight('pinnacle', 'mma_mixed_martial_arts'))
        self.assertGreater(reference_weight('betfair_ex_uk', 'soccer_epl'), reference_weight('betonlineag', 'soccer_epl'))
        self.assertEqual(reference_weight('pinnacle', 'basketball_wnba'), reference_weight('betonlineag', 'basketball_wnba'))
        for sport in ('basketball_nba', 'basketball_wnba', 'americanfootball_nfl', 'baseball_mlb', 'icehockey_nhl'):
            self.assertGreater(reference_weight('fanduel', sport, player_props=True), reference_weight('pinnacle', sport, player_props=True))

    def test_main_ev_uses_weighted_devigged_probabilities(self):
        market = MatchedMarket('c', 'h2h', ('h', 'a'), False)
        refs = [Offer(b+s, 'c', 'h2h', s, b, price, D(0))
                for b,prices in [('pinnacle', (D(2), D(3))), ('betonlineag', (D(3), D(2)))]
                for s,price in zip(('h', 'a'), prices)]
        result = calculate_featured_ev(market, Offer('t','c','h2h','h','draftkings',D(2),D(0)), refs,
                                      required_reference_books=('pinnacle','betonlineag'), sport_key='basketball_nba')
        self.assertEqual(result.conditional_fair_probability, D('0.56'))
        self.assertEqual(result.conditional_ev_ratio_on_capital, D('0.12'))
        self.assertEqual(sum(b.weight for b in result.reference_books), D(1))
        self.assertEqual({b.sportsbook_id:b.weight for b in result.reference_books}, {'pinnacle':D('.8'), 'betonlineag':D('.2')})

    def test_props_normalize_only_available_other_books(self):
        prices = {'fanduel': {0:D(2),1:D(3)}, 'pinnacle':{0:D(3),1:D(2)}, 'draftkings':{0:D(2),1:D(2)}}
        fair, used = pm._fair_first_side(prices, exclude='draftkings', sport_key='basketball_nba')
        self.assertEqual(set(used), {'fanduel','pinnacle'})
        self.assertAlmostEqual(float(fair), (0.6*5+0.4*2)/7)
        self.assertEqual((None,[]), pm._fair_first_side(prices, exclude='fanduel', sport_key='basketball_nba'))
        weights = normalized_reference_weights(['fanduel'], 'soccer_epl', player_props=True)
        self.assertEqual(weights, {'fanduel':D(1)})

    def test_legacy_generic_calculations_remain_equal(self):
        self.assertEqual(normalized_reference_weights(['pinnacle', 'betonlineag']), {'pinnacle':D('.5'),'betonlineag':D('.5')})

    def test_betonline_is_requested_as_a_reference_and_has_valid_links(self):
        from api.database import DEFAULT_REFERENCES
        from pipelines.odds_ingestion import PARAMS
        from pipelines.props_ingestion import BOOKS
        from corner.links import clean_url
        self.assertIn('betonlineag', DEFAULT_REFERENCES)
        self.assertIn('betonlineag', PARAMS['bookmakers'].split(','))
        self.assertIn('betonlineag', BOOKS.split(','))
        self.assertEqual('https://www.betonline.ag/sportsbook', clean_url('https://www.betonline.ag/sportsbook','betonlineag'))
