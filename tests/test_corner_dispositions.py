"""Rollback-only integration tests; opt in with CORNER_TEST_DATABASE=1."""

import json
import os
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from corner.dispositions import (
    DecisionAuthority, DispositionCommand, IdempotencyConflict, record_disposition,
)
from test_corner_quote_states import event_fixture


@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE') == '1', 'opt-in PostgreSQL tests')
class DispositionTests(unittest.TestCase):
    def setUp(self):
        from db.insert import connect
        from corner.ingestion import _seed_provider, _create_batch, _create_payload, process_payload
        self.conn = connect()
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        provider = _seed_provider(self.conn)
        batch = _create_batch(self.conn, provider, {'source': 'disposition-test'})
        self.time = datetime(2026, 9, 21, 10, 5, tzinfo=timezone.utc)
        event = event_fixture()
        payload = _create_payload(self.conn, batch, provider, self.time, json.dumps(event).encode())
        process_payload(self.conn, payload, event)
        with self.conn.cursor() as cur:
            cur.execute('SELECT id FROM corner.odds_observations WHERE provider_payload_id = %s', (payload,))
            self.observation = cur.fetchone()[0]
        self.authority = DecisionAuthority('service', 'normalization-review')
        self.command = DispositionCommand('command-1', self.observation, 'rejected',
                                          'Investigating normalization', self.time,
                                          {'rule': 'v2', 'ticket': 'INC-42'})

    def record(self, command=None, authority=None):
        return record_disposition(self.conn, authority=authority or self.authority,
                                  command=command or self.command)

    def assert_sql_error(self, sql, params, code):
        import psycopg2
        with self.conn.cursor() as cur:
            cur.execute('SAVEPOINT expected_error')
            try:
                with self.assertRaises(psycopg2.Error) as caught:
                    cur.execute(sql, params)
                self.assertEqual(code, caught.exception.pgcode)
            finally:
                cur.execute('ROLLBACK TO SAVEPOINT expected_error')
                cur.execute('RELEASE SAVEPOINT expected_error')

    def test_retry_returns_original_id_and_timestamps_with_jsonb_equality(self):
        first = self.record()
        retry = self.record(replace(self.command, authority_metadata={'ticket': 'INC-42', 'rule': 'v2'}))
        self.assertEqual(first, retry)
        with self.conn.cursor() as cur:
            cur.execute('SELECT count(*), max(uuid_extract_version(id)) '
                        'FROM corner.observation_dispositions WHERE observation_id = %s', (self.observation,))
            self.assertEqual((1, 7), cur.fetchone())

    def test_every_changed_command_field_conflicts(self):
        self.record()
        changes = [dict(reason='Different'), dict(disposition='reinstated'),
                   dict(decided_at=self.time + timedelta(seconds=1)),
                   dict(authority_metadata={'rule': 'v3'}), dict(authority_metadata=None)]
        # A second genuine observation proves that observation_id does not scope the key.
        from corner.ingestion import _create_batch, _create_payload, _seed_provider, process_payload
        provider = _seed_provider(self.conn)
        batch = _create_batch(self.conn, provider, {})
        event = event_fixture()
        payload = _create_payload(self.conn, batch, provider, self.time, json.dumps(event).encode())
        process_payload(self.conn, payload, event)
        with self.conn.cursor() as cur:
            cur.execute('SELECT id FROM corner.odds_observations WHERE provider_payload_id = %s', (payload,))
            changes.append(dict(observation_id=cur.fetchone()[0]))
        for change in changes:
            with self.subTest(change=change), self.assertRaises(IdempotencyConflict):
                self.record(replace(self.command, **change))

    def test_authority_scopes_key_and_new_key_allows_same_judgment(self):
        rows = [self.record(), self.record(authority=DecisionAuthority('human', self.authority.identifier)),
                self.record(authority=DecisionAuthority('service', 'other-service')),
                self.record(replace(self.command, decision_key='command-2'))]
        self.assertEqual(4, len({row['id'] for row in rows}))

    def test_database_itself_rejects_duplicate_command_key(self):
        self.record()
        self.assert_sql_error('''INSERT INTO corner.observation_dispositions
            (observation_id, disposition_type_id, reason, decided_at, authority_kind, authority_id, decision_key)
            SELECT observation_id, disposition_type_id, reason, decided_at, authority_kind, authority_id, decision_key
            FROM corner.observation_dispositions WHERE observation_id = %s''', (self.observation,), '23505')

    def test_update_delete_and_truncate_are_blocked(self):
        row = self.record()
        for sql, params in [
            ('UPDATE corner.observation_dispositions SET reason = %s WHERE id = %s', ('changed', row['id'])),
            ('DELETE FROM corner.observation_dispositions WHERE id = %s', (row['id'],)),
            # Assessment evidence now references dispositions. Bypass only the
            # FK precheck to prove the ledger's own trigger rejects truncation.
            ('TRUNCATE corner.observation_dispositions CASCADE', ()),
        ]:
            self.assert_sql_error(sql, params, 'P0001')

    def test_observation_fk_restricts_delete_independently_of_ledger_trigger(self):
        self.record()
        with self.conn.cursor() as cur:
            # Transactional test-only disable to isolate FK enforcement; rollback restores it.
            cur.execute('ALTER TABLE corner.odds_observations DISABLE TRIGGER odds_observations_immutable')
        self.assert_sql_error('DELETE FROM corner.odds_observations WHERE id = %s',
                              (self.observation,), '23001')
        with self.conn.cursor() as cur:
            cur.execute('ALTER TABLE corner.odds_observations ENABLE TRIGGER odds_observations_immutable')

    def test_reinstatement_orders_by_decision_time_not_insert_order(self):
        rejected = self.record()
        reinstated = self.record(replace(self.command, decision_key='reinstate', disposition='reinstated',
                                         decided_at=self.time + timedelta(minutes=16)))
        older = self.record(replace(self.command, decision_key='late-arrival',
                                    decided_at=self.time + timedelta(minutes=1)))
        with self.conn.cursor() as cur:
            cur.execute('SELECT id FROM corner.observation_dispositions WHERE observation_id = %s '
                        'ORDER BY decided_at DESC, id DESC', (self.observation,))
            self.assertEqual([reinstated['id'], older['id'], rejected['id']], [r[0] for r in cur.fetchall()])

    def test_null_metadata_retry_and_timezone_validation(self):
        command = replace(self.command, authority_metadata=None)
        self.assertEqual(self.record(command), self.record(command))
        with self.assertRaises(ValueError):
            self.record(replace(command, decided_at=self.time.replace(tzinfo=None)))
