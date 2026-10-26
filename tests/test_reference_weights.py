import unittest
from decimal import Decimal as D
from corner.reference_weights import normalized_reference_weights as weights, reference_weight
from corner.featured_ev import calculate_featured_ev
from corner.featured_tools import MatchedMarket, Offer
from corner import prop_markets as pm

class Matrix(unittest.TestCase):
    def test_main_and_alternate_matrix(self):
        books=['pinnacle','novig','prophetx','polymarket_us','kalshi','betonlineag','draftkings','fanduel']
        expected={'pinnacle':D('.45'),'novig':D('.0875'),'prophetx':D('.0875'),'polymarket_us':D('.0875'),'kalshi':D('.0875'),'betonlineag':D('.1'),'draftkings':D('.05'),'fanduel':D('.05')}
        for market in ('h2h','alternate_spreads','team_totals'):
            self.assertEqual(weights(books,'basketball_nba',market_key=market),expected)

    def test_props_matrix_and_missing_novig_fallback(self):
        books=['fanduel','novig','prophetx','kalshi','pinnacle','draftkings']
        result=weights(books,'basketball_nba',player_props=True)
        self.assertEqual(result,dict(fanduel=D('.35'),novig=D('.35'),prophetx=D('.075'),kalshi=D('.075'),pinnacle=D('.075'),draftkings=D('.075')))
        self.assertEqual(weights(['fanduel','pinnacle','draftkings'],'basketball_nba',player_props=True),dict(fanduel=D('.6'),pinnacle=D('.2'),draftkings=D('.2')))
        fallback=weights(['fanduel','pinnacle','prophetx','kalshi'],'basketball_nba',player_props=True)
        self.assertEqual(fallback,dict(fanduel=D('.57'),pinnacle=D('.38'),prophetx=D('.025'),kalshi=D('.025')))

    def test_secondary_books_share_five_percent_and_partial_groups_reallocate(self):
        result=weights(['pinnacle','novig','kalshi','betonlineag','draftkings','betmgm','bovada'],'basketball_nba')
        self.assertEqual(result['pinnacle'],D('.4275'))
        self.assertEqual(result['novig'],D('.16625'))
        self.assertEqual(result['draftkings'],D('.095'))
        self.assertEqual(result['betmgm']+result['bovada'],D('.05'))
        self.assertEqual(sum(result.values()),D(1))

    def test_target_exclusion_triggers_fallback_without_reducing_reference_minimum(self):
        prices={b:{0:D(2),1:D(3)} for b in ('novig','fanduel','pinnacle','draftkings')}
        fair,used=pm._fair_first_side(prices,exclude='novig',sport_key='basketball_nba')
        self.assertNotIn('novig',used)
        self.assertEqual(weights(used,'basketball_nba',player_props=True)['fanduel'],D('.6'))
        self.assertEqual(pm._fair_first_side({'novig':prices['novig'],'fanduel':prices['fanduel']},exclude='novig',sport_key='basketball_nba'),(None,[]))

    def test_main_calculator_uses_matrix_after_target_exclusion(self):
        market=MatchedMarket('c','h2h',('h','a'),False)
        refs=[Offer(b+s,'c','h2h',s,b,price,D(0)) for b,prices in [('pinnacle',(D(2),D(3))),('betmgm',(D(3),D(2)))] for s,price in zip(('h','a'),prices)]
        result=calculate_featured_ev(market,Offer('t','c','h2h','h','draftkings',D(2),D(0)),refs,required_reference_books=('pinnacle','betmgm'),sport_key='basketball_nba')
        self.assertEqual(result.conditional_fair_probability,D('.59'))
        self.assertEqual({b.sportsbook_id:b.weight for b in result.reference_books},{'pinnacle':D('.95'),'betmgm':D('.05')})

    def test_eligibility_aliases_and_legacy(self):
        self.assertEqual(weights(['pinnacle','betfair_ex_uk']),{'pinnacle':D('.5'),'betfair_ex_uk':D('.5')})
        self.assertEqual(weights(['betfair_ex_uk'],'basketball_nba',player_props=True),{})
        self.assertEqual(reference_weight('prizepicks','basketball_nba'),0)
        self.assertEqual(weights([],'basketball_nba'),{})
        single=weights(['betfair_ex_uk','betmgm'],'soccer_epl')
        aliases=weights(['betfair_ex_uk','betfair_ex_eu','betmgm'],'soccer_epl')
        self.assertEqual(single['betfair_ex_uk'],aliases['betfair_ex_uk']+aliases['betfair_ex_eu'])
        self.assertEqual(weights(['bovada','betmgm'],'basketball_nba'),{'bovada':D('.5'),'betmgm':D('.5')})
