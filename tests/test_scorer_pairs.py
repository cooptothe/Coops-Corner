import unittest
from decimal import Decimal as D
from corner.prop_markets import build_bets, normalize_event, market_meta
from corner.pricing import no_vig_pair


class ScorerPairs(unittest.TestCase):
    def event(self, market, sport, pairs=True):
        quotes=[]
        for book,yes,no in [('fanduel','4','1.4'),('pinnacle','5','1.3'),('draftkings','6',None)]:
            quotes.append(dict(book=book,player='Player',side=0,point=None,price=yes))
            if pairs and no:
                quotes.append(dict(book=book,player='Player',side=1,point=None,price=no))
        return {'e':dict(sport_key=sport,home_team='H',away_team='A',commence_time='2030-01-01T00:00:00Z',markets={market:dict(quotes=quotes)})}

    def test_atd_and_atg_exact_yes_no_references_price_automatically(self):
        for market,sport in [('player_anytime_td','americanfootball_nfl'),('player_goal_scorer_anytime','icehockey_nhl'),('player_goal_scorer_anytime','soccer_epl')]:
            with self.subTest(market=market,sport=sport):
                target=next(b for b in build_bets(self.event(market,sport)) if b['book']=='draftkings')
                self.assertEqual(target['side'],'Yes')
                self.assertNotIn('draftkings',target['sharps'])
                self.assertEqual(target['probability_basis'],'weighted_power_no_vig')
                self.assertEqual(D(target['reference_weights']['fanduel']),D(target['reference_weights']['pinnacle']))
                weights={b:D(w) for b,w in target['reference_weights'].items()}
                power=weights['fanduel']*no_vig_pair(D('4'),D('1.4'))[0][0]+weights['pinnacle']*no_vig_pair(D('5'),D('1.3'))[0][0]
                self.assertAlmostEqual(float(target['fair_probability']),float(power),places=5)

    def test_yes_only_prices_never_become_unqualified_fair_odds(self):
        data=self.event('player_anytime_td','americanfootball_nfl',False)
        self.assertEqual(build_bets(data),[])
        self.assertTrue(build_bets(data,one_sided_margin='.10'))
        target=next(b for b in build_bets(data,one_sided_margin='.10') if b['book']=='draftkings')
        self.assertLess(D(target['allocation_sensitivity']['ev_min']),D(target['ev']))
        self.assertFalse(target['allocation_sensitivity']['confidence_interval'])

    def test_no_price_for_another_player_cannot_complete_pair(self):
        data=self.event('player_anytime_td','americanfootball_nfl')
        for q in data['e']['markets']['player_anytime_td']['quotes']:
            if q['side']==1:q['player']='Someone else'
        self.assertEqual(build_bets(data),[])

    def test_named_yes_list_and_explicit_no_survive_normalization(self):
        key='player_anytime_td'
        payload={'bookmakers':[{'key':'fanduel','markets':[{'key':key,'outcomes':[{'name':'Player','price':4},{'name':'No','description':'Player','price':1.4}]}]}]}
        quotes=normalize_event(payload,key,market_meta('americanfootball_nfl',key))
        self.assertEqual([(q['player'],q['side']) for q in quotes],[('Player',0),('Player',1)])
