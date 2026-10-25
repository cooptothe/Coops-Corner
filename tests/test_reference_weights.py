import unittest
from decimal import Decimal as D
from corner.reference_weights import reference_weight, normalized_reference_weights
from corner.featured_ev import calculate_featured_ev
from corner.featured_tools import MatchedMarket, Offer
from corner import prop_markets as pm

class Weights(unittest.TestCase):
    def test_sport_profiles_follow_reputation_tiers(self):
        self.assertGreater(reference_weight('pinnacle', 'icehockey_nhl'), reference_weight('betfair_ex_uk', 'icehockey_nhl'))
        self.assertGreater(reference_weight('pinnacle', 'mma_mixed_martial_arts'), reference_weight('betfair_ex_uk', 'mma_mixed_martial_arts'))
        self.assertGreater(reference_weight('betfair_ex_uk', 'soccer_epl'), reference_weight('prophetx', 'soccer_epl'))
        self.assertGreater(reference_weight('pinnacle', 'basketball_wnba'), reference_weight('betfair_ex_uk', 'basketball_wnba'))
        for sport in ('basketball_nba', 'baseball_mlb'):
            self.assertGreater(reference_weight('fanduel', sport, player_props=True), reference_weight('pinnacle', sport, player_props=True))

    def test_main_ev_uses_weighted_devigged_probabilities(self):
        market = MatchedMarket('c', 'h2h', ('h', 'a'), False)
        refs = [Offer(b+s, 'c', 'h2h', s, b, price, D(0))
                for b,prices in [('pinnacle', (D(2), D(3))), ('betfair_ex_uk', (D(3), D(2)))]
                for s,price in zip(('h', 'a'), prices)]
        result = calculate_featured_ev(market, Offer('t','c','h2h','h','draftkings',D(2),D(0)), refs,
                                      required_reference_books=('pinnacle','betfair_ex_uk'), sport_key='basketball_nba')
        self.assertEqual(result.conditional_fair_probability, D('0.56'))
        self.assertEqual(result.conditional_ev_ratio_on_capital, D('0.12'))
        self.assertEqual(sum(b.weight for b in result.reference_books), D(1))
        self.assertEqual({b.sportsbook_id:b.weight for b in result.reference_books}, {'pinnacle':D('.8'), 'betfair_ex_uk':D('.2')})

    def test_props_normalize_only_available_other_books(self):
        prices = {'fanduel': {0:D(2),1:D(3)}, 'pinnacle':{0:D(3),1:D(2)}, 'draftkings':{0:D(2),1:D(2)}}
        fair, used = pm._fair_first_side(prices, exclude='draftkings', sport_key='basketball_nba')
        self.assertEqual(set(used), {'fanduel','pinnacle'})
        from corner.pricing import no_vig_pair
        a = no_vig_pair(D(2), D(3))[0][0]
        b = no_vig_pair(D(3), D(2))[0][0]
        self.assertAlmostEqual(float(fair), float((a*4+b)/5))
        self.assertEqual(set(pm._fair_first_side(prices, exclude='fanduel', sport_key='basketball_nba')[1]), {'pinnacle','draftkings'})
        self.assertEqual((None,[]),pm._fair_first_side({'fanduel':prices['fanduel'],'pinnacle':prices['pinnacle']},exclude='fanduel',sport_key='basketball_nba'))
        weights = normalized_reference_weights(['fanduel'], 'soccer_epl', player_props=True)
        self.assertEqual(weights, {'fanduel':D(1)})

    def test_legacy_generic_calculations_remain_equal(self):
        self.assertEqual(normalized_reference_weights(['pinnacle', 'betfair_ex_uk']), {'pinnacle':D('.5'),'betfair_ex_uk':D('.5')})

    def test_expanded_props_pair_excludes_target_and_keeps_two_references(self):
        for sport in ('basketball_nba','americanfootball_nfl','baseball_mlb','icehockey_nhl','soccer_epl'):
            for book in ('betonlineag','bovada'):
                self.assertGreater(reference_weight(book,sport,player_props=True),D(0))
            prices={'betonlineag':{0:D('2.1'),1:D('1.9')},
                    'bovada':{0:D('2.2'),1:D('1.8')},
                    'draftkings':{0:D('2'),1:D('2')}}
            fair,used=pm._fair_first_side(prices,exclude='draftkings',sport_key=sport)
            self.assertIsNotNone(fair)
            self.assertEqual(set(used),{'betonlineag','bovada'})
            self.assertEqual(set(pm._fair_first_side(prices,exclude='bovada',sport_key=sport)[1]),{'betonlineag','draftkings'})


class ConfiguredEVAnchors(unittest.TestCase):
    def test_three_equal_top_tier_anchors_cover_core_and_alternate_lines(self):
        from corner.reference_weights import REFERENCE_BOOKS
        for sport in ('basketball_nba','basketball_wnba','americanfootball_nfl','soccer_epl','icehockey_nhl','baseball_mlb','tennis_atp_challenger','mma_mixed_martial_arts'):
            for market in ('h2h','spreads','totals','alternate_spreads','alternate_totals','team_totals','btts','draw_no_bet'):
                anchors={book:reference_weight(book,sport,market_key=market) for book in ('pinnacle','kalshi','novig')}
                self.assertEqual(set(anchors.values()),{D(4)})
                for book in REFERENCE_BOOKS-set(anchors):
                    self.assertLess(reference_weight(book,sport,market_key=market),D(4),(sport,market,book))

    def test_props_profiles_do_not_inherit_non_prop_anchors(self):
        self.assertEqual(reference_weight('kalshi','basketball_nba',player_props=True),D('.5'))
        self.assertEqual(reference_weight('novig','basketball_nba',player_props=True),D('.5'))
        self.assertEqual(reference_weight('pinnacle','basketball_nba',player_props=True),D(1))
        self.assertEqual(reference_weight('fanduel','basketball_nba',player_props=True),D(4))

    def test_missing_anchors_are_not_invented_and_available_references_normalize(self):
        weights=normalized_reference_weights(['kalshi','novig','draftkings'],'basketball_nba',market_key='alternate_spreads')
        self.assertEqual(set(weights),{'kalshi','novig','draftkings'})
        self.assertEqual(weights['kalshi'],weights['novig'])
        self.assertEqual(weights['kalshi']/weights['draftkings'],D(4))
