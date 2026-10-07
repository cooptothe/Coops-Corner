"""Rollback-only selector/engine integration with explicit synthetic policies."""

import json
import os
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from corner.dispositions import DecisionAuthority, DispositionCommand, record_disposition
from corner.ev import EVConfiguration, InputIssue, ProviderTimePolicy, Reason, evaluate_ev
from corner.ev_selection import MarketValidation, SelectionReason, select_ev_snapshot
from test_corner_quote_states import event_fixture


@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE') == '1', 'opt-in PostgreSQL tests')
class EVSelectionTests(unittest.TestCase):
    def setUp(self):
        from db.insert import connect
        from corner.ingestion import _seed_provider, _create_batch, _create_payload, process_payload
        self.conn = connect()
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.time = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)
        self.provider = _seed_provider(self.conn)
        self.batch = _create_batch(self.conn, self.provider, {'source': 'synthetic-ev-selection'})
        event = event_fixture()
        event['bookmakers'] = [
            {'key': book, 'title': book, 'markets': [{'key': 'h2h', 'outcomes': [
                {'name': event['home_team'], 'price': home},
                {'name': event['away_team'], 'price': away}]}]}
            for book, home, away in [('draftkings', 2.25, 3), ('pinnacle', 1.8, 2.1), ('fanduel', 2, 2)]
        ]
        payload = _create_payload(self.conn, self.batch, self.provider, self.time, json.dumps(event).encode())
        process_payload(self.conn, payload, event)
        with self.conn.cursor() as cur:
            cur.execute('''SELECT b.code, side.code, o.id, o.outcome_id, o.sportsbook_id,
                                  m.id, m.event_id, e.competition_id
                           FROM corner.odds_observations o
                           JOIN corner.sportsbooks b ON b.id=o.sportsbook_id
                           JOIN corner.outcomes oc ON oc.id=o.outcome_id
                           JOIN corner.outcome_sides side ON side.id=oc.outcome_side_id
                           JOIN corner.markets m ON m.id=oc.market_id
                           JOIN corner.events e ON e.id=m.event_id
                           WHERE o.provider_payload_id=%s''', (payload,))
            self.rows = {(row[0], row[1]): row for row in cur.fetchall()}
        row = self.rows['draftkings', 'home']
        self.target_id, self.outcome_id, self.book_id, self.market_id, self.event_id, competition = row[2:]
        self.reference_ids = tuple(self.rows[book, 'home'][4] for book in ('pinnacle', 'fanduel'))
        self.config = EVConfiguration('synthetic-selection-v1', competition, 'moneyline', 'full_game',
            self.reference_ids, timedelta(seconds=30), timedelta(seconds=30), timedelta(seconds=30),
            ProviderTimePolicy.IGNORE, None, 40)
        self.validation = MarketValidation(self.event_id, self.market_id, 'pregame',
                                          'synthetic phase evidence', 'two_way_no_push',
                                          'synthetic no-push settlement validation')

    def select(self, **changes):
        args = dict(target_outcome_id=self.outcome_id, target_sportsbook_id=self.book_id,
                    evaluated_at=self.time + timedelta(seconds=2), configuration=self.config,
                    validation=self.validation)
        args.update(changes)
        return select_ev_snapshot(self.conn, **args)

    def decide(self, observation):
        return record_disposition(self.conn, authority=DecisionAuthority('service', 'selection-test'),
            command=DispositionCommand(str(uuid4()), observation, 'rejected', 'Synthetic rejection', self.time))

    def append(self, original, state='active', price='2.10', outcome=None, observed_at=None):
        from corner.ingestion import _create_payload, _ensure_vocabulary
        received = observed_at or self.time + timedelta(seconds=1)
        raw = json.dumps({'synthetic': True, 'original': original, 'state': state, 'price': price}).encode()
        payload = _create_payload(self.conn, self.batch, self.provider, received, raw)
        with self.conn.cursor() as cur:
            state_id = _ensure_vocabulary(cur, 'quote_states', state, state.title())
            cur.execute('''INSERT INTO corner.odds_observations
                (provider_payload_id, provider_id, outcome_id, sportsbook_id, quote_state_id,
                 source_record_key, decimal_odds, observed_at)
                SELECT %s, provider_id, COALESCE(%s::uuid, outcome_id), sportsbook_id, %s,
                       'synthetic/0', %s, %s FROM corner.odds_observations WHERE id=%s RETURNING id''',
                (payload, outcome, state_id, price, received, original))
            return cur.fetchone()[0]

    def test_complete_selection_reaches_engine_with_exact_ids(self):
        selected = self.select()
        self.assertIsNone(selected.reason)
        result = evaluate_ev(selected.snapshot, selected.configuration)
        self.assertIsNone(result.reason)
        self.assertEqual(self.target_id, result.snapshot.target_observation_id)
        expected = {self.rows[book, side][2] for book in ('pinnacle', 'fanduel') for side in ('home', 'away')}
        self.assertEqual(expected, {oid for estimate in result.reference_estimates for oid in estimate.observation_ids})
        self.assertEqual(5, len(result.snapshot.quotes))
        self.assertLess(abs(result.ev_ratio - Decimal('0.1682692307692307692307692308')), Decimal('1e-26'))

    def test_unavailable_reference_reaches_engine_without_fallback(self):
        original = self.rows['pinnacle', 'away'][2]
        latest = self.append(original, 'unavailable', None)
        selected = self.select()
        ids = {q.observation_id for q in selected.snapshot.quotes}
        self.assertIn(latest, ids)
        self.assertNotIn(original, ids)
        result = evaluate_ev(selected.snapshot, self.config)
        self.assertEqual(Reason.INSUFFICIENT_REFERENCE_COVERAGE, result.reason)
        self.assertEqual(InputIssue.INACTIVE, result.reference_exclusions[0].issue)

    def test_rejected_latest_exposes_original_timestamp(self):
        latest = self.append(self.target_id, price='9')
        self.decide(latest)
        selected = self.select()
        target = next(q for q in selected.snapshot.quotes if q.observation_id == self.target_id)
        self.assertEqual(self.time, target.observed_at)
        self.assertEqual(Decimal('2.25'), target.decimal_odds)
        self.assertNotIn(latest, {q.observation_id for q in selected.snapshot.quotes})

    def test_target_book_excluded_even_when_configured_as_reference(self):
        config = replace(self.config, reference_sportsbook_ids=self.reference_ids + (self.book_id,))
        selected = self.select(configuration=config)
        self.assertEqual([self.target_id], [q.observation_id for q in selected.snapshot.quotes
                                           if q.sportsbook_id == self.book_id])
        result = evaluate_ev(selected.snapshot, config)
        self.assertIsNone(result.reason)
        self.assertNotIn(self.book_id, {e.sportsbook_id for e in result.reference_estimates})

    def test_incomplete_reference_set_is_not_fabricated(self):
        self.decide(self.rows['pinnacle', 'away'][2])
        selected = self.select()
        self.assertEqual(2, len(selected.snapshot.contract.outcomes))
        self.assertEqual(4, len(selected.snapshot.quotes))
        result = evaluate_ev(selected.snapshot, self.config)
        self.assertEqual(Reason.INSUFFICIENT_REFERENCE_COVERAGE, result.reason)
        self.assertEqual(InputIssue.INCOMPLETE, result.reference_exclusions[0].issue)

    def test_three_way_contract_survives_even_without_draw_quotes(self):
        from corner.ingestion import _resolve_outcome
        draw = _resolve_outcome(self.conn, self.market_id, None, 'draw', None)
        selected = self.select(validation=replace(self.validation, settlement_policy='three_way_no_push'))
        self.assertEqual(3, len(selected.snapshot.contract.outcomes))
        self.assertIn(draw, {o.outcome_id for o in selected.snapshot.contract.outcomes})
        self.assertEqual(Reason.UNSUPPORTED_SETTLEMENT, evaluate_ev(selected.snapshot, self.config).reason)

    def test_unrelated_markets_and_alternate_points_not_combined(self):
        from corner.ingestion import _resolve_market, _resolve_outcome
        with self.conn.cursor() as cur:
            cur.execute('SELECT selected_participant_id FROM corner.outcomes WHERE id=%s', (self.outcome_id,))
            participant = cur.fetchone()[0]
        spread = _resolve_market(self.conn, self.event_id, 'spread', 'full_game')
        for point in (Decimal('-3.5'), Decimal('-4.5')):
            outcome = _resolve_outcome(self.conn, spread, participant, 'home', point)
            self.append(self.rows['pinnacle', 'home'][2], outcome=outcome)
        selected = self.select()
        self.assertEqual(5, len(selected.snapshot.quotes))
        self.assertTrue(all(q.market_id == self.market_id for q in selected.snapshot.quotes))
        # Unexpected pointed outcomes in the target market must not be hidden either.
        extra = _resolve_outcome(self.conn, self.market_id, participant, 'home', Decimal('1.5'))
        selected = self.select()
        self.assertIn(extra, {o.outcome_id for o in selected.snapshot.contract.outcomes})
        self.assertEqual(Reason.UNSUPPORTED_SETTLEMENT, evaluate_ev(selected.snapshot, self.config).reason)

    def test_freshness_and_state_remain_engine_decisions(self):
        selected = self.select(evaluated_at=self.time + timedelta(hours=1))
        self.assertIsNone(selected.reason)
        self.assertEqual(5, len(selected.snapshot.quotes))
        self.assertEqual(Reason.STALE_TARGET, evaluate_ev(selected.snapshot, self.config).reason)
        latest = self.append(self.target_id, 'unavailable', None)
        selected = self.select()
        self.assertEqual(latest, selected.snapshot.target_observation_id)
        self.assertEqual(Reason.INACTIVE_TARGET, evaluate_ev(selected.snapshot, self.config).reason)

    def test_selection_failure_reasons_are_explicit(self):
        self.assertEqual(SelectionReason.UNKNOWN_TARGET_OUTCOME,
                         self.select(target_outcome_id=str(uuid4())).reason)
        self.assertEqual(SelectionReason.CONFIGURATION_MISMATCH,
                         self.select(configuration=replace(self.config, competition_id=str(uuid4()))).reason)
        self.assertEqual(SelectionReason.VALIDATION_MISMATCH,
                         self.select(validation=replace(self.validation, event_id=str(uuid4()))).reason)
        self.decide(self.target_id)
        selected = self.select()
        self.assertIsNone(selected.snapshot)
        self.assertEqual(SelectionReason.NO_TRUSTED_TARGET, selected.reason)

    def test_saved_snapshot_remains_reproducible_after_new_decision(self):
        selected = self.select()
        before = evaluate_ev(selected.snapshot, selected.configuration)
        self.decide(self.rows['pinnacle', 'away'][2])
        self.assertEqual(before, evaluate_ev(selected.snapshot, selected.configuration))
        after = self.select()
        self.assertEqual(Reason.INSUFFICIENT_REFERENCE_COVERAGE, evaluate_ev(after.snapshot, self.config).reason)

    def test_selector_executes_one_read_statement_and_does_not_commit(self):
        from unittest.mock import MagicMock
        wrapped = MagicMock()
        from psycopg2.extras import RealDictCursor
        with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
            tracked_cursor = MagicMock(wraps=cursor)
            wrapped.cursor.return_value.__enter__.return_value = tracked_cursor
            selected = select_ev_snapshot(wrapped, target_outcome_id=self.outcome_id,
                target_sportsbook_id=self.book_id, evaluated_at=self.time,
                configuration=self.config, validation=self.validation)
            self.assertIsNone(selected.reason)
            self.assertEqual(1, tracked_cursor.execute.call_count)
            wrapped.commit.assert_not_called()
            wrapped.rollback.assert_not_called()
