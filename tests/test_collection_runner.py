from datetime import timedelta
import tempfile
from pathlib import Path
import unittest

from corner.collection_policy import parse
from corner.credit_governor import Governor
from pipelines.collection_runner import Runner


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.g = Governor(Path(self.temp.name) / 'simulation.sqlite3')
        self.now = parse('2026-10-19T15:00:00Z')
        self.g.configure_cycle('simulation-october', parse('2026-10-01T00:00:00Z'),
                               parse('2026-11-01T00:00:00Z'))
        self.discoveries = 0
        self.calls = []

    def tearDown(self):
        self.g.close()
        self.temp.cleanup()

    def discover(self):
        self.discoveries += 1
        return {'active_sport_keys': ['basketball_nba'], 'events': [],
                'discovered_at': self.now.isoformat()}

    def transport(self, g, job, token, owner):
        self.calls.append(job.key)
        return 200, [], {'x-requests-last': str(job.cost),
                         'x-requests-remaining': '15000000'}, self.now

    def runner(self, **kwargs):
        return Runner(self.g, self.discover, self.transport,
                      clock=lambda: self.now, **kwargs)

    def test_persistent_inventory_and_cadence(self):
        r = self.runner()
        self.assertEqual(r.tick()['executed'], 2)
        self.assertEqual(self.discoveries, 1)
        self.g.release(r.owner)
        second = self.runner()
        self.assertEqual(second.tick()['executed'], 0)
        self.assertEqual(self.discoveries, 1)
        self.now += timedelta(seconds=120)
        self.assertEqual(second.tick()['executed'], 2)

    def test_round_robin_survives_restart(self):
        r = self.runner(max_jobs=1)
        r.tick()
        self.g.release(r.owner)
        self.runner(max_jobs=1).tick()
        self.assertEqual(len(set(self.calls)), 2)

    def test_other_owner_cannot_discover(self):
        self.g.acquire('other', self.now)
        self.assertEqual(self.runner().tick()['state'], 'another_worker')
        self.assertEqual(self.discoveries, 0)

    def test_after_hours_no_discovery(self):
        self.now = parse('2026-10-20T06:00:00Z')
        self.assertEqual(self.runner().tick()['state'], 'after_hours')
        self.assertEqual(self.discoveries, 0)

    def test_failed_discovery_backoff_and_recovery(self):
        r = self.runner()
        r.discover = lambda: (_ for _ in ()).throw(RuntimeError('secret must not escape'))
        self.assertEqual(r.tick()['state'], 'discovery_failed')
        self.assertEqual(r.tick()['state'], 'discovery_backoff')
        self.assertEqual(self.calls, [])
        self.now += timedelta(seconds=30)
        r.discover = self.discover
        self.assertEqual(r.tick()['executed'], 2)

    def test_failed_refresh_does_not_buy_using_old_inventory(self):
        r = self.runner()
        r.tick()
        self.calls.clear()
        self.now += timedelta(seconds=300)
        r.discover = lambda: (_ for _ in ()).throw(RuntimeError())
        self.assertEqual(r.tick()['state'], 'discovery_failed')
        self.assertEqual(self.calls, [])

    def test_stale_inventory_rejected(self):
        r = self.runner()
        r.discover = lambda: {**self.discover(), 'discovered_at': (self.now - timedelta(seconds=61)).isoformat()}
        self.assertEqual(r.tick()['state'], 'discovery_failed')
        self.assertEqual(self.calls, [])

    def test_uncertain_request_holds_cost_and_pauses(self):
        r = self.runner()
        r.transport = lambda *args: (_ for _ in ()).throw(TimeoutError())
        r.tick()
        self.assertEqual(self.g.status()['unknown_attempts'], 1)
        self.assertTrue(self.g.status()['paused'])
        self.assertEqual(r.tick()['state'], 'paused')

    def test_missing_charge_header_pauses_without_replay(self):
        r = self.runner()
        r.transport = lambda *args: (200, [], {}, self.now)
        r.tick()
        self.assertEqual(self.g.status()['unknown_attempts'], 1)
        self.assertEqual(r.tick()['state'], 'paused')

    def test_writer_failure_prevents_new_purchases(self):
        r = self.runner()
        r.tick()
        self.calls.clear()
        r.publisher = lambda *args: (_ for _ in ()).throw(RuntimeError())
        self.now += timedelta(seconds=60)
        failure = r.tick()
        self.assertEqual(failure['state'], 'publication_failed')
        self.assertEqual(failure['error_type'], 'RuntimeError')
        self.assertIsNone(failure['sqlstate'])
        self.assertEqual(self.calls, [])

    def test_clock_rechecked_between_requests(self):
        self.now = parse('2026-10-20T04:59:59Z')
        r = self.runner()
        def transport(*args):
            result = self.transport(*args)
            self.now = parse('2026-10-20T05:00:00Z')
            return (*result[:3], self.now)
        r.transport = transport
        r.tick()
        self.assertEqual(len(self.calls), 1)

    def test_expired_worker_cannot_settle_and_recovery_pauses(self):
        r = self.runner()
        def transport(*args):
            result = self.transport(*args)
            self.now += timedelta(seconds=121)
            return (*result[:3], self.now)
        r.transport = transport
        self.assertEqual(r.tick()['state'], 'lease_lost')
        self.assertEqual(self.runner().tick()['state'], 'paused')
        self.assertEqual(self.g.status()['unknown_attempts'], 1)

    def test_inventory_survives_database_reopen(self):
        r = self.runner()
        r.tick()
        self.g.release(r.owner)
        path = self.g.path
        self.g.close()
        self.g = Governor(path)
        self.assertEqual(self.runner().tick()['executed'], 0)
        self.assertEqual(self.discoveries, 1)


if __name__ == '__main__':
    unittest.main()

class PublicationResilienceTests(unittest.TestCase):
    setUp = RunnerTests.setUp
    tearDown = RunnerTests.tearDown
    discover = RunnerTests.discover
    transport = RunnerTests.transport
    runner = RunnerTests.runner
    def test_bad_capture_is_retained_without_blocking_good_capture(self):
        from corner.featured_markets import FeaturedMarketError
        r=self.runner()
        r.tick()
        count=self.g.db.execute('SELECT count(*) FROM publication_outbox').fetchone()[0]
        self.assertGreater(count,1)
        calls=[]
        def publish(token,record):
            calls.append(token)
            if len(calls)==1: raise FeaturedMarketError('invalid provider quote')
        r.publisher=publish
        self.assertEqual(r.tick()['state'],'publication_quarantined')
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM publication_failures WHERE quarantined=1').fetchone()[0],1)
        self.g.release(r.owner)
        r = self.runner(publisher=publish)
        r.tick()
        self.assertEqual(len(calls),2)
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM publication_outbox WHERE published_at IS NULL').fetchone()[0],count-1)
    def test_database_failure_backoff_buys_nothing(self):
        r=self.runner()
        r.tick()
        self.calls.clear()
        r.publisher=lambda *args: (_ for _ in ()).throw(RuntimeError('database unavailable'))
        self.assertEqual(r.tick()['state'],'publication_failed')
        self.assertEqual(r.tick()['state'],'publication_backoff')
        self.assertEqual(self.calls,[])
