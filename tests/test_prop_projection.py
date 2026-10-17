from datetime import datetime,timezone
import math
import unittest
from corner.prop_projection import nb_cdf,student_cdf,forecast,plan,competing_scorer
from corner.model_validation import evaluate
from corner.prop_markets import FAMILIES
from tests.test_prop_trends import games,NOW


def project(values,**changes):
    args=dict(sport='basketball_nba',market='player_points',line='10.5',side='Over',price='2',commission='0',as_of=NOW)
    args.update(changes)
    return forecast(games(values),**args)


class Projections(unittest.TestCase):
    def test_count_cdf_matches_geometric_closed_form_and_underflow_safe(self):
        for mu in (.01,1,20):
            for k in (0,1,10,80):self.assertAlmostEqual(nb_cdf(k,1,mu),1-(mu/(1+mu))**(k+1),places=11)
        self.assertTrue(0<nb_cdf(500,15000,500)<1)

    def test_student_t_matches_cauchy_and_symmetry(self):
        for x in (-10,-1,-.1,.1,1,10):
            self.assertAlmostEqual(student_cdf(x,1),.5+math.atan(x)/math.pi,places=11)
            self.assertAlmostEqual(student_cdf(x,8)+student_cdf(-x,8),1,places=12)

    def test_predictive_branches_sum_to_one_and_integer_pushes_refund(self):
        result=project([8,10,12,9,11]*6,line='10')
        self.assertEqual(result['status'],'research_only')
        self.assertAlmostEqual(result['probability']+result['push_probability']+result['loss_probability'],1)
        self.assertGreater(result['push_probability'],0)
        self.assertAlmostEqual(result['model_ev'],result['probability']-result['loss_probability'])
        self.assertFalse(result['edge_validated']);self.assertFalse(result['live_feed_eligible'])
        half=project([8,10,12,9,11]*6)
        self.assertEqual(half['push_probability'],0)

    def test_over_and_under_complement_and_fee_only_changes_return(self):
        over=project([8,10,12,9,11]*6);under=project([8,10,12,9,11]*6,side='Under')
        fee=project([8,10,12,9,11]*6,commission='.02')
        self.assertAlmostEqual(over['probability']+under['probability'],1)
        self.assertEqual(over['probability'],fee['probability'])
        self.assertLess(fee['model_ev'],over['model_ev'])

    def test_monotone_line_probabilities_and_overdispersion_context(self):
        values=[0,0,0,0,20]*8
        low=project(values,line='2.5');high=project(values,line='10.5')
        self.assertGreater(low['probability'],high['probability'])
        self.assertIn('overdispersed_negative_binomial',[x['method'] for x in low['models']])

    def test_anytime_zero_history_does_not_claim_impossible_or_certain(self):
        result=project([0]*30,sport='icehockey_nhl',market='player_goal_scorer_anytime',line=None,side='Yes')
        self.assertTrue(0<result['probability']<1)
        self.assertEqual(result['push_probability'],0)

    def test_signed_yards_and_binary_milestone_have_separate_models(self):
        yards=project([-4,10,20,30,0,50,3,15]*4,sport='americanfootball_nfl',market='player_rush_yds',line='10')
        self.assertIn('normal_unknown_mean_variance_predictive',[m['method'] for m in yards['models']])
        binary=project([0,1]*15,market='player_double_double',side='Yes',line=None)
        self.assertAlmostEqual(binary['probability'],.5)
        invalid=project([0,2]*15,market='player_double_double',side='Yes',line=None)
        self.assertEqual(invalid['status'],'needs_context')

    def test_future_duplicate_conflicts_and_small_samples_do_not_fake_coverage(self):
        rows=games([10]*10);rows.append({**rows[0],'value':'20'});rows[1]['date']='2031-01-01T00:00:00Z';rows[2]['dnp']=True
        result=forecast(rows,sport='basketball_nba',market='player_points',line='10.5',side='Over',price='2',commission='0',as_of=NOW)
        self.assertEqual(result['status'],'needs_data');self.assertEqual(result['games'],7)
        self.assertEqual(project([1]*20,market='imaginary')['status'],'needs_context')

    def test_first_last_require_complete_competing_field_and_no_scorer(self):
        result=project([1]*30,sport='americanfootball_nfl',market='player_1st_td',line=None,side='Yes')
        self.assertEqual(result['status'],'needs_context')
        with self.assertRaises(ValueError):competing_scorer({'alice':.5},'alice')
        rates={'alice':.5,'teammates':1,'opponents':2}
        p=competing_scorer(rates,'alice',complete_field=True)
        self.assertGreater(p['anytime'],p['first'])
        self.assertAlmostEqual(sum(competing_scorer(rates,key,complete_field=True)['first'] for key in rates)+p['no_scorer'],1)

    def test_every_catalog_entry_has_an_explicit_projection_plan(self):
        mapping={'basketball':'basketball_nba','football':'americanfootball_nfl','baseball':'baseball_mlb','hockey':'icehockey_nhl','soccer':'soccer_epl'}
        for group,entries in FAMILIES.items():
            for market in entries:
                with self.subTest(market=market.key):
                    result=plan(mapping[group],market.key)
                    self.assertNotEqual(result['method'],'unavailable');self.assertTrue(result['requires'])

    def test_validation_blocks_future_leakage_and_counts_event_clusters(self):
        row=dict(model_id='model',event_id='one',selection_id='a',features_as_of=1,train_cutoff=0,predicted_at=2,event_start=3,settled_at=4,probability=.6,outcome=1)
        result=evaluate([row,{**row,'selection_id':'b'}])['model']
        self.assertEqual(result['events'],1);self.assertEqual(result['predictions'],2)
        self.assertAlmostEqual(result['event_balanced_brier'],.16)
        with self.assertRaises(ValueError):evaluate([row,{**row}])
        for change in ({'features_as_of':3},{'train_cutoff':2},{'predicted_at':5}):
            with self.assertRaises(ValueError):evaluate([{**row,**change}])

    def test_full_game_history_is_not_first_quarter_evidence(self):
        result=project([20]*30,market='player_points_q1',line='5.5')
        self.assertEqual(result['status'],'needs_context')

    def test_coverage_accounts_for_every_retained_quote_including_unknown_markets(self):
        from corner.prop_coverage import coverage
        from tests.test_one_sided_props import event
        data={'e':event({'draftkings':{0:3},'pinnacle':{0:2}})}
        data['e']['markets']['unrecognized']={'quotes':[{'player':'Player','point':None,'book':'kalshi','side':0,'price':'2'}]}
        result=coverage(data,[])
        self.assertEqual(result['retained_quotes'],3)
        self.assertEqual(sum(result['outcomes'].values()),3)
        self.assertEqual(result['outcomes']['undocumented_market'],1)
