import unittest
from decimal import Decimal as D
from unittest.mock import patch
from corner.prop_markets import build_bets
from pipelines import props_ingestion
from tests import test_scorer_pairs as scorer_cases
from tests.test_automatic_prop_margin import fixture


class PolicyMarginProps(unittest.TestCase):
    def data(self):return scorer_cases.ScorerPairs().event('player_anytime_td','americanfootball_nfl',False)

    def target(self,data,**kwargs):
        return next(b for b in build_bets(data,**kwargs) if b['book']=='draftkings' and b['player']=='Player')

    def test_default_feed_fallback_prices_yes_only_with_stress_and_disclosure(self):
        with patch.object(props_ingestion,'load',return_value={}),patch.object(props_ingestion,'prune',return_value={'events':self.data()}):
            row=next(b for b in props_ingestion.bets() if b['book']=='draftkings')
        # Reviewed NFL profile: FD and Pinnacle have equal weights. Central /1.1; stress /1.2.
        q=(D('.25')+D('.20'))/2
        self.assertAlmostEqual(float(row['fair_probability']),float(q/D('1.1')),places=5)
        self.assertAlmostEqual(float(row['ev']),float(q/D('1.2')*6-1),places=5)
        self.assertEqual(row['assumed_margin'],'0.10');self.assertEqual(row['stress_margin'],'0.20')
        self.assertEqual(row['probability_basis'],'policy_margin_fallback')
        self.assertEqual(set(row['fallback_reference_books']),{'fanduel','pinnacle'})
        self.assertNotIn(row['book'],row['sharps'])

    def test_pricing_core_still_requires_explicit_policy_opt_in(self):
        self.assertEqual(build_bets(self.data()),[])

    def test_paired_and_observed_evidence_take_precedence(self):
        paired=scorer_cases.ScorerPairs().event('player_anytime_td','americanfootball_nfl')
        self.assertEqual(self.target(paired),self.target(paired,fallback_margin='.10'))
        data=fixture()
        self.assertEqual(self.target(data),self.target(data,fallback_margin='.10'))

    def test_manual_assumption_remains_request_scoped(self):
        row=self.target(self.data(),fallback_margin='.10',one_sided_margin='.15')
        self.assertEqual(row['assumed_margin'],'0.15');self.assertIsNone(row['stress_margin'])
        self.assertEqual(row['probability_basis'],'assumed_proportional_margin')

    def test_one_reference_and_duplicate_quotes_remain_ineligible(self):
        data=self.data();quotes=data['e']['markets']['player_anytime_td']['quotes']
        quotes[:]=[q for q in quotes if q['book']!='pinnacle']
        self.assertEqual(build_bets(data,fallback_margin='.10'),[])
        data=self.data();quotes=data['e']['markets']['player_anytime_td']['quotes'];quotes.append(dict(quotes[0]))
        self.assertEqual(build_bets(data,fallback_margin='.10'),[])

    def test_stress_can_remove_apparent_edge(self):
        data=self.data()
        for q in data['e']['markets']['player_anytime_td']['quotes']:
            if q['book']=='draftkings':q['price']='5'
        row=self.target(data,fallback_margin='.10')
        self.assertGreater(D(row['fair_probability'])*5-1,0)
        self.assertLess(D(row['ev']),0)
