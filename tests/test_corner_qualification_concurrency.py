"""Real committed two-connection races, isolated in a disposable database.

Requires CORNER_TEST_DATABASE=1 and CORNER_TEST_CONCURRENCY=1 and CREATEDB.
Never commits test evidence to the configured application database.
"""

import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import test_corner_ev_selection as fixtures
from corner import qualifications
from corner.evaluations import EvaluationAuthority, EvaluationCommand, record_evaluation


@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE') == '1'
                     and os.getenv('CORNER_TEST_CONCURRENCY') == '1',
                     'opt-in disposable-database concurrency tests')
class QualificationConcurrencyTests(unittest.TestCase):
    select = fixtures.EVSelectionTests.select

    @classmethod
    def setUpClass(cls):
        import psycopg2
        from psycopg2 import sql
        from config import DB_CONFIG
        cls.database_name = 'corner_qualification_test_' + uuid4().hex
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
            for migration in sorted(directory.glob('00[2-8]_*.sql')):
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
        # Drop only the exact database created above, never the configured DB.
        if not cls.database_name.startswith('corner_qualification_test_'):
            raise AssertionError('unexpected scratch database name')
        admin = psycopg2.connect(**DB_CONFIG)
        admin.autocommit = True
        try:
            with admin.cursor() as cur:
                cur.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.database_name)))
        finally:
            admin.close()

    def setUp(self):
        with patch('db.insert.connect', side_effect=self.connect):
            fixtures.EVSelectionTests.setUp(self)
        selected = self.select()
        evaluation = record_evaluation(self.conn,
            authority=EvaluationAuthority('service', 'concurrency-test'),
            evaluation_key=str(uuid4()), command=EvaluationCommand(selected.snapshot, selected.configuration))
        self.command = qualifications.QualificationCommand(evaluation['id'],
            qualifications.MinimumEVPolicy('test-v1', Decimal('.01')), self.time + timedelta(minutes=1))
        self.conn.commit()  # Only the disposable database receives committed test rows.

    def race(self, divergent=False):
        barrier = threading.Barrier(2)
        winner_committed = threading.Event()
        worker_context = threading.local()
        original = qualifications.qualify_evaluation

        def compute(evaluation, policy):
            result = original(evaluation, policy)
            barrier.wait(timeout=15)  # Both callers passed the absent-command lookup.
            if divergent and worker_context.number == 1:
                if not winner_committed.wait(timeout=15):
                    raise AssertionError('original writer did not commit')
                return replace(result, decision_kind='not_qualified', reason_code='below_minimum_ev')
            return result

        def worker(number):
            worker_context.number = number
            conn = self.connect()
            try:
                row = qualifications.record_qualification(conn,
                    authority=qualifications.QualificationAuthority('service', 'concurrency-test'),
                    qualification_key=self.command.engine_evaluation_id, command=self.command)
                conn.commit()
                winner_committed.set()
                return row
            except qualifications.QualificationDeterminismFailure as error:
                conn.rollback()
                return error
            finally:
                conn.close()

        with patch('corner.qualifications.qualify_evaluation', side_effect=compute):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(worker, (0, 1)))
        with self.conn.cursor() as cur:
            cur.execute('SELECT id, decision_kind FROM corner.qualification_decisions WHERE engine_evaluation_id=%s',
                        (self.command.engine_evaluation_id,))
            rows = cur.fetchall()
        self.assertEqual(1, len(rows))
        return results, rows[0]

    def test_concurrent_identical_commands_return_one_original_row(self):
        results, stored = self.race()
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0]['id'], stored[0])

    def test_concurrent_divergent_results_preserve_original_and_surface_failure(self):
        results, stored = self.race(divergent=True)
        self.assertIsInstance(results[1], qualifications.QualificationDeterminismFailure)
        self.assertEqual((results[0]['id'], 'qualified'), stored)
