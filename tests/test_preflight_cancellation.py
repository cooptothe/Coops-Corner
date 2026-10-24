import unittest
from unittest.mock import patch
from datetime import timedelta
from corner.credit_governor import RequestNotSent, Refused
from pipelines.collection_provider import Provider
from tests.test_collection_adapters import Adapters, Session, NOW
from tests.test_collection_runner import RunnerTests


class PreflightTransport(unittest.TestCase):
    setUp=Adapters.setUp
    tearDown=Adapters.tearDown

    def test_local_gate_refused_proves_no_http(self):
        job=self.jobs[0]
        token=self.g.claim(job,'worker',NOW)
        session=Session([])
        provider=Provider(key='fixture',enabled=False,session=session,clock=lambda:NOW)
        with self.assertRaises(RequestNotSent):provider.odds(self.g,job,token,'worker')
        self.assertEqual(session.calls,[])

    def test_reused_dispatch_cannot_be_reclassified_as_not_sent(self):
        job=self.jobs[0];token=self.g.claim(job,'worker',NOW)
        self.g.db.execute('INSERT INTO dispatches VALUES(?,?)',(token,NOW.timestamp()))
        provider=Provider(key='fixture',enabled=False,session=Session([]),clock=lambda:NOW)
        with self.assertRaises(Refused) as caught:provider.odds(self.g,job,token,'worker')
        self.assertNotIsInstance(caught.exception,RequestNotSent)

    def test_failure_after_network_boundary_never_claims_not_sent(self):
        job=self.jobs[0];token=self.g.claim(job,'worker',NOW)
        session=Session([])
        session.get=lambda *args,**kwargs: (_ for _ in ()).throw(Refused('fixture network failure'))
        provider=Provider(key='fixture',enabled=True,session=session,clock=lambda:NOW)
        with self.assertRaises(RuntimeError) as caught:provider.odds(self.g,job,token,'worker')
        self.assertNotIsInstance(caught.exception,RequestNotSent)


class PreflightRunner(unittest.TestCase):
    setUp=RunnerTests.setUp
    tearDown=RunnerTests.tearDown
    discover=RunnerTests.discover
    transport=RunnerTests.transport
    runner=RunnerTests.runner

    def test_proven_not_sent_settles_zero_and_keeps_healthy_scope_running(self):
        runner=self.runner()
        calls=[]
        def transport(*args):
            calls.append(1)
            if len(calls)==1:raise RequestNotSent('fixture local refusal')
            return self.transport(*args)
        runner.transport=transport
        runner.tick()
        self.assertEqual(self.g.status()['unknown_attempts'],0)
        self.assertFalse(self.g.status()['paused'])
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM attempts WHERE actual=0').fetchone()[0],1)
        self.assertEqual(len(self.calls),1)

    def test_generic_refusal_remains_uncertain(self):
        runner=self.runner()
        runner.transport=lambda *args: (_ for _ in ()).throw(Refused('no proof of no network'))
        runner.tick()
        self.assertEqual(self.g.status()['unknown_attempts'],1)
        self.assertTrue(self.g.status()['paused'])


from tests import test_collection_live as live_fixtures

class PreflightQuota(unittest.TestCase):
    setUp=live_fixtures.LiveTests.setUp
    tearDown=live_fixtures.LiveTests.tearDown
    bind=live_fixtures.LiveTests.bind
    acquire=live_fixtures.LiveTests.acquire
    claim=live_fixtures.LiveTests.claim

    def test_proven_cancellation_preserves_quota_and_enforces_cooldown(self):
        self.bind();self.acquire();token=self.claim()
        self.g.cancel_not_sent(self.job,token,'worker',NOW)
        self.assertEqual(self.g.db.execute('SELECT state,actual FROM attempts').fetchone()[:],('settled',0))
        self.assertEqual(self.g._binding(self.g.db,NOW)['used'],0)
        self.assertFalse(self.g.status()['paused'])
        self.assertFalse(self.g.ready(self.job,NOW+timedelta(seconds=121)))
        self.assertTrue(self.g.ready(self.job,NOW+timedelta(seconds=301)))
        with self.assertRaises(Refused):self.g.cancel_not_sent(self.job,token,'worker',NOW)


if __name__=='__main__':unittest.main()
