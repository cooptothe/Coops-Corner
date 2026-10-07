"""Committed Migration 009 races isolated from the application database."""

import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import test_corner_channels as helpers
from corner import channels


@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE') == '1'
                     and os.getenv('CORNER_TEST_CONCURRENCY') == '1',
                     'opt-in disposable-database concurrency tests')
class ChannelConcurrencyTests(unittest.TestCase):
    select = helpers.ChannelLedgerTests.select
    register = helpers.ChannelLedgerTests.register
    activation = helpers.ChannelLedgerTests.activation
    activate = helpers.ChannelLedgerTests.activate
    qualification = helpers.ChannelLedgerTests.qualification

    @classmethod
    def setUpClass(cls):
        import psycopg2
        from psycopg2 import sql
        from config import DB_CONFIG
        cls.database_name = 'corner_channels_test_' + uuid4().hex
        cls.connection_config = dict(DB_CONFIG)
        cls.connection_config.pop('database', None)
        cls.connection_config['dbname'] = cls.database_name
        admin = psycopg2.connect(**DB_CONFIG)
        admin.autocommit = True
        try:
            with admin.cursor() as cur:
                cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.database_name)))
        finally:
            admin.close()
        cls.addClassCleanup(cls.drop_database)
        conn = cls.connect()
        try:
            directory = Path(__file__).resolve().parents[1] / 'db' / 'migrations'
            for migration in sorted(directory.glob('00[2-9]_*.sql')):
                with conn.cursor() as cur:
                    cur.execute(migration.read_text(encoding='utf-8'))
        finally:
            conn.close()

    @classmethod
    def connect(cls):
        import psycopg2
        return psycopg2.connect(**cls.connection_config)

    @classmethod
    def drop_database(cls):
        import psycopg2
        from psycopg2 import sql
        from config import DB_CONFIG
        if not cls.database_name.startswith('corner_channels_test_'):
            raise AssertionError('unexpected disposable database name')
        admin = psycopg2.connect(**DB_CONFIG)
        admin.autocommit = True
        try:
            with admin.cursor() as cur:
                cur.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.database_name)))
        finally:
            admin.close()

    def setUp(self):
        with patch('db.insert.connect', side_effect=self.connect):
            helpers.ChannelLedgerTests.setUp(self)
        self.authority = channels.ChannelAuthority('service', 'race-' + uuid4().hex)
        self.conn.commit()

    def race(self, operations, sql_prefix):
        """Make both connections reach the actual SQL contention boundary."""
        barrier = threading.Barrier(2)

        class CursorProxy:
            def __init__(self, cur):
                self.cur = cur

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.cur.close()

            def __getattr__(self, name):
                return getattr(self.cur, name)

            def execute(self, sql, params=None):
                if sql.startswith(sql_prefix):
                    barrier.wait(timeout=15)
                return self.cur.execute(sql, params)

        class ConnectionProxy:
            def __init__(self, conn):
                self.conn = conn

            def cursor(self, *args, **kwargs):
                return CursorProxy(self.conn.cursor(*args, **kwargs))

        def worker(operation):
            conn = self.connect()
            try:
                with conn.cursor() as cur:
                    cur.execute("SET LOCAL statement_timeout='20s'")
                row = operation(ConnectionProxy(conn))
                conn.commit()
                return row
            except (channels.ChannelConflict, channels.ActivationConflict) as error:
                conn.rollback()
                return error
            finally:
                conn.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(worker, operations))

    def count(self, table, field, identity):
        with self.conn.cursor() as cur:
            cur.execute(f'SELECT count(*) FROM corner.{table} WHERE {field}=%s', (identity,))
            return cur.fetchone()[0]

    def test_concurrent_registration_returns_original_row(self):
        results = self.race((lambda conn: self.register(conn=conn),) * 2,
                           'INSERT INTO corner.qualification_channel_generations')
        self.assertEqual(results[0], results[1])
        self.assertEqual(1, self.count('qualification_channel_generations', 'channel_id', self.channel['id']))

    def test_concurrent_registration_changed_command_conflicts(self):
        changed = replace(self.command, configuration=replace(self.command.configuration,
            qualification_policy=replace(self.command.configuration.qualification_policy, minimum_ev_ratio=Decimal('.03'))))
        results = self.race((lambda conn: self.register(conn=conn),
                            lambda conn: self.register(command=changed, conn=conn)),
                           'INSERT INTO corner.qualification_channel_generations')
        self.assertEqual(1, sum(isinstance(row, channels.ChannelConflict) for row in results))
        self.assertEqual(1, self.count('qualification_channel_generations', 'channel_id', self.channel['id']))

    def test_concurrent_identical_activation_returns_original_row(self):
        generation = self.register()
        self.conn.commit()
        command = self.activation(generation)
        results = self.race((lambda conn: self.activate(command, conn=conn),) * 2,
                           'SELECT id FROM corner.qualification_channels')
        self.assertEqual(results[0], results[1])
        self.assertEqual(1, results[0]['activation_sequence'])
        self.assertEqual(1, self.count('channel_generation_activations', 'channel_id', self.channel['id']))
        successor = self.register('successor')
        self.activate(self.activation(successor, generation), 'later-activation')
        self.conn.commit()
        # Retrying the concurrent winner must bypass today's different predecessor.
        self.assertEqual(results[0], self.activate(command))

    def test_concurrent_genesis_competitors_have_one_winner(self):
        g1, g2 = self.register(), self.register('second')
        self.conn.commit()
        results = self.race((lambda conn: self.activate(self.activation(g1), 'a1', conn=conn),
                            lambda conn: self.activate(self.activation(g2), 'a2', conn=conn)),
                           'SELECT id FROM corner.qualification_channels')
        self.assertEqual(1, sum(isinstance(row, channels.ActivationConflict) for row in results))
        self.assertEqual(1, self.count('channel_generation_activations', 'channel_id', self.channel['id']))

    def test_concurrent_successor_competitors_have_one_winner(self):
        g1, g2, g3 = self.register(), self.register('second'), self.register('third')
        self.activate(self.activation(g1))
        self.conn.commit()
        results = self.race((lambda conn: self.activate(self.activation(g2, g1), 'a2', conn=conn),
                            lambda conn: self.activate(self.activation(g3, g1), 'a3', conn=conn)),
                           'SELECT id FROM corner.qualification_channels')
        self.assertEqual(1, sum(isinstance(row, channels.ActivationConflict) for row in results))
        winner = next(row for row in results if isinstance(row, dict))
        self.assertEqual(2, winner['activation_sequence'])
        self.assertEqual(2, self.count('channel_generation_activations', 'channel_id', self.channel['id']))

    def test_cross_channel_authority_key_race_cannot_change_command(self):
        other = channels.create_channel(self.conn, code='other-' + uuid4().hex, display_name='Other')
        g1 = self.register()
        g2 = self.register('other', replace(self.command, channel_id=other['id']))
        self.conn.commit()
        results = self.race((lambda conn: self.activate(self.activation(g1), conn=conn),
            lambda conn: self.activate(self.activation(g2, channel_id=other['id']), conn=conn)),
            'SELECT id FROM corner.qualification_channels')
        self.assertEqual(1, sum(isinstance(row, channels.ChannelConflict) for row in results))
        self.assertEqual(1, self.count('channel_generation_activations', 'authority_id', self.authority.identifier))

    def test_concurrent_occurrence_creation_returns_one_immutable_row(self):
        qualification = self.qualification()
        self.conn.commit()
        operation = lambda conn: channels.create_occurrence(conn, qualification_decision_id=qualification['id'])
        results = self.race((operation, operation), 'INSERT INTO corner.opportunity_occurrences')
        self.assertEqual(results[0], results[1])
        self.assertEqual(1, self.count('opportunity_occurrences', 'qualification_decision_id', qualification['id']))

    def test_outer_transaction_failure_rolls_back_all_three_ledgers(self):
        qualification = self.qualification()
        self.conn.commit()
        conn = self.connect()
        try:
            with self.assertRaisesRegex(RuntimeError, 'outer failure'):
                with conn:
                    generation = self.register(conn=conn)
                    self.activate(self.activation(generation), conn=conn)
                    channels.create_occurrence(conn, qualification_decision_id=qualification['id'])
                    raise RuntimeError('outer failure after all three writes')
        finally:
            conn.close()
        self.assertEqual(0, self.count('qualification_channel_generations', 'channel_id', self.channel['id']))
        self.assertEqual(0, self.count('channel_generation_activations', 'channel_id', self.channel['id']))
        self.assertEqual(0, self.count('opportunity_occurrences', 'qualification_decision_id', qualification['id']))


@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE') == '1'
                     and os.getenv('CORNER_TEST_CONCURRENCY') == '1',
                     'opt-in disposable-database constraint tests')
class DisposableChannelLedgerTests(helpers.ChannelLedgerTests):
    """Run the complete constraint matrix against a clean 002-009 database too."""
    setUpClass = classmethod(ChannelConcurrencyTests.setUpClass.__func__)
    connect = classmethod(ChannelConcurrencyTests.connect.__func__)
    drop_database = classmethod(ChannelConcurrencyTests.drop_database.__func__)

    def setUp(self):
        with patch('db.insert.connect', side_effect=self.connect):
            super().setUp()
