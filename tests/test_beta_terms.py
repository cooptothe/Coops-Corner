import unittest
from corner import beta_terms as terms


class Terms(unittest.TestCase):
    def test_exact_two_day_boundary_and_fixed_paid_end(self):
        start = terms.BETA_END - 10*86400
        self.assertEqual(terms.entitlement('preview',start,start+172799)['state'], 'trial')
        self.assertEqual(terms.entitlement('preview',start,start+172800)['state'], 'expired')
        self.assertEqual(terms.entitlement('paid_beta',start,terms.BETA_END-1)['state'], 'paid')
        self.assertEqual(terms.entitlement('paid_beta',start,terms.BETA_END)['state'], 'expired')
        self.assertEqual(terms.entitlement('operator',start,terms.BETA_END+1)['state'], 'operator')
        self.assertEqual(terms.entitlement('preview',start,start-1)['state'], 'unavailable')

    def test_new_trials_close_before_the_beta_to_allow_two_full_days(self):
        self.assertTrue(terms.trial_available(terms.LAST_TRIAL_START))
        self.assertFalse(terms.trial_available(terms.LAST_TRIAL_START+1))

    def test_exact_native_amounts_without_float_rounding(self):
        self.assertEqual(terms.quote_amount('XRP','2')['amount_base_units'], '25000000')
        self.assertEqual(terms.quote_amount('HBAR','0.25')['amount_base_units'], '20000000000')
        self.assertEqual(terms.quote_amount('XLM','0.5')['amount_base_units'], '1000000000')
        self.assertEqual(terms.quote_amount('XRP','3')['amount_base_units'], '16666667')
        self.assertEqual(terms.quote_amount('XRP','3')['amount'], '16.666667')

    def test_ondo_unknown_assets_and_bad_rates_are_rejected(self):
        for asset, price in [('ONDO','1'), ('BTC','1'), ('XRP',2), ('XRP','NaN'),
                             ('XRP','Infinity'), ('HBAR','0'), ('XLM','-1'), ('XLM','1e-100')]:
            with self.subTest(asset=asset,price=price), self.assertRaises(ValueError):
                terms.quote_amount(asset,price)
