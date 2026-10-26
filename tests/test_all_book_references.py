import os
import unittest
from decimal import Decimal as D
from unittest.mock import patch
from api.database import build_raw,LiveCatalog
from api.catalog import FixtureCatalog
from corner.collection_policy import PROP_STANDARD,STANDARD
from corner.pricing import reference_eligible,no_vig_pair
from corner.reference_weights import reference_weight,normalized_reference_weights
from corner.reference_policy import sufficient_references
from corner.prop_markets import _sharp_side_probability,build_bets
from tests.test_database_catalog import board,q,PEOPLE,NOW


class AllBookReferences(unittest.TestCase):
    def test_all_cash_books_and_legacy_env_lists_cannot_narrow_production(self):
        for book in PROP_STANDARD:self.assertTrue(reference_eligible(book))
        with patch.dict(os.environ,{'CORNER_TOOLS_REFERENCE_BOOKS':'pinnacle',
                                   'CORNER_PROPS_REFERENCE_BOOKS':'pinnacle'}):
            with patch.object(LiveCatalog,'_rebuild',return_value=None):
                catalog=LiveCatalog(lambda:None)
            self.assertIsNone(catalog._references)
            raw=build_raw(board(),PEOPLE,now=NOW)
            self.assertEqual(set(raw['required_reference_books']),{'draftkings','pinnacle','prophetx'})
            prices={'betmgm':{0:D('1.9'),1:D('2.1')},
                    'betrivers':{0:D('2'),1:D('2')},'draftkings':{0:D('2.4'),1:D('1.6')}}
            fair,used=_sharp_side_probability(prices,0,exclude='draftkings',sport_key='icehockey_nhl',market_key='player_shots_on_goal')
            self.assertIsNotNone(fair);self.assertEqual(set(used),{'betmgm','betrivers'})

    def test_retail_only_board_can_price_ev_without_using_target(self):
        rows=[q(b,'moneyline',side,price) for b,prices in [('draftkings',('3','1.5')),('betmgm',('1.9','1.9')),('betrivers',('2','2'))]
              for side,price in zip(('home','away'),prices)]
        catalog=FixtureCatalog(raw=build_raw(rows,PEOPLE,now=NOW))
        ev=[x for x in catalog.rows if x.kind=='positive_ev' and catalog.quote_map[x.calculation.target_quote_id].sportsbook_id=='draftkings']
        self.assertTrue(ev)
        result=ev[0].calculation
        self.assertEqual({b.sportsbook_id for b in result.reference_books},{'betmgm','betrivers'})
        self.assertEqual(result.conditional_fair_probability,D('.5'))
        self.assertEqual(result.conditional_ev_ratio_on_capital,D('.5'))

    def test_researched_profiles_market_context_and_minimum(self):
        self.assertEqual(normalized_reference_weights(['fanduel','pinnacle'],'basketball_nba',player_props=True),{'fanduel':D('.6'),'pinnacle':D('.4')})
        self.assertEqual(normalized_reference_weights(['fanduel','pinnacle'],'baseball_mlb',player_props=True),{'fanduel':D('.6'),'pinnacle':D('.4')})
        self.assertEqual(normalized_reference_weights(['fanduel','pinnacle','betonlineag'],'americanfootball_nfl',player_props=True),{'fanduel':D('.57'),'pinnacle':D('.38'),'betonlineag':D('.05')})
        self.assertGreater(reference_weight('betfair_ex_uk','soccer_epl',market_key='h2h'),reference_weight('betfair_ex_uk','soccer_epl',market_key='btts'))
        self.assertFalse(sufficient_references(['betfair_ex_uk','betfair_ex_eu'],'basketball_nba',player_props=True))
        prices={'betrivers':{0:D('1.9'),1:D('2.1')}}
        self.assertEqual(_sharp_side_probability(prices,0,sport_key='basketball_nba'),(None,[]))
        self.assertFalse(reference_eligible('prizepicks'))

    def test_same_exchange_aliases_do_not_multiply_weight(self):
        weights=normalized_reference_weights(['pinnacle','betfair_ex_uk','betfair_ex_eu'],'soccer_epl')
        expected=normalized_reference_weights(['pinnacle','betfair_ex_uk'],'soccer_epl')
        self.assertEqual(weights['pinnacle'],expected['pinnacle'])
        self.assertEqual(weights['betfair_ex_uk']+weights['betfair_ex_eu'],expected['betfair_ex_uk'])

    def test_each_prop_target_excludes_itself_and_order_is_stable(self):
        prices={b:{0:D('2.1'),1:D('1.9')} for b in PROP_STANDARD}
        for book in PROP_STANDARD:
            a,used=_sharp_side_probability(prices,0,exclude=book,sport_key='basketball_nba',market_key='player_points')
            b,reversed_used=_sharp_side_probability(dict(reversed(list(prices.items()))),0,exclude=book,sport_key='basketball_nba',market_key='player_points')
            self.assertNotIn(book,used)
            self.assertEqual(len(used),len(PROP_STANDARD)-1)
            self.assertEqual(a,b);self.assertEqual(used,reversed_used)
