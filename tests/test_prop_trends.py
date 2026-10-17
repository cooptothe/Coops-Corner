from datetime import datetime, timedelta, timezone
import math
import unittest
from corner.prop_trends import analyze, wilson, walk_forward

NOW = datetime(2030,2,1,tzinfo=timezone.utc).timestamp()


def games(values):
    return [{'id':str(i),'date':datetime.fromtimestamp(NOW-(i+1)*86400,timezone.utc).isoformat(),
             'value':str(value),'completed':True,'opponent':'Opponent','home':True,'workload':'30'} for i,value in enumerate(values)]


def report(rows, **kwargs):
    return analyze(rows,line='10',side='Over',price='2',commission='0',as_of=NOW,opponent='Opponent',home=True,**kwargs)


class ResearchMath(unittest.TestCase):
    def test_dashboard_history_is_bounded_and_does_not_change_existing_window(self):
        result=report(games([20]*50))
        self.assertEqual(len(result['history_games']),40)
        self.assertEqual(len(result['games']),10)
        self.assertEqual(result['windows']['20']['games'],20)
        self.assertEqual(result['opponent'],'Opponent')
    def test_recent_windows_pushes_and_integer_refunds(self):
        result = report(games([11,10,9,12,13]))
        self.assertEqual(result['windows']['1']['wins'],1)
        self.assertEqual(result['windows']['5']['pushes'],1)
        self.assertEqual(result['windows']['10']['games'],5)
        self.assertEqual(result['baseline']['hit_rate'],.75)
        self.assertEqual(result['model_probability'],.7)  # (3+.5)/(4+1)
        self.assertAlmostEqual(result['model_ev'],.32)  # 4/5 * (.7*2-1)
        self.assertFalse(result['research_signal'])

    def test_small_sample_never_becomes_a_certified_edge(self):
        result = report(games([20]*10))
        self.assertLess(result['model_probability'],1)
        self.assertFalse(result['research_signal'])
        self.assertEqual(result['calibration_status'],'not_empirically_calibrated')
        self.assertFalse(result['historical_replay']['edge_validated'])

    def test_signal_requires_larger_history_and_historical_lower_sensitivity(self):
        result = report(games([20]*30))
        self.assertTrue(result['research_signal'])
        result = report(games([20,0]*15))
        self.assertFalse(result['research_signal'])

    def test_missing_dnp_future_duplicate_and_old_games_do_not_inflate_sample(self):
        rows = games([20,20,20,20,20,20])
        rows[0]['dnp']=True
        rows[1]['value']='NaN'
        rows[2]['completed']=False
        rows[3]['date']=datetime.fromtimestamp(NOW+1,timezone.utc).isoformat()
        rows[4]['date']='2020-01-01T00:00:00Z'
        rows.append({**rows[5],'value':'0'})
        self.assertEqual(report(rows)['baseline']['games'],0)
        self.assertIsNone(report(rows)['model_probability'])
        self.assertIsNone(report(rows)['model_ev'])

    def test_fee_adjusted_negative_signal_and_under_symmetry(self):
        rows = games([20,0]*15)
        result = analyze(rows,line='10',side='Under',price='2',commission='.02',as_of=NOW)
        self.assertAlmostEqual(result['model_probability'],.5)
        self.assertAlmostEqual(result['model_ev'],-.01)
        self.assertAlmostEqual(result['break_even_probability'],1/1.98)

    def test_workload_change_suppresses_candidate(self):
        rows = games([20]*30)
        for row in rows[:5]:row['workload']='50'
        self.assertFalse(report(rows)['research_signal'])
        self.assertAlmostEqual(report(rows)['workload_change'],2/3)

    def test_matchup_is_separate_not_independent_extra_wins(self):
        result = report(games([20]*30))
        self.assertEqual(result['matchup']['games'],30)
        self.assertEqual(result['baseline']['games'],30)
        self.assertEqual(result['model_probability'],30.5/31)

    def test_wilson_known_binomial_boundaries(self):
        lower,upper = wilson(5,10)
        self.assertAlmostEqual(lower,.236593,places=5)
        self.assertAlmostEqual(upper,.763407,places=5)
        self.assertEqual(wilson(0,0),None)

    def test_walk_forward_is_chronological_and_does_not_fit_the_holdout(self):
        rows = list(reversed(games([0]*5+[20]*20)))
        result = walk_forward(rows,'10','Over')
        p = 20.5/21
        self.assertEqual(result['held_out_games'],5)
        self.assertGreater(result['brier'],.5)
        self.assertFalse(result['edge_validated'])
        self.assertTrue(math.isfinite(result['log_loss']))
