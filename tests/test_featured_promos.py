from dataclasses import replace
from decimal import Decimal as D, localcontext
from fractions import Fraction
import unittest

from corner.featured_promos import PromoTerms, convert_promo, convert_promo_back_hedge
from corner.featured_tools import MatchedMarket, Offer, ToolInputError


def fixtures(kind="bonus_stake_not_returned", refund=False):
    market = MatchedMarket("event:scope:rules", "h2h", ("a", "b"), refund)
    back = Offer("back", market.contract_id, "h2h", "a", "book", D(5), D(0))
    lay = Offer("lay", market.contract_id, "h2h_lay", "a", "exchange", D(5), D(0))
    terms = PromoTerms("terms:retained:revision", kind, D(100), D(100), D("1.5"),
                       D(100) if kind.startswith("loss_") else D(0), "eligibility:fixture", kind.startswith("bonus_"))
    return market, back, lay, terms


class PromoTests(unittest.TestCase):
    def test_stake_not_returned_bonus(self):
        r = convert_promo(*fixtures())
        self.assertEqual(D(80), r.lay_stake)
        self.assertEqual(D(320), r.lay_liability)
        self.assertEqual(D(320), r.upfront_cash_required)
        self.assertEqual(D(80), r.minimum_decisive_cash_profit)
        self.assertEqual(D(".8"), r.decisive_cash_to_face_ratio)
        self.assertFalse(r.eligibility_verified)

    def test_stake_returned_as_cash_is_distinct(self):
        r = convert_promo(*fixtures("bonus_stake_returned_as_cash"))
        self.assertEqual(D(100), r.lay_stake)
        self.assertEqual(D(100), r.minimum_decisive_cash_profit)

    def test_cash_refund_uses_real_initial_cash_stake(self):
        r = convert_promo(*fixtures("loss_refund_cash"))
        self.assertEqual(D(80), r.minimum_decisive_cash_profit)
        self.assertEqual(D(420), r.upfront_cash_required)

    def test_token_refund_is_not_cash(self):
        r = convert_promo(*fixtures("loss_refund_bonus"))
        self.assertEqual(D(0), r.minimum_decisive_cash_profit)
        self.assertEqual(D(100), r.lay_stake)
        self.assertEqual(D(100), r.outcomes[1].noncash_bonus_face_returned)
        self.assertEqual(D(0), r.outcomes[0].noncash_bonus_face_returned)
        self.assertIsNone(r.noncash_valuation)

    def test_partial_cash_refund_cap(self):
        m, b, l, t = fixtures("loss_refund_cash")
        r = convert_promo(m, b, l, replace(t, loss_refund_cap=D(50)))
        self.assertEqual(D(90), r.lay_stake)
        self.assertEqual(D(40), r.minimum_decisive_cash_profit)

    def test_void_returns_no_cash_profit_bonus_restore_separate(self):
        r = convert_promo(*fixtures(refund=True))
        self.assertEqual(D(0), r.minimum_modeled_cash_profit)
        self.assertEqual(D(100), r.outcomes[-1].noncash_bonus_face_returned)
        m, b, l, t = fixtures(refund=True)
        self.assertEqual(D(0), convert_promo(m, b, l, replace(t, bonus_restored_on_void=False)).outcomes[-1].noncash_bonus_face_returned)

    def test_cash_void_does_not_manufacture_bonus(self):
        r = convert_promo(*fixtures("loss_refund_bonus", True))
        self.assertEqual(D(0), r.outcomes[-1].noncash_bonus_face_returned)

    def test_lay_commission_and_rounded_stake(self):
        m, b, l, t = fixtures()
        r = convert_promo(m, b, replace(l, commission_rate=D(".02")), t)
        self.assertEqual(D("80.32"), r.lay_stake)
        self.assertEqual(D("78.7136"), r.minimum_decisive_cash_profit)

    def test_liability_and_stake_limits(self):
        for limits in (dict(maximum_lay_stake=D(50)), dict(maximum_lay_liability=D(200)),
                       dict(maximum_lay_stake=D(60), maximum_lay_liability=D(200))):
            r = convert_promo(*fixtures(), **limits)
            self.assertEqual(D(50), r.lay_stake)
            self.assertEqual(D(50), r.minimum_decisive_cash_profit)
        self.assertEqual(D(0), convert_promo(*fixtures(), maximum_lay_liability=D(0)).lay_stake)

    def test_minimum_odds_and_eligibility_cap(self):
        m, b, l, t = fixtures()
        with self.assertRaises(ToolInputError):
            convert_promo(m, replace(b, decimal_odds=D("1.4")), l, t)
        with self.assertRaises(ToolInputError):
            replace(t, eligible_stake_cap=D(99))
        with self.assertRaises(ToolInputError):
            replace(t, kind="risk_free")

    def test_wrong_selection_contract_and_book(self):
        m, b, l, t = fixtures()
        for bad in (replace(l, selection_id="b"), replace(l, contract_id="different"), replace(l, sportsbook_id="book")):
            with self.assertRaises(ToolInputError):
                convert_promo(m, b, bad, t)

    def test_back_commission_and_fractional_face_rejected(self):
        m, b, l, t = fixtures()
        with self.assertRaises(ToolInputError):
            convert_promo(m, replace(b, commission_rate=D(".1")), l, t)
        with self.assertRaises(ToolInputError):
            convert_promo(m, b, l, replace(t, face_value=D("99.999")))

    def test_outright_lay_covers_all_other_entrants(self):
        m, b, l, t = fixtures()
        m = replace(m, market_key="outrights", selection_ids=("a", "b", "c", "d"))
        r = convert_promo(m, replace(b, market_key="outrights"), replace(l, market_key="outrights_lay"), t)
        self.assertEqual(D(80), r.minimum_decisive_cash_profit)

    def test_rounded_optimizer_against_exhaustive_cash_grid(self):
        for kind in ("bonus_stake_not_returned", "bonus_stake_returned_as_cash", "loss_refund_cash", "loss_refund_bonus"):
            m, b, l, t = fixtures(kind)
            t = replace(t, face_value=D(2), loss_refund_cap=D(1) if kind.startswith("loss") else D(0))
            for odds in (D("1.5"), D("3.01"), D(7)):
                l = replace(l, decimal_odds=odds, commission_rate=D(".03"))
                r = convert_promo(m, b, l, t, stake_increment=D(".1"), maximum_lay_stake=D(5))
                win = Fraction(10 if kind == "bonus_stake_returned_as_cash" else 8)
                loss = Fraction(0 if kind.startswith("bonus") else -1 if kind == "loss_refund_cash" else -2)
                candidates = [(min(win - Fraction(n, 10) * (Fraction(odds) - 1), loss + Fraction(n, 10) * Fraction(97, 100)), -n) for n in range(51)]
                expected, negative_n = max(candidates)
                self.assertEqual(Fraction(-negative_n, 10), Fraction(r.lay_stake))
                self.assertEqual(expected, Fraction(r.minimum_decisive_cash_profit))

    def test_precision_independent(self):
        expected = convert_promo(*fixtures())
        with localcontext() as ctx:
            ctx.prec = 2
            self.assertEqual(expected, convert_promo(*fixtures()))

    def test_query_bridge(self):
        from corner.featured_queries import CalculationInputs
        m, b, l, t = fixtures()
        inputs = CalculationInputs(m, (b, l), ())
        self.assertEqual(convert_promo(m, b, l, t), inputs.promo_conversion(back_quote_id="back", lay_quote_id="lay", terms=t))

    def test_opposite_back_hedge(self):
        m, b, l, t = fixtures()
        hedge = replace(l, market_key="h2h", selection_id="b", decimal_odds=D("1.25"))
        result = convert_promo_back_hedge(m, b, hedge, t)
        self.assertEqual(D(320), result.hedge_stake)
        self.assertEqual(D(80), result.minimum_decisive_cash_profit)
        self.assertEqual(D(320), result.upfront_cash_required)

    def test_opposite_back_rejects_uncovered_draw(self):
        m, b, l, t = fixtures()
        with self.assertRaisesRegex(ToolInputError, "two exhaustive"):
            convert_promo_back_hedge(replace(m, selection_ids=("a", "b", "draw")), b,
                                    replace(l, market_key="h2h", selection_id="b"), t)

    def test_opposite_back_cap_and_commission(self):
        m, b, l, t = fixtures()
        hedge = replace(l, market_key="h2h", selection_id="b", decimal_odds=D(2), commission_rate=D(".02"))
        r = convert_promo_back_hedge(m, b, hedge, t, maximum_hedge_stake=D(100))
        self.assertEqual(D(98), r.minimum_decisive_cash_profit)
        self.assertEqual(D(100), r.hedge_stake)

    def test_opposite_back_spread_common_push(self):
        m, b, l, t = fixtures(refund=True)
        m = replace(m, market_key="spreads")
        r = convert_promo_back_hedge(m, replace(b, market_key="spreads"),
                                    replace(l, market_key="spreads", selection_id="b", decimal_odds=D(2)), t)
        self.assertEqual(D(200), r.minimum_decisive_cash_profit)
        self.assertEqual(D(0), r.minimum_modeled_cash_profit)

    def test_back_hedge_query_bridge(self):
        from corner.featured_queries import CalculationInputs
        m, b, l, t = fixtures()
        hedge = replace(l, market_key="h2h", selection_id="b")
        inputs = CalculationInputs(m, (b, hedge), ())
        self.assertEqual(convert_promo_back_hedge(m, b, hedge, t), inputs.promo_back_conversion(promo_quote_id="back", hedge_quote_id="lay", terms=t))


if __name__ == "__main__":
    unittest.main()
