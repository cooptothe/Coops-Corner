"""Independent DFS-line assumption tests: no HTTP, purchases, or self-reference."""
from decimal import Decimal as D
from copy import deepcopy
import unittest
from unittest.mock import patch
from corner import prop_markets as pm
from corner.pricing import reference_eligible

def event(books,market='player_threes',sport='basketball_nba',point='2.5'):
    return {'e':{'sport_key':sport,'home_team':'H','away_team':'A','commence_time':'2030-01-01T00:00:00Z','markets':{market:{'captured_at':'2026-10-18T10:00:00Z','quotes':[{'player':'P','book':b,'side':side,'point':point,'price':str(price)} for b,sides in books.items() for side,price in sides.items()]}}}}

def prices(data):return pm.build_bets(data,include_dfs=True,fallback_margin='0.10')

class DfsReferences(unittest.TestCase):
    def test_two_dfs_lines_can_price_a_one_sided_cash_target(self):
        data=event({'prizepicks':{0:1.82,1:1.82},'underdog':{0:1.91,1:1.91},'draftkings':{0:2.2}})
        before=deepcopy(data); row,=prices(data)
        self.assertEqual(row['book'],'draftkings')
        self.assertEqual(row['fair_probability'],'0.500000')
        self.assertEqual(row['ev'],'0.100000')
        self.assertEqual(row['sharps'],['prizepicks','underdog'])
        self.assertEqual(row['dfs_reference_books'],['prizepicks','underdog'])
        self.assertIn('not inferred',row['dfs_assumption'])
        self.assertIsNone(row['market_width_cents'])
        self.assertEqual(data,before)
    def test_two_references_still_required(self):
        self.assertEqual(prices(event({'prizepicks':{0:1.9,1:1.9},'draftkings':{0:3}})),[])
        self.assertEqual(prices(event({'pinnacle':{0:2,1:2},'draftkings':{0:3}})),[])
    def test_cash_reference_has_more_weight_than_dfs(self):
        rows=prices(event({'fanduel':{0:2,1:2},'prizepicks':{0:1.82,1:1.82},'draftkings':{0:2.2}}))
        row=next(r for r in rows if r['book']=='draftkings')
        self.assertGreater(D(row['reference_weights']['fanduel']),D(row['reference_weights']['prizepicks']))
    def test_unequal_multipliers_missing_side_and_different_line_are_not_probabilities(self):
        for change in ('unequal','missing','line','player'):
            data=event({'prizepicks':{0:1.82,1:1.82},'underdog':{0:1.9,1:1.9},'draftkings':{0:3}})
            quotes=data['e']['markets']['player_threes']['quotes']
            if change=='unequal':quotes[0]['price']='2.3'
            elif change=='missing':quotes.pop(0)
            elif change=='line':quotes[0]['point']='3.5';quotes[1]['point']='3.5'
            else:quotes[0]['player']='Another';quotes[1]['player']='Another'
            self.assertEqual(prices(data),[],change)
    def test_dfs_not_used_for_scorer_yes_lists(self):
        data=event({'prizepicks':{0:2,1:2},'underdog':{0:2,1:2},'draftkings':{0:4}},market='player_anytime_td',sport='americanfootball_nfl',point=None)
        self.assertEqual(prices(data),[])
    def test_two_one_sided_cash_references_can_price_one_sided_scorer(self):
        for sport,market in [('americanfootball_nfl','player_anytime_td'),('icehockey_nhl','player_goal_scorer_anytime'),('soccer_epl','player_goal_scorer_anytime')]:
            data=event({'pinnacle':{0:3},'fanduel':{0:3},'draftkings':{0:4}},market=market,sport=sport,point=None)
            row=next(r for r in prices(data) if r['book']=='draftkings')
            self.assertEqual(row['fair_probability'],'0.303030')
            self.assertEqual(row['probability_lower'],'0.277778')
            self.assertEqual(row['ev'],'0.111111')
    def test_explicit_yes_and_player_name_only_scorer_payloads_are_offered(self):
        for sport,market in [('americanfootball_nfl','player_anytime_td'),('icehockey_nhl','player_goal_scorer_anytime'),('soccer_epl','player_goal_scorer_anytime')]:
            for explicit_yes in (True,False):
                books=[]
                for book,price in [('pinnacle',3),('fanduel',3),('draftkings',4)]:
                    outcome={'name':'Yes','description':'P','price':price} if explicit_yes else {'name':'P','price':price}
                    books.append({'key':book,'markets':[{'key':market,'outcomes':[outcome]}]})
                meta=pm.market_meta(sport,market)
                quotes=pm.normalize_event({'bookmakers':books},market,meta)
                self.assertEqual(len(quotes),3)
                data=event({},market,sport,None)
                data['e']['markets'][market]['quotes']=quotes
                row=next(r for r in prices(data) if r['book']=='draftkings')
                self.assertEqual(row['side'],'Yes')
                self.assertIsNone(row['point'])
                self.assertGreater(D(row['ev']),0)
                self.assertEqual(len(row['sharps']),2)

    def test_main_pricing_dfs_eligibility_is_unchanged(self):
        self.assertFalse(reference_eligible('prizepicks'))
        self.assertFalse(reference_eligible('underdog'))
        from api.database import DEFAULT_REFERENCES
        self.assertNotIn('prizepicks',DEFAULT_REFERENCES)
        self.assertNotIn('underdog',DEFAULT_REFERENCES)
    def test_production_props_explicitly_enables_dfs(self):
        from pipelines import props_ingestion as p
        with patch.object(p,'load',return_value={'events':{}}),patch.object(p,'build_bets',return_value=[]) as build:
            p.bets()
        self.assertTrue(build.call_args.kwargs['include_dfs'])
    def test_requested_markets_are_recommended_and_soccer_keys_documented(self):
        for sport,key in [('basketball_nba','player_threes'),('icehockey_nhl','player_assists'),('soccer_epl','player_assists'),('soccer_epl','player_shots_on_target'),('americanfootball_nfl','player_anytime_td')]:
            self.assertTrue(next(m for m in pm.catalog_view([sport])[sport] if m['key']==key)['default'])
        self.assertIsNotNone(pm.market_meta('soccer_epl','player_first_goal_scorer'))
        self.assertIsNotNone(pm.market_meta('soccer_epl','player_last_goal_scorer'))

if __name__=='__main__':unittest.main()
