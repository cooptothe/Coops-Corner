import unittest
from decimal import Decimal
from corner.prop_markets import build_bets
from tests.test_one_sided_props import event

class PropDecimalOutput(unittest.TestCase):
    def test_zero_worst_case_is_plain_decimal_in_actual_prop_response(self):
        data={'e':event({'pinnacle':{0:2,1:2},'fanduel':{0:2,1:2},'draftkings':{0:2,1:2}})}
        rows=build_bets(data)
        self.assertTrue(rows)
        zero=False
        for bet in rows:
            for comparison in bet['devig_comparisons']:
                for field in ('ev','probability'):
                    self.assertNotIn('E',comparison[field].upper())
                    Decimal(comparison[field])
                if comparison['method']=='worst_case' and Decimal(comparison['ev'])==0:zero=True
        self.assertTrue(zero)
