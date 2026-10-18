from dataclasses import replace
from decimal import Decimal as D, localcontext
from fractions import Fraction
import unittest

from corner.featured_middles import LineBet, calculate_middle, find_middles
from corner.featured_tools import ToolInputError


def leg(side, line, **kwargs):
    return LineBet(**(dict(quote_id=side, sportsbook_id=side, contract_id="fixture:game:full:rules",
                          market_key="totals" if side in {"over", "under"} else "spreads", side=side,
                          line=D(line), decimal_odds=D("1.9"), stake=D(100), commission_rate=D(0)) | kwargs))


def middle(first=None, second=None, **kwargs):
    return calculate_middle(contract_id="fixture:game:full:rules", first=first or leg("over", "210.5"),
                            second=second or leg("under", "213.5"), refund_possible=kwargs.pop("refund_possible", False), **kwargs)


def at(result, score):
    r = next(r for r in result.ranges if (r.minimum_score is None or score >= r.minimum_score)
             and (r.maximum_score is None or score <= r.maximum_score))
    payoff = next(p for p in result.payoff.states if p.state_id == r.state_id)
    return r, payoff.net_profit


class MiddleTests(unittest.TestCase):
    def test_snapshot_digest_preserves_existing_wire_bytes(self):
        import hashlib, json
        from api.catalog import digest, wire
        from datetime import datetime, timezone
        value = {'calculation': middle(), 'time': datetime(2026, 10, 18, tzinfo=timezone.utc),
                 'nested': [None, True, 1, 'text', D('1.900')]}
        expected = hashlib.sha256(json.dumps(wire(value), sort_keys=True,
            separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        self.assertEqual(digest(value), expected)

    def test_discovery_prefilter_matches_exhaustive_quarter_line_payoffs(self):
        from corner.featured_middles import _full_win_window
        # Include negative spread margins, quarter splits, pushes and zero totals.
        for high, low in (("home", "away"), ("over", "under")):
            points = [D(i) / 4 for i in range(-8 if high == "home" else 0, 17)]
            for first_line in points:
                for second_line in points:
                    first, second = leg(high, str(first_line)), leg(low, str(second_line))
                    exact = middle(first, second)
                    self.assertEqual(bool(exact.double_win_ranges),
                        _full_win_window(first.market_key, high, first_line, low, second_line))
                    found = find_middles((first, second), refund_possible=False)
                    self.assertEqual(found, (exact,) if exact.double_win_ranges else ())


    def test_total_double_win_window_and_worst_loss(self):
        result = middle()
        self.assertEqual(((211, 213),), result.double_win_ranges)
        self.assertEqual(D(180), at(result, 212)[1])
        self.assertEqual(D(-10), result.payoff.minimum_modeled_profit)
        self.assertIsNone(result.payoff.expected_profit)

    def test_integer_push_boundaries(self):
        r = middle(leg("over", "210"), leg("under", "214"))
        self.assertEqual(D(90), at(r, 210)[1])
        self.assertEqual(D(90), at(r, 214)[1])
        self.assertEqual(((211, 213),), r.double_win_ranges)

    def test_spread_uses_home_margin_with_away_sign(self):
        r = middle(leg("home", "-3.5"), leg("away", "6.5"))
        self.assertEqual("home_minus_away", r.coordinate)
        self.assertEqual(((4, 6),), r.double_win_ranges)
        self.assertEqual(D(-10), at(r, -20)[1])
        self.assertEqual(D(180), at(r, 5)[1])

    def test_negative_margin_middle(self):
        r = middle(leg("home", "6.5"), leg("away", "-3.5"))
        self.assertEqual(((-6, -4),), r.double_win_ranges)

    def test_same_line_has_no_middle(self):
        r = middle(leg("over", "210"), leg("under", "210"))
        self.assertEqual((), r.double_win_ranges)
        self.assertEqual(D(0), at(r, 210)[1])

    def test_reverse_lines_report_double_loss_not_fake_middle(self):
        r = middle(leg("over", "214.5"), leg("under", "210.5"))
        self.assertEqual((), r.double_win_ranges)
        self.assertEqual(D(-200), r.payoff.minimum_modeled_profit)

    def test_quarter_lines_preserve_half_push(self):
        r = middle(leg("over", "210.25"), leg("under", "212.75"))
        self.assertEqual(D(40), at(r, 210)[1])  # -50 + 90
        self.assertEqual(D(40), at(r, 213)[1])
        self.assertEqual(((211, 212),), r.double_win_ranges)

    def test_quarter_spread_signs(self):
        r = middle(leg("home", "-3.25"), leg("away", "5.75"))
        self.assertEqual(D(40), at(r, 3)[1])
        self.assertEqual(D(40), at(r, 6)[1])

    def test_ev_requires_complete_range_model_including_void(self):
        r = middle(refund_possible=True)
        probs = tuple((p.state_id, D(".1") if p.state_id == "common_refund" else
                      D(".1") if p.net_profit > 0 else D(".4")) for p in r.payoff.states)
        result = middle(refund_possible=True, state_probabilities=probs, probability_model_id="fixture:distribution")
        self.assertEqual(D(10), result.payoff.expected_profit)
        with self.assertRaises(ToolInputError):
            middle(refund_possible=True, state_probabilities=probs[:-1], probability_model_id="fixture")

    def test_same_book_wrong_contract_same_side_rejected(self):
        a, b = leg("over", "210"), leg("under", "214")
        for bad in (replace(b, sportsbook_id=a.sportsbook_id), replace(b, contract_id="another-event"), replace(b, side="over")):
            with self.assertRaises(ToolInputError):
                middle(a, bad)

    def test_invalid_lines_and_cash_increments_rejected(self):
        for bad in ("1.1", "NaN", "-1", "1000001"):
            with self.assertRaises(ToolInputError):
                leg("over", bad)
        with self.assertRaises(ToolInputError):
            middle(leg("over", "210", stake=D("1.005")))

    def test_range_partition_against_direct_settlement_oracle(self):
        # Independent enumeration across integer/half/quarter and reverse lines.
        for family in ("spreads", "totals"):
            for x in ("2", "2.25", "2.5", "2.75", "3"):
                for y in ("1.75", "2", "2.5", "3.25", "4"):
                    a = leg("home" if family == "spreads" else "over", str(-D(x)) if family == "spreads" else x)
                    b = leg("away" if family == "spreads" else "under", y)
                    result = middle(a, b)
                    for score in range(-8 if family == "spreads" else 0, 10):
                        matches = [r for r in result.ranges if (r.minimum_score is None or r.minimum_score <= score)
                                   and (r.maximum_score is None or score <= r.maximum_score)]
                        self.assertEqual(1, len(matches))
                        expected = Fraction(0)
                        for bet in (a, b):
                            line = Fraction(bet.line)
                            parts = [line] if (2 * line).denominator == 1 else [Fraction((2 * line).__floor__(), 2), Fraction((2 * line).__ceil__(), 2)]
                            for part in parts:
                                delta = score + part if bet.side == "home" else part - score if bet.side in {"away", "under"} else score - part
                                expected += (Fraction(90) if delta > 0 else Fraction(-100) if delta < 0 else 0) / len(parts)
                        self.assertEqual(expected, Fraction(at(result, score)[1]))

    def test_ambient_precision_independent(self):
        expected = middle()
        with localcontext() as ctx:
            ctx.prec = 2
            self.assertEqual(expected, middle())

    def test_discovery_is_bound_to_contract_book_and_direction(self):
        bets = (leg("over", "210"), leg("under", "214"),
                leg("under", "212", quote_id="other-game", contract_id="other-game"),
                leg("under", "216", quote_id="same-book", sportsbook_id="over"))
        found = find_middles(bets, refund_possible=True)
        self.assertEqual(1, len(found))
        self.assertEqual(found, find_middles(reversed(bets), refund_possible=True))

    def test_discovery_bound_and_duplicate_rejected(self):
        bets = (leg("over", "210"), leg("under", "214"), leg("under", "215", quote_id="u2"))
        with self.assertRaisesRegex(ToolInputError, "bound exceeded"):
            find_middles(bets, refund_possible=False, maximum_pair_checks=1)
        with self.assertRaises(ToolInputError):
            find_middles((bets[0], bets[0]), refund_possible=False)


if __name__ == "__main__":
    unittest.main()
