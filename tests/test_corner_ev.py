"""Synthetic, policy-explicit tests; freshness values are not production defaults."""

import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN, localcontext

from corner.ev import (
    EVConfiguration, EVSnapshot, InputIssue, MarketContract, OutcomeContract,
    ProviderTimePolicy, QuoteInput, Reason, evaluate_ev,
)


D = Decimal
NOW = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)


def inputs():
    contract = MarketContract('market', 'competition', 'moneyline', 'full_game',
                              'two_way_no_push', 'synthetic validated settlement rules v1',
                              (OutcomeContract('a', 'participant-a'), OutcomeContract('b', 'participant-b')))
    quotes = tuple(QuoteInput(identifier, 'market', outcome, book, D(price), 'active', NOW, NOW)
                   for identifier, outcome, book, price in (
                       ('target', 'a', 'target-book', '2.25'),
                       ('r1a', 'a', 'ref-1', '1.80'), ('r1b', 'b', 'ref-1', '2.10'),
                       ('r2a', 'a', 'ref-2', '2.00'), ('r2b', 'b', 'ref-2', '2.00')))
    snapshot = EVSnapshot(NOW, 'pregame', 'synthetic phase validation', contract, 'target', quotes)
    config = EVConfiguration('test-config-v1', 'competition', 'moneyline', 'full_game',
                             ('ref-1', 'ref-2'), timedelta(seconds=10), timedelta(seconds=20),
                             timedelta(seconds=20), ProviderTimePolicy.IGNORE, None, 40)
    return snapshot, config


def change_quote(snapshot, identifier, **changes):
    return replace(snapshot, quotes=tuple(replace(q, **changes) if q.observation_id == identifier else q
                                          for q in snapshot.quotes))


class CanonicalEVTests(unittest.TestCase):
    def test_known_math_and_exact_audit_inputs(self):
        snapshot, config = inputs()
        result = evaluate_ev(snapshot, config)
        self.assertIsNone(result.reason)
        # Ref 1 gives 7/13, ref 2 gives 1/2: consensus 27/52; EV 35/208.
        with localcontext() as ctx:
            ctx.prec = 40
            self.assertLess(abs(result.fair_probability - D(27) / D(52)), D('1e-38'))
            self.assertLess(abs(result.ev_ratio - D(35) / D(208)), D('1e-38'))
        self.assertEqual(snapshot, result.snapshot)
        self.assertEqual(config, result.configuration)
        self.assertEqual(('r1a', 'r1b'), result.reference_estimates[0].observation_ids)
        self.assertEqual(('r2a', 'r2b'), result.reference_estimates[1].observation_ids)
        self.assertEqual('1.0.0', result.engine_version)

    def test_deterministic_under_input_order_and_ambient_decimal_context(self):
        snapshot, config = inputs()
        expected = evaluate_ev(snapshot, config)
        with localcontext() as ctx:
            ctx.prec = 6
            ctx.rounding = ROUND_DOWN
            actual = evaluate_ev(replace(snapshot, quotes=tuple(reversed(snapshot.quotes))), config)
        self.assertEqual(expected.ev_ratio, actual.ev_ratio)
        self.assertEqual(expected.reference_estimates, actual.reference_estimates)

    def test_zero_and_negative_ev_are_successful_estimates(self):
        snapshot, config = inputs()
        snapshot = change_quote(snapshot, 'r1a', decimal_odds=D('2'))
        snapshot = change_quote(snapshot, 'r1b', decimal_odds=D('2'))
        for price, expected in [('2', '0'), ('1.9', '-0.05')]:
            result = evaluate_ev(change_quote(snapshot, 'target', decimal_odds=D(price)), config)
            self.assertIsNone(result.reason)
            self.assertEqual(D(expected), result.ev_ratio)

    def test_no_fallback_from_unavailable_target(self):
        snapshot, config = inputs()
        result = evaluate_ev(change_quote(snapshot, 'target', quote_state='unavailable', decimal_odds=None), config)
        self.assertEqual(Reason.INACTIVE_TARGET, result.reason)
        self.assertIsNone(result.ev_ratio)
        old = replace(snapshot.quotes[0], observation_id='old', observed_at=NOW - timedelta(seconds=1))
        self.assertEqual(Reason.INVALID_SNAPSHOT,
                         evaluate_ev(replace(snapshot, quotes=snapshot.quotes + (old,)), config).reason)

    def test_target_age_inclusive_boundary_and_future_rejection(self):
        snapshot, config = inputs()
        at_boundary = change_quote(snapshot, 'target', observed_at=NOW - config.target_max_age)
        self.assertIsNone(evaluate_ev(at_boundary, config).reason)
        self.assertEqual(Reason.STALE_TARGET, evaluate_ev(change_quote(
            at_boundary, 'target', observed_at=NOW - config.target_max_age - timedelta(microseconds=1)), config).reason)
        self.assertEqual(Reason.FUTURE_TARGET, evaluate_ev(change_quote(
            snapshot, 'target', observed_at=NOW + timedelta(microseconds=1)), config).reason)

    def test_reference_age_inclusive_boundary(self):
        snapshot, config = inputs()
        snapshot = change_quote(snapshot, 'r1a', observed_at=NOW - config.reference_max_age)
        self.assertIsNone(evaluate_ev(snapshot, config).reason)
        result = evaluate_ev(change_quote(snapshot, 'r1a', observed_at=NOW - config.reference_max_age
                                          - timedelta(microseconds=1)), config)
        self.assertEqual(Reason.INSUFFICIENT_REFERENCE_COVERAGE, result.reason)
        self.assertEqual(InputIssue.STALE, result.reference_exclusions[0].issue)

    def test_global_skew_includes_both_sides_and_target(self):
        snapshot, config = inputs()
        config = replace(config, max_input_skew=timedelta(seconds=5))
        for identifier in ('target', 'r1a', 'r1b'):
            boundary = change_quote(snapshot, identifier, observed_at=NOW - config.max_input_skew)
            self.assertIsNone(evaluate_ev(boundary, config).reason)
            outside = change_quote(boundary, identifier, observed_at=NOW - config.max_input_skew
                                    - timedelta(microseconds=1))
            self.assertEqual(Reason.INPUT_SKEW, evaluate_ev(outside, config).reason)

    def test_incomplete_or_inactive_reference_is_excluded_as_whole_book(self):
        snapshot, config = inputs()
        for broken in (
            replace(snapshot, quotes=tuple(q for q in snapshot.quotes if q.observation_id != 'r1b')),
            change_quote(snapshot, 'r1b', quote_state='suspended', decimal_odds=None),
        ):
            result = evaluate_ev(broken, config)
            self.assertEqual(Reason.INSUFFICIENT_REFERENCE_COVERAGE, result.reason)
            self.assertEqual('ref-1', result.reference_exclusions[0].sportsbook_id)
        # Completeness cannot be assembled using prices from different books.
        split = change_quote(snapshot, 'r1b', sportsbook_id='unconfigured')
        self.assertEqual(Reason.INSUFFICIENT_REFERENCE_COVERAGE, evaluate_ev(split, config).reason)

    def test_target_book_cannot_count_as_reference(self):
        snapshot, config = inputs()
        config = replace(config, reference_sportsbook_ids=('target-book', 'ref-1'))
        result = evaluate_ev(snapshot, config)
        self.assertEqual(Reason.INSUFFICIENT_REFERENCE_COVERAGE, result.reason)
        self.assertEqual(InputIssue.TARGET_BOOK, result.reference_exclusions[0].issue)

    def test_bad_book_can_be_excluded_when_two_complete_books_remain(self):
        snapshot, config = inputs()
        extra = replace(snapshot.quotes[1], observation_id='r3a', sportsbook_id='ref-3')
        result = evaluate_ev(replace(snapshot, quotes=snapshot.quotes + (extra,)),
                             replace(config, reference_sportsbook_ids=('ref-1', 'ref-2', 'ref-3')))
        self.assertIsNone(result.reason)
        self.assertEqual(2, len(result.reference_estimates))
        self.assertEqual(InputIssue.INCOMPLETE, result.reference_exclusions[0].issue)

    def test_provider_timestamp_policies(self):
        snapshot, config = inputs()
        missing = change_quote(snapshot, 'target', provider_updated_at=None)
        old = change_quote(snapshot, 'target', provider_updated_at=NOW - timedelta(minutes=10))
        self.assertIsNone(evaluate_ev(old, config).reason)  # IGNORE is explicit.
        for policy in (ProviderTimePolicy.REQUIRE, ProviderTimePolicy.MAX_AGE_IF_PRESENT):
            chosen = replace(config, provider_time_policy=policy, provider_max_age=timedelta(seconds=30))
            expected = Reason.TARGET_PROVIDER_TIME if policy == ProviderTimePolicy.REQUIRE else None
            self.assertEqual(expected, evaluate_ev(missing, chosen).reason)
            self.assertEqual(Reason.TARGET_PROVIDER_TIME, evaluate_ev(old, chosen).reason)
            edge = change_quote(snapshot, 'target', provider_updated_at=NOW - timedelta(seconds=30))
            self.assertIsNone(evaluate_ev(edge, chosen).reason)
            future = change_quote(snapshot, 'target', provider_updated_at=NOW + timedelta(seconds=1))
            self.assertEqual(Reason.TARGET_PROVIDER_TIME, evaluate_ev(future, chosen).reason)
        required = replace(config, provider_time_policy=ProviderTimePolicy.REQUIRE,
                           provider_max_age=timedelta(seconds=30))
        result = evaluate_ev(change_quote(snapshot, 'r1b', provider_updated_at=None), required)
        self.assertEqual(InputIssue.MISSING_PROVIDER_TIME, result.reference_exclusions[0].issue)

    def test_unsupported_phase_and_unproven_settlement(self):
        snapshot, config = inputs()
        for phase in ('live', 'unknown', 'finished'):
            self.assertEqual(Reason.UNSUPPORTED_PHASE,
                             evaluate_ev(replace(snapshot, event_phase=phase), config).reason)
        self.assertEqual(Reason.UNSUPPORTED_PHASE,
                         evaluate_ev(replace(snapshot, phase_evidence=''), config).reason)
        for contract in (
            replace(snapshot.contract, settlement_policy='push_possible'),
            replace(snapshot.contract, settlement_evidence=''),
            replace(snapshot.contract, outcomes=snapshot.contract.outcomes + (OutcomeContract('draw', None),)),
            replace(snapshot.contract, outcomes=(OutcomeContract('a', 'participant-a', D('0')), snapshot.contract.outcomes[1])),
        ):
            self.assertEqual(Reason.UNSUPPORTED_SETTLEMENT,
                             evaluate_ev(replace(snapshot, contract=contract), config).reason)

    def test_configuration_and_canonical_identity_must_match(self):
        snapshot, config = inputs()
        for field in ('competition_id', 'market_type', 'scope'):
            self.assertEqual(Reason.CONFIGURATION_MISMATCH,
                             evaluate_ev(snapshot, replace(config, **{field: 'different'})).reason)
        for changes in (dict(market_id='other-event-market'), dict(outcome_id='unrelated')):
            self.assertEqual(Reason.INVALID_SNAPSHOT,
                             evaluate_ev(change_quote(snapshot, 'r1b', **changes), config).reason)

    def test_invalid_prices_and_naive_timestamps(self):
        snapshot, config = inputs()
        for price in (None, D('NaN'), D('Infinity'), D('1'), D('-2'), 2.25):
            self.assertEqual(Reason.INVALID_TARGET_PRICE,
                             evaluate_ev(change_quote(snapshot, 'target', decimal_odds=price), config).reason)
        self.assertEqual(Reason.INVALID_SNAPSHOT,
                         evaluate_ev(replace(snapshot, evaluated_at=NOW.replace(tzinfo=None)), config).reason)

    def test_configuration_is_immutable_and_requires_explicit_valid_policy(self):
        snapshot, config = inputs()
        with self.assertRaises(FrozenInstanceError):
            config.version = 'changed'
        with self.assertRaises(FrozenInstanceError):
            snapshot.quotes[0].quote_state = 'unavailable'
        for changes in (dict(minimum_reference_books=1), dict(calculation_precision=4),
                        dict(reference_sportsbook_ids=('same', 'same')),
                        dict(target_max_age=timedelta(seconds=-1)),
                        dict(provider_time_policy=ProviderTimePolicy.REQUIRE),
                        dict(no_vig_method='unsupported')):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(config, **changes)


if __name__ == '__main__':
    unittest.main()
