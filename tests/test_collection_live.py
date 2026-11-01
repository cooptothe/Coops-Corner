from datetime import timedelta
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

from corner.collection_policy import parse, plan, TOTAL, PROTECTED, POOLS
from corner.collection_quota import LiveGovernor, key_identity, quota_headers
from corner.credit_governor import Refused
from pipelines.collection_live import LiveProvider
from pipelines.collection_runner import Runner
from tests.test_collection_adapters import Session, Response

NOW = parse('2026-10-19T15:00:00Z')
ZERO = {'main': 0, 'props': 0, 'metadata': 0, 'history': 0}

def headers(used, actual=0):
    return {'x-requests-used': str(used), 'x-requests-remaining': str(TOTAL-used), 'x-requests-last': str(actual)}

class LiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.g = LiveGovernor(Path(self.tmp.name) / 'collection-live.sqlite3')
        self.g.configure_cycle('funded-cycle', NOW-timedelta(days=1), NOW+timedelta(days=29))
        self.identity = key_identity('test-key-never-log')
        self.now = NOW
        self.job = plan(NOW, ['basketball_nba'], [])[0]

    def tearDown(self):
        self.g.close()
        self.tmp.cleanup()

    def bind(self, used=0, offsets=None):
        self.g.bind('funded-cycle', self.identity, used, TOTAL-used, offsets or ZERO, self.now, 'verified fixture')

    def acquire(self):
        self.assertTrue(self.g.acquire('worker', self.now))

    def claim(self):
        self.g.prepare_due(self.job, 'worker', self.now)
        return self.g.claim(self.job, 'worker', self.now)

    def test_default_activation_refuses_before_network(self):
        from corner.collection_activation import activation
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(Refused):
                activation(NOW)

    def test_header_missing_wrong_total_boolean_and_negative_rejected(self):
        for value in ({}, {**headers(0), 'x-requests-used': True},
                      {**headers(0), 'x-requests-used': '-1'},
                      {**headers(0), 'x-requests-remaining': '1'}):
            with self.assertRaises(Refused):
                quota_headers(value)

    def test_preexisting_usage_debits_pool_before_claim(self):
        self.bind(POOLS['main']-1, {'main': POOLS['main']-1, 'props': 0, 'metadata': 0, 'history': 0})
        self.acquire()
        with self.assertRaisesRegex(Refused, 'Pool limit'):
            self.claim()
        self.assertEqual(self.g.status()['cycles'][0]['remaining_pools']['main'], 1)

    def test_binding_requires_complete_allocations_and_cannot_reset(self):
        with self.assertRaises(Refused):
            self.bind(100, ZERO)
        self.bind()
        with self.assertRaises(Refused):
            self.bind()

    def test_key_change_and_unbound_cycle_refused(self):
        self.acquire()
        with self.assertRaises(Refused):
            self.g.authorize('worker', NOW, self.identity)
        self.g.release('worker')
        self.bind()
        self.acquire()
        with self.assertRaises(Refused):
            self.g.authorize('worker', NOW, key_identity('another-key'))

    def test_stale_confirmation_blocks_odds_but_free_inventory_can_confirm(self):
        self.bind()
        self.now += timedelta(seconds=301)
        self.acquire()
        with self.assertRaises(Refused):
            self.g.authorize('worker', self.now, self.identity)
        token = self.g.authorize('worker', self.now, self.identity, inventory=True)
        self.g.inventory_finish(token, 'worker', self.now, headers(0), 200)
        self.g.authorize('worker', self.now, self.identity)

    def test_successful_charge_reconciles_exact_used_and_remaining(self):
        self.bind(10, {'main': 10, 'props': 0, 'metadata': 0, 'history': 0})
        self.acquire()
        token = self.claim()
        self.assertEqual(self.g.finish(self.job, token, 'worker', NOW, headers(13, 3), []), 'published')
        self.assertEqual(self.g.status()['cycles'][0]['accounted']['main'], 13)
        self.assertEqual(self.g.db.execute('SELECT used FROM quota_bindings').fetchone()[0], 13)

    def test_quota_drift_pauses_without_publication(self):
        self.bind()
        self.acquire()
        token = self.claim()
        self.assertEqual(self.g.finish(self.job, token, 'worker', NOW, headers(8, 3), []), 'paused')
        self.assertIn('drift', self.g.status()['paused'])
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM publication_outbox').fetchone()[0], 0)
        self.assertEqual(self.g.status()['cycles'][0]['accounted']['main'], 3)

    def test_missing_used_header_never_publishes(self):
        self.bind()
        self.acquire()
        token = self.claim()
        self.assertEqual(self.g.finish(self.job, token, 'worker', NOW,
                         {'x-requests-last': '3', 'x-requests-remaining': '14999997'}, []), 'paused')
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM publication_outbox').fetchone()[0], 0)

    def test_inventory_nonzero_charge_debits_metadata_and_pauses(self):
        self.bind()
        self.acquire()
        token = self.g.authorize('worker', NOW, self.identity, inventory=True)
        with self.assertRaises(Refused):
            self.g.inventory_finish(token, 'worker', NOW, headers(2, 2), 200)
        self.assertEqual(self.g.status()['cycles'][0]['accounted']['metadata'], 2)
        self.assertTrue(self.g.status()['paused'])

    def test_inventory_timeout_and_crash_hold_reservation(self):
        self.bind()
        self.acquire()
        token = self.g.authorize('worker', NOW, self.identity, inventory=True)
        later = NOW + timedelta(seconds=121)
        self.assertTrue(self.g.acquire('replacement', later))
        self.assertEqual(self.g.db.execute('SELECT state FROM quota_inventory').fetchone()[0], 'unknown')
        self.assertEqual(self.g.status()['cycles'][0]['accounted']['metadata'], 1)
        with self.assertRaises(Refused):
            self.g.inventory_finish(token, 'worker', later, headers(0), 200)

    def test_resume_requires_reconciliation_not_just_fresh_binding(self):
        self.bind()
        with self.assertRaises(Refused):
            self.g.resume(NOW, 'operator acceptance')

    def test_operator_reconciles_unknown_with_audit_then_resumes(self):
        self.bind()
        self.acquire()
        token = self.claim()
        self.g.unknown(token, 'worker', NOW)
        self.g.release('worker')
        self.g.reconcile(NOW, 2, TOTAL-2, ZERO, {token: 2}, {}, 'verified provider receipt fixture')
        self.assertTrue(self.g.status()['paused'])
        self.g.resume(NOW, 'reviewed recovery fixture')
        self.assertFalse(self.g.status()['paused'])
        self.assertEqual(self.g.status()['unknown_attempts'], 0)
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM quota_audit').fetchone()[0], 3)
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM publication_outbox').fetchone()[0], 0)

    def test_reconciliation_mismatch_rolls_back_and_preserves_unknown(self):
        self.bind()
        self.acquire()
        token = self.claim()
        self.g.unknown(token, 'worker', NOW)
        self.g.release('worker')
        with self.assertRaises(Refused):
            self.g.reconcile(NOW, 9, TOTAL-9, ZERO, {token: 2}, {}, 'fixture')
        self.assertEqual(self.g.status()['unknown_attempts'], 1)
        self.assertEqual(self.g.status()['cycles'][0]['accounted']['main'], 3)

    def test_reconciliation_refuses_live_lease_and_decreasing_baseline(self):
        self.bind(10, {'main': 10, 'props': 0, 'metadata': 0, 'history': 0})
        self.acquire()
        with self.assertRaises(Refused):
            self.g.reconcile(NOW, 10, TOTAL-10, {'main': 10, 'props': 0, 'metadata': 0, 'history': 0}, {}, {}, 'fixture')
        self.g.release('worker')
        with self.assertRaises(Refused):
            self.g.reconcile(NOW, 10, TOTAL-10, ZERO, {}, {}, 'fixture')

    def test_external_usage_allocation_is_explicit_and_audited(self):
        self.bind()
        self.g.reconcile(NOW, 50, TOTAL-50, {'main': 50, 'props': 0, 'metadata': 0, 'history': 0}, {}, {}, 'external consumer receipt')
        self.assertEqual(self.g.status()['cycles'][0]['accounted']['main'], 50)

    def test_protected_reserve_prevents_binding(self):
        with self.assertRaises(Refused):
            self.bind(TOTAL-PROTECTED, {'main': 7900000, 'props': 5000000, 'metadata': 500000, 'history':100000})

    def test_fake_live_pipeline_discovery_odds_and_replay_cadence(self):
        self.bind()
        responses = [Response([{'key': 'basketball_nba', 'active': True}], charge='0'),
                     Response([], charge='0'), Response([], charge='3'), Response([], charge='3')]
        for response, used in zip(responses, (0, 0, 3, 6)):
            response.headers = {k.title(): v for k, v in headers(used, 0 if used == 0 else 3).items()}
        session = Session(responses)
        runner = Runner(self.g, None, None, owner='worker', clock=lambda: self.now)
        provider = LiveProvider(self.g, 'worker', key='test-key-never-log', enabled=True,
                                exchange_verified=True, session=session, clock=lambda: self.now)
        runner.discover, runner.transport = provider.discover, provider.odds
        with patch('pipelines.collection_live.activation', return_value={}):
            self.assertEqual(runner.tick()['executed'], 2)
            self.assertEqual(runner.tick()['executed'], 0)
        self.assertEqual(len(session.calls), 4)
        self.assertEqual(self.g.db.execute('SELECT used FROM quota_bindings').fetchone()[0], 6)
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM publication_outbox').fetchone()[0], 2)

    def test_shutdown_intent_refuses_network(self):
        self.bind()
        session = Session([])
        provider = LiveProvider(self.g, 'worker', key='test-key-never-log', enabled=True,
                                exchange_verified=True, session=session, clock=lambda: NOW,
                                should_stop=lambda: True)
        with self.assertRaises(Refused):
            provider.discover()
        self.assertEqual(session.calls, [])

    def test_runner_shutdown_does_not_create_reservations(self):
        runner = Runner(self.g, lambda: self.fail('No discovery during shutdown'), None,
                        clock=lambda: NOW, should_stop=lambda: True)
        self.assertEqual(runner.tick()['state'], 'stopping')
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM attempts').fetchone()[0], 0)

    def test_inventory_unknown_settlement_and_external_offsets_reconcile(self):
        self.bind()
        self.acquire()
        token = self.g.authorize('worker', NOW, self.identity, inventory=True)
        self.g.inventory_unknown(token, 'worker', NOW)
        self.g.release('worker')
        self.g.reconcile(NOW, 7, TOTAL-7, {'main': 5, 'props': 0, 'metadata': 0, 'history': 0}, {}, {token: 2}, 'verified inventory and external usage')
        self.g.resume(NOW, 'reviewed exception')
        self.assertEqual(self.g.status()['cycles'][0]['accounted'], {'main': 5, 'props': 0, 'metadata': 2, 'history':0})

    def test_cycle_reset_never_reuses_old_binding(self):
        self.bind()
        future = NOW + timedelta(days=30)
        self.g.configure_cycle('next-cycle', NOW+timedelta(days=29), NOW+timedelta(days=59))
        self.assertTrue(self.g.acquire('worker', future))
        with self.assertRaises(Refused):
            self.g.authorize('worker', future, self.identity, inventory=True)


class ActivationTests(unittest.TestCase):
    def setUp(self):
        from corner import collection_activation as module
        self.module = module
        self.env = {'CORNER_COLLECTION_ENABLED': '1', 'CORNER_PRIVATE_BETA': '1',
                    'CORNER_COLLECTION_DB': str(module.STATE),
                    'CORNER_COLLECTION_RETAINED': str(module.RETAINED),
                    'CORNER_COLLECTION_DB_HOST': '127.0.0.1', 'CORNER_COLLECTION_DB_PORT': '5432',
                    'CORNER_COLLECTION_DB_NAME': 'corner_staging',
                    'CORNER_COLLECTION_DB_USER': 'corner_collection_writer',
                    'ODDS_API_KEY': 'fake-secret', 'CORNER_COLLECTION_DB_PASSWORD': 'fake-password'}
        self.approval = {'approved': True, 'release_commit': 'a'*40, 'cycle_id': 'test-cycle',
                         'cycle_start': (NOW-timedelta(days=1)).isoformat(),
                         'cycle_end': (NOW+timedelta(days=29)).isoformat(),
                         'quota_checked_at': NOW.isoformat(), 'provider_used': 0, 'provider_remaining': TOTAL,
                         'evidence': {k: 'offline test reference' for k in module.EVIDENCE}}

    def check(self, *, mode=0o100644, uid=0, commit='a'*40, now=NOW):
        file = MagicMock()
        file.lstat.return_value = SimpleNamespace(st_mode=mode, st_uid=uid)
        file.parent.stat.return_value = SimpleNamespace(st_mode=0o40755, st_uid=0)
        file.read_text.return_value = json.dumps(self.approval)
        with patch.dict(os.environ, self.env, clear=True), patch.object(self.module, 'APPROVAL', file), \
             patch.object(self.module.subprocess, 'check_output', return_value=commit):
            return self.module.activation(now, startup=True)

    def test_complete_root_owned_commit_specific_approval_accepts(self):
        self.assertEqual(self.check()['cycle_id'], 'test-cycle')

    def test_unapproved_incomplete_stale_and_wrong_release_refused(self):
        self.approval['approved'] = False
        with self.assertRaises(Refused): self.check()
        self.approval['approved'] = True
        self.approval['evidence']['offserver_backup_restore_tested'] = ''
        with self.assertRaises(Refused): self.check()
        self.approval['evidence']['offserver_backup_restore_tested'] = 'restore fixture'
        with self.assertRaises(Refused): self.check(commit='b'*40)
        with self.assertRaises(Refused): self.check(now=NOW+timedelta(seconds=301))

    def test_writable_nonroot_and_symlink_approvals_refused(self):
        for mode, uid in ((0o100666, 0), (0o100644, 1000), (0o120777, 0)):
            with self.assertRaises(Refused): self.check(mode=mode, uid=uid)

    def test_wrong_writer_and_before_funding_date_refused(self):
        self.env['CORNER_COLLECTION_DB_USER'] = 'postgres'
        with self.assertRaises(Refused): self.check()
        self.env['CORNER_COLLECTION_DB_USER'] = 'corner_collection_writer'
        with self.assertRaises(Refused): self.check(now=NOW-timedelta(days=1))


class WriterTests(unittest.TestCase):
    def test_writer_uses_dedicated_configuration_and_rejects_elevation(self):
        from pipelines.collection_live import writer
        env = {'CORNER_COLLECTION_DB_HOST': '127.0.0.1', 'CORNER_COLLECTION_DB_PORT': '5432',
               'CORNER_COLLECTION_DB_NAME': 'corner_staging', 'CORNER_COLLECTION_DB_USER': 'corner_collection_writer',
               'CORNER_COLLECTION_DB_PASSWORD': 'test-only-secret'}
        for elevated in (False, True):
            conn = MagicMock()
            cur = conn.cursor.return_value.__enter__.return_value
            cur.fetchone.side_effect = [('corner_staging', 'corner_collection_writer'),
                                        (elevated, False, False, False, False), (False, False, False), (1,)]
            with patch.dict(os.environ, env, clear=True), patch('pipelines.collection_live.psycopg2.connect', return_value=conn) as connect:
                if elevated:
                    with self.assertRaises(Refused): writer()
                    conn.close.assert_called_once()
                else:
                    self.assertIs(writer(), conn)
                    self.assertEqual(connect.call_args.kwargs['user'], 'corner_collection_writer')

    def test_missing_writer_configuration_has_no_owner_fallback(self):
        from pipelines.collection_live import writer
        with patch.dict(os.environ, {}, clear=True), patch('pipelines.collection_live.psycopg2.connect') as connect:
            with self.assertRaises(KeyError): writer()
            connect.assert_not_called()

if __name__ == '__main__':
    unittest.main()
