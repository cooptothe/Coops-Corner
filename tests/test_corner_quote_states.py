"""Synthetic canonical state evidence; not captured Odds API responses.

Database tests run only with CORNER_TEST_DATABASE=1 and always roll back.
The synthetic adapter explicitly maps state evidence to a NormalizedQuote.
Provider-specific suspension/removal detection is deliberately outside this test.
"""

import json
import os
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from corner.normalization import normalize_event


def event_fixture():
    return {
        "id": str(uuid4()), "sport_key": "americanfootball_nfl",
        "commence_time": "2026-10-01T00:00:00Z",
        "home_team": "Test Saints", "away_team": "Test Falcons",
        "bookmakers": [{"key": "draftkings", "title": "DraftKings", "markets": [
            {"key": "h2h", "outcomes": [{"name": "Test Saints", "price": 2.25}]}
        ]}],
    }


class QuoteStateValidationTests(unittest.TestCase):
    def test_explicit_unavailable_and_suspended_have_no_price(self):
        quote = normalize_event(event_fixture())[0]
        for state in ("unavailable", "suspended"):
            self.assertEqual(state, replace(
                quote, quote_state_code=state, decimal_odds=None
            ).quote_state_code)

    def test_invalid_state_price_combinations_are_rejected(self):
        quote = normalize_event(event_fixture())[0]
        for state, price in (
            ("active", None), ("active", Decimal("NaN")),
            ("active", Decimal("Infinity")), ("active", Decimal("1")),
            ("unavailable", Decimal("2.15")), ("unknown", None),
        ):
            with self.subTest(state=state, price=price), self.assertRaises(ValueError):
                replace(quote, quote_state_code=state, decimal_odds=price)

    def test_absence_does_not_invent_unavailability(self):
        event = event_fixture()
        event["bookmakers"][0]["markets"][0]["outcomes"] = []
        self.assertEqual([], normalize_event(event))

    def test_missing_price_without_state_evidence_is_rejected(self):
        event = event_fixture()
        event["bookmakers"][0]["markets"][0]["outcomes"][0]["price"] = None
        with self.assertRaises(ValueError):
            normalize_event(event)


@unittest.skipUnless(os.getenv("CORNER_TEST_DATABASE") == "1", "opt-in PostgreSQL tests")
class QuoteStateLedgerTests(unittest.TestCase):
    def setUp(self):
        from db.insert import connect
        self.conn = connect()
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)

    def verify_sequence(self, states, arrival_order=(0, 1, 2)):
        from corner.ingestion import (
            _seed_provider, _create_batch, _create_payload, process_payload,
            _insert_observation,
        )
        event = event_fixture()
        provider = _seed_provider(self.conn)
        batch = _create_batch(self.conn, provider, {"source": "synthetic-state-test"})
        start = datetime(2026, 9, 21, 14, tzinfo=timezone.utc)
        raw = json.dumps(event).encode()
        first = _create_payload(self.conn, batch, provider, start, raw)
        process_payload(self.conn, first, event)
        with self.conn.cursor() as cur:
            cur.execute("SELECT outcome_id, sportsbook_id FROM corner.odds_observations "
                        "WHERE provider_payload_id = %s", (first,))
            outcome, book = cur.fetchone()
        quote = normalize_event(event)[0]
        for index in arrival_order:
            if index == 0:
                continue
            state, price = states[index]
            # Exact bytes retain the explicit synthetic evidence used by this adapter.
            evidence = json.dumps({"synthetic": True, "state": state, "price": price}).encode()
            received = start + timedelta(minutes=index)
            payload = _create_payload(self.conn, batch, provider, received, evidence)
            normalized = replace(quote, quote_state_code=state,
                                 decimal_odds=Decimal(price) if price else None)
            for _ in range(2):  # Replay the same source record, including null-price states.
                _insert_observation(self.conn, payload, provider, outcome, book, normalized, received)
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT o.id, s.code, o.decimal_odds, o.observed_at
                FROM corner.odds_observations o
                JOIN corner.quote_states s ON s.id = o.quote_state_id
                WHERE o.outcome_id = %s AND o.sportsbook_id = %s
                ORDER BY o.observed_at DESC, o.id DESC
            """, (outcome, book))
            rows = cur.fetchall()
        self.assertEqual(3, len(rows))
        self.assertEqual(3, len({row[0] for row in rows}))
        self.assertEqual(
            [(state, Decimal(price) if price else None) for state, price in reversed(states)],
            [(row[1], row[2]) for row in rows],
        )
        self.assertEqual(start + timedelta(minutes=2), rows[0][3])

    def test_unavailable_is_latest_and_all_prices_remain_in_history(self):
        self.verify_sequence([("active", "2.25"), ("active", "2.15"), ("unavailable", None)])

    def test_reactivation_appends_a_new_active_observation(self):
        self.verify_sequence([("active", "2.25"), ("unavailable", None), ("active", "2.30")])

    def test_late_persistence_does_not_resurrect_older_price(self):
        self.verify_sequence(
            [("active", "2.25"), ("active", "2.15"), ("unavailable", None)],
            arrival_order=(0, 2, 1),
        )
