"""Fresh 002-010 schema, real assessment races, and rollback-only contract tests."""

import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import test_corner_assessments as helpers
import test_corner_channel_concurrency as databases
from corner import assessments as a


class AssessmentDatabase:
    connect = classmethod(databases.ChannelConcurrencyTests.connect.__func__)
    drop_database = classmethod(databases.ChannelConcurrencyTests.drop_database.__func__)

    @classmethod
    def setUpClass(cls):
        databases.ChannelConcurrencyTests.setUpClass.__func__(cls)
        conn = cls.connect()
        try:
            with conn.cursor() as cur:
                cur.execute((Path(__file__).resolve().parents[1] / 'db/migrations/010_corner_actionability_assessments.sql').read_text())
        finally:
            conn.close()


@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE') == '1' and os.getenv('CORNER_TEST_CONCURRENCY') == '1',
                     'opt-in disposable assessment database')
class AssessmentConcurrencyTests(AssessmentDatabase, unittest.TestCase):
    select = helpers.AssessmentLedgerTests.select
    evaluate = helpers.AssessmentLedgerTests.evaluate
    qualify = helpers.AssessmentLedgerTests.qualify
    register = helpers.AssessmentLedgerTests.register
    capture = helpers.AssessmentLedgerTests.capture
    command = helpers.AssessmentLedgerTests.command
    record = helpers.AssessmentLedgerTests.record

    def setUp(self):
        with patch('db.insert.connect', side_effect=self.connect):
            helpers.AssessmentLedgerTests.setUp(self)
        self.captured_command = self.command()
        self.conn.commit()

    def race(self, *, changed_command=False, divergent_result=False):
        barrier = threading.Barrier(2)
        committed = threading.Event()
        context = threading.local()
        original = a._compute

        def compute(cur, document):
            output = original(cur, document)
            barrier.wait(timeout=15)
            if divergent_result and context.number == 1:
                if not committed.wait(timeout=15):
                    raise AssertionError('original writer did not commit')
                output = output | {'actionable': False, 'primary_reason': 'unsupported_phase', 'reasons': ['unsupported_phase']}
            return output

        def worker(number):
            context.number = number
            conn = self.connect()
            try:
                with conn.cursor() as cur:
                    cur.execute("SET LOCAL statement_timeout='20s'")
                command = self.captured_command
                if changed_command and number == 1:
                    command = replace(command, context_json='{"changed":true}')
                result = self.record(command, conn=conn)
                conn.commit()
                committed.set()
                return result
            except (a.AssessmentConflict, a.AssessmentDeterminismFailure) as error:
                conn.rollback()
                return error
            finally:
                conn.close()

        with patch('corner.assessments._compute', side_effect=compute):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(worker, (0, 1)))
        with self.conn.cursor() as cur:
            cur.execute('''SELECT a.id, a.actionable, count(s.id) FROM corner.actionability_assessments a
                JOIN corner.assessment_stream_evidence s ON s.assessment_id=a.id
                WHERE authority_id=%s GROUP BY a.id''', (self.authority.identifier,))
            stored = cur.fetchall()
        self.assertEqual(1, len(stored))
        self.assertEqual(5, stored[0][2])
        return results, stored[0]

    def test_identical_commands_have_one_header_and_complete_streams(self):
        results, stored = self.race()
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0]['id'], stored[0])

    def test_changed_command_conflicts_without_partial_evidence(self):
        results, _ = self.race(changed_command=True)
        self.assertEqual(1, sum(isinstance(r, a.AssessmentConflict) for r in results))

    def test_divergent_results_preserve_original_and_surface_determinism_error(self):
        results, stored = self.race(divergent_result=True)
        self.assertIsInstance(results[1], a.AssessmentDeterminismFailure)
        self.assertTrue(stored[1])
        self.assertEqual(results[0]['id'], stored[0])


@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE') == '1' and os.getenv('CORNER_TEST_CONCURRENCY') == '1',
                     'opt-in disposable assessment database')
class DisposableAssessmentLedgerTests(AssessmentDatabase, helpers.AssessmentLedgerTests):
    def setUp(self):
        with patch('db.insert.connect', side_effect=self.connect):
            super().setUp()
