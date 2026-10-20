from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from contextlib import nullcontext, redirect_stdout
import io

from corner.collection_policy import Job, STANDARD, TOTAL
from corner.collection_quota import LiveGovernor
from corner.credit_governor import Refused
from pipelines.collection_setup import initialize
from pipelines.collection_smoke import prepare, reserve, dispatch, publish_replay
from pipelines import collection_smoke as smoke
from tests.test_collection_setup import NOW, KEY, quota


class Smoke(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name)/'collection-live.sqlite3'
        initialize(self.path, KEY, quota(), NOW, 'a'*40)
        self.g = LiveGovernor(self.path)
        self.g.acquire('owner', NOW)
        prepare(self.g)
        self.job = Job('main', 'icehockey_nhl', 'standard', STANDARD, ('h2h','spreads','totals'))

    def tearDown(self):
        self.g.close()
        self.directory.cleanup()

    def reserve(self, **changes):
        values = dict(g=self.g, owner='owner', now=NOW, key=KEY, job=self.job, quota=quota())
        values.update(changes)
        return reserve(**values)

    def test_pause_is_never_cleared_and_purchase_limit_is_durable(self):
        token = self.reserve()
        self.assertTrue(self.g.db.execute('SELECT paused FROM controls').fetchone()[0])
        with self.assertRaises(Refused):
            self.g.authorize('owner', NOW, 'a'*64)
        with self.assertRaises(Refused):
            self.reserve()
        self.assertEqual(self.g.db.execute('SELECT reserved FROM attempts WHERE token=?',(token,)).fetchone()[0], 3)
        self.g.close()
        self.g = LiveGovernor(self.path)
        with self.assertRaises(Refused):
            self.reserve()

    def test_nonzero_stale_or_changed_key_refused_without_reservation(self):
        for changes in ({'quota': {**quota(),'provider_used':1,'provider_remaining':TOTAL-1}},
                        {'quota':{**quota(),'checked_at_utc':(NOW-timedelta(minutes=1)).isoformat()}},
                        {'key':'different-credential'}):
            with self.assertRaises(Refused):
                self.reserve(**changes)
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM attempts').fetchone()[0], 0)

    def test_outside_hours_and_exchange_cannot_use_smoke_permit(self):
        with self.assertRaises(Refused):
            self.reserve(now=NOW.replace(hour=4))
        from corner.collection_policy import EXCHANGE
        with self.assertRaises(Refused):
            self.reserve(job=Job('main','icehockey_nhl','exchange',EXCHANGE,('h2h','spreads','totals')))

    def test_dispatch_once_and_fixed_three_market_request(self):
        token = self.reserve()
        provider = Mock()
        provider._get.return_value = (200, [], {})
        dispatch(self.g,provider,'owner',self.job,token,NOW)
        with self.assertRaises(Refused):
            dispatch(self.g,provider,'owner',self.job,token,NOW)
        provider._get.assert_called_once()
        path, params = provider._get.call_args.args
        self.assertEqual(path, '/icehockey_nhl/odds')
        self.assertEqual(params['markets'], 'h2h,spreads,totals')
        self.assertNotIn('regions', params)

    def test_expired_permit_never_dispatches(self):
        token = self.reserve()
        provider = Mock()
        with self.assertRaises(Refused):
            dispatch(self.g,provider,'owner',self.job,token,NOW+timedelta(seconds=5))
        provider._get.assert_not_called()

    def test_network_failure_burns_dispatch_permit(self):
        token = self.reserve()
        provider = Mock()
        provider._get.side_effect = RuntimeError('synthetic timeout')
        with self.assertRaises(RuntimeError):
            dispatch(self.g,provider,'owner',self.job,token,NOW)
        with self.assertRaises(Refused):
            dispatch(self.g,provider,'owner',self.job,token,NOW)
        self.g.unknown(token,'owner',NOW)
        self.assertEqual(self.g.db.execute('SELECT state FROM attempts').fetchone()[0], 'unknown')
        with self.assertRaises(Refused):
            self.reserve()

    def test_settlement_accounts_charge_and_keeps_pause(self):
        token = self.reserve()
        result = self.g.finish(self.job,token,'owner',NOW,
                               {'x-requests-last':'3','x-requests-used':'3','x-requests-remaining':str(TOTAL-3)}, [])
        self.assertEqual(result, 'published')
        self.assertEqual(self.g._binding(self.g.db,NOW)['used'], 3)
        self.assertTrue(self.g.db.execute('SELECT paused FROM controls').fetchone()[0])
        with self.assertRaises(Refused):
            self.reserve()

    def test_overspend_never_publishes(self):
        token = self.reserve()
        result = self.g.finish(self.job,token,'owner',NOW,
                               {'x-requests-last':'4','x-requests-used':'4','x-requests-remaining':str(TOTAL-4)}, [])
        self.assertEqual(result,'paused')
        self.assertIsNone(self.g.db.execute('SELECT 1 FROM publication_outbox').fetchone())

    def test_pending_publication_failure_stays_pending(self):
        token = self.reserve()
        self.g.finish(self.job,token,'owner',NOW,
                      {'x-requests-last':'3','x-requests-used':'3','x-requests-remaining':str(TOTAL-3)}, [])
        publisher = Mock(side_effect=RuntimeError('synthetic DB failure'))
        with self.assertRaises(RuntimeError):
            publish_replay(self.g,publisher,Mock(),NOW)
        self.assertIsNone(self.g.db.execute('SELECT published_at FROM publication_outbox').fetchone()[0])
        with self.assertRaises(Refused):
            self.reserve()

    def run_cli(self, execute, provider=None):
        self.g.release('owner')
        arguments = ['smoke'] + (['--execute-three-credit-smoke'] if execute else [])
        with patch.object(smoke,'preflight',return_value={'ODDS_API_KEY':KEY}), \
             patch.object(smoke,'STATE',self.path), \
             patch.object(smoke,'clock',return_value=NOW), \
             patch.object(smoke,'maintenance_lock',return_value=nullcontext()), \
             patch.object(smoke,'writer'), \
             patch.object(smoke,'reader_check',return_value={'fresh_quotes_visible':True}), \
             patch.object(smoke.onboarding,'verify_key',return_value=quota()) as inventory, \
             patch.object(smoke,'Provider',return_value=provider) as factory, \
             patch.object(smoke,'publish_replay',return_value=1), \
             patch.object(smoke,'write_private'), \
             patch('sys.argv',arguments), redirect_stdout(io.StringIO()):
            # Keep the actual free-response validator rather than a permissive mock.
            from pipelines.collection_provider import Provider
            factory._free_response = Provider._free_response
            result = smoke.main()
            return result, inventory.call_count, factory.call_count

    def test_check_cli_never_constructs_provider_or_purchases(self):
        self.assertEqual(self.run_cli(False), (0,0,0))
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM attempts').fetchone()[0],0)

    def test_execute_then_restart_cannot_buy_twice(self):
        provider = Mock()
        free = {'x-requests-last':'0','x-requests-used':'0','x-requests-remaining':str(TOTAL)}
        paid = {'x-requests-last':'3','x-requests-used':'3','x-requests-remaining':str(TOTAL-3)}
        provider._get.side_effect = [(200,[{'sport_key':'icehockey_nhl','commence_time':(NOW+timedelta(hours=1)).isoformat()}],free),
                                    (200,[],paid)]
        self.assertEqual(self.run_cli(True,provider),(0,1,1))
        self.assertEqual(provider._get.call_count,2)
        self.assertEqual(self.run_cli(True,Mock()),(0,0,0))
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM attempts').fetchone()[0],1)


if __name__ == '__main__':
    unittest.main()
