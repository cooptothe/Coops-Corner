import math
import unittest
from decimal import Decimal as D
from corner.scorer_research import allocation_bounds,scorer_sensitivity,poisson_anytime,negative_binomial_anytime
from pipelines.scorer_study import run


class ScorerResearch(unittest.TestCase):
    def test_exact_allocation_bounds(self):
        self.assertEqual(allocation_bounds('.25','.10'),(D('.15'),D('.25')))
        for p in (D('.15'),D('.20'),D('.25')):
            self.assertTrue(D('.15')<=p<=D('.25'))
        self.assertEqual(allocation_bounds('.02','.1')[0],0)

    def test_weighted_interval_is_not_proportional_point_estimate(self):
        result=scorer_sensitivity([{'price':4,'weight':5,'maximum_overround':'.1'},{'price':5,'weight':2,'maximum_overround':'.1'}],net_decimal_odds=6)
        expected=(D('.15')*5+D('.10')*2)/7
        self.assertEqual(D(result['probability_min']),expected)
        self.assertLess(D(result['ev_min']),0)
        self.assertGreater(D(result['ev_max']),0)
        self.assertFalse(result['confidence_interval'])

    def test_count_model_distinguishes_expected_count_and_anytime_chance(self):
        self.assertAlmostEqual(poisson_anytime(1),1-math.exp(-1))
        self.assertAlmostEqual(negative_binomial_anytime(1,1),.5)
        self.assertLess(negative_binomial_anytime(1,1),poisson_anytime(1))
        self.assertAlmostEqual(negative_binomial_anytime(1,1e8),poisson_anytime(1),places=7)

    def test_synthetic_bound_coverage_and_reproducibility(self):
        result=run(count=1000)
        self.assertEqual(result,run(count=1000))
        self.assertEqual(result['allocation_bound_violations'],0)
        self.assertEqual(result['methods']['allocation_lower']['false_positive_edges'],0)
        self.assertGreater(result['methods']['raw_implied']['false_positive_edges'],0)

    def test_invalid_inputs_are_rejected(self):
        for q,h in [('NaN','.1'),('.2','Infinity'),('1','.1'),('.2','-.1')]:
            with self.assertRaises(ValueError):allocation_bounds(q,h)
        with self.assertRaises(ValueError):poisson_anytime(-1)
        with self.assertRaises(ValueError):negative_binomial_anytime(1,0)
