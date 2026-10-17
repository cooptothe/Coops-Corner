import unittest
from decimal import Decimal as D,localcontext
from corner.pricing import no_vig_pair

def original(first,second):
    with localcontext() as ctx:
        ctx.prec=60
        q=(1/D(first),1/D(second));low=D(0);high=D(1)
        while sum(x**high for x in q)>1:high*=2
        for _ in range(180):
            mid=(low+high)/2
            if sum(x**mid for x in q)>1:low=mid
            else:high=mid
        return q[0]**((low+high)/2)

class PricingSolver(unittest.TestCase):
    def test_matches_independent_original_solver_across_price_extremes(self):
        for first,second in [('1.91','1.95'),('4','1.4'),('1.01','101'),('1000000000000','1.000000000001'),('1.000000000001','1.000000000002'),('99','101'),('2','3')]:
            with self.subTest(first=first,second=second),localcontext() as ctx:
                ctx.prec=60
                power,proportional=no_vig_pair(first,second)
                self.assertLess(abs(power[0]-original(first,second)),D('1e-45'))
                self.assertEqual(sum(power),1)
                self.assertEqual(sum(proportional),1)
                self.assertLess(abs(power[0]-no_vig_pair(second,first)[0][1]),D('1e-45'))
    def test_validation_and_symmetric_shortcut_are_preserved(self):
        self.assertEqual(no_vig_pair('1.9','1.9')[0],(D('.5'),D('.5')))
        for value in ('NaN','Infinity','1','0','1.0000000000001'):
            with self.assertRaises(ValueError):no_vig_pair(value,'2')
