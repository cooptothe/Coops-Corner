"""Real PostgreSQL projection tests. All synthetic evidence rolls back."""

import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from corner.dispositions import DecisionAuthority, DispositionCommand, record_disposition
from test_corner_quote_states import event_fixture


@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE') == '1', 'opt-in PostgreSQL tests')
class TrustedQuoteTests(unittest.TestCase):
    def setUp(self):
        from db.insert import connect
        from corner.ingestion import _seed_provider, _create_batch, _create_payload, process_payload
        self.conn = connect()
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.time = datetime(2000, 1, 1, tzinfo=timezone.utc)
        provider = _seed_provider(self.conn)
        batch = _create_batch(self.conn, provider, {'source': 'trusted-quote-test'})
        event = event_fixture()
        payload = _create_payload(self.conn, batch, provider, self.time, json.dumps(event).encode())
        process_payload(self.conn, payload, event)
        with self.conn.cursor() as cur:
            cur.execute('SELECT id, outcome_id, sportsbook_id FROM corner.odds_observations '
                        'WHERE provider_payload_id = %s', (payload,))
            self.first, self.outcome, self.book = cur.fetchone()

    def append(self, minute=1, state='active', price='2.15', identifier=None):
        identifier = identifier or str(uuid4())
        with self.conn.cursor() as cur:
            cur.execute('INSERT INTO corner.quote_states (code, display_name) VALUES (%s, %s) '
                        'ON CONFLICT (code) DO NOTHING', (state, state.title()))
            cur.execute('''
                INSERT INTO corner.odds_observations
                (id, provider_payload_id, provider_id, outcome_id, sportsbook_id, quote_state_id,
                 source_record_key, decimal_odds, observed_at)
                SELECT %s, provider_payload_id, provider_id, outcome_id, sportsbook_id,
                       (SELECT id FROM corner.quote_states WHERE code = %s), %s, %s, %s
                FROM corner.odds_observations WHERE id = %s
            ''', (identifier, state, 'synthetic/' + identifier, price,
                  self.time + timedelta(minutes=minute), self.first))
        return identifier

    def decide(self, observation, disposition, minute=5):
        return record_disposition(self.conn, authority=DecisionAuthority('service', 'projection-test'),
            command=DispositionCommand(str(uuid4()), observation, disposition, 'Synthetic test',
                                       self.time + timedelta(minutes=minute)))

    def current(self):
        from psycopg2.extras import RealDictCursor
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT * FROM corner.trusted_current_quotes '
                        'WHERE outcome_id = %s AND sportsbook_id = %s', (self.outcome, self.book))
            return cur.fetchone()

    def test_default_eligibility_and_no_freshness_cutoff(self):
        row = self.current()
        self.assertEqual(self.first, row['observation_id'])
        self.assertEqual(self.time, row['observed_at'])
        self.assertIsNone(row['latest_disposition_id'])
        self.assertIsNone(row['latest_disposition_code'])

    def test_unavailable_and_suspended_win_over_older_active(self):
        for minute, state in enumerate(('unavailable', 'suspended'), start=1):
            latest = self.append(minute=minute, state=state, price=None)
            row = self.current()
            self.assertEqual(latest, row['observation_id'])
            self.assertIsNone(row['decimal_odds'])
            with self.conn.cursor() as cur:
                cur.execute('SELECT code FROM corner.quote_states WHERE id = %s', (row['quote_state_id'],))
                self.assertEqual(state, cur.fetchone()[0])

    def test_reject_latest_then_all_then_reinstate(self):
        latest = self.append()
        self.assertEqual(latest, self.current()['observation_id'])
        self.decide(latest, 'rejected')
        row = self.current()
        self.assertEqual(self.first, row['observation_id'])
        self.assertEqual(self.time, row['observed_at'])
        self.assertEqual(Decimal('2.25'), row['decimal_odds'])
        self.decide(self.first, 'rejected')
        self.assertIsNone(self.current())
        decision = self.decide(latest, 'reinstated', minute=21)
        row = self.current()
        self.assertEqual(latest, row['observation_id'])
        self.assertEqual(decision['id'], row['latest_disposition_id'])
        self.assertEqual('reinstated', row['latest_disposition_code'])
        self.assertEqual(decision['created_at'], row['disposition_created_at'])

    def test_observation_timestamp_beats_persistence_order(self):
        latest = self.append(minute=2, state='unavailable', price=None)
        self.append(minute=1)
        self.assertEqual(latest, self.current()['observation_id'])

    def test_decision_timestamp_beats_persistence_order(self):
        self.decide(self.first, 'reinstated', minute=21)
        self.decide(self.first, 'rejected', minute=5)
        self.assertEqual(self.first, self.current()['observation_id'])

    def test_observation_uuid_breaks_equal_time_tie(self):
        high = 'ffffffff-ffff-7fff-bfff-ffffffffffff'
        self.append(identifier=high)
        self.append(identifier='00000000-0000-7000-8000-000000000001')
        self.assertEqual(high, self.current()['observation_id'])

    def test_decision_uuid_breaks_equal_time_tie(self):
        with self.conn.cursor() as cur:
            for identifier, code in [
                ('ffffffff-ffff-7fff-bfff-ffffffffffff', 'reinstated'),
                ('00000000-0000-7000-8000-000000000001', 'rejected'),
            ]:
                cur.execute('''INSERT INTO corner.observation_dispositions
                    (id, observation_id, disposition_type_id, decision_key, reason,
                     decided_at, authority_kind, authority_id)
                    VALUES (%s, %s, (SELECT id FROM corner.disposition_types WHERE code = %s),
                            %s, 'Synthetic tie', %s, 'service', 'tie-test')''',
                            (identifier, self.first, code, str(uuid4()), self.time))
        self.assertEqual('reinstated', self.current()['latest_disposition_code'])

    def test_projection_is_normal_non_updatable_view(self):
        with self.conn.cursor() as cur:
            cur.execute("SELECT is_updatable FROM information_schema.views "
                        "WHERE table_schema = 'corner' AND table_name = 'trusted_current_quotes'")
            self.assertEqual(('NO',), cur.fetchone())
