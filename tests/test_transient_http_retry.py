from datetime import timedelta
import unittest
from unittest.mock import patch

from tests import test_collection_live as fixture
from pipelines.collection_recover import reconcile_known_failure
from corner.collection_quota import LiveGovernor


class TransientHttpRetry(unittest.TestCase):
    setUp=fixture.LiveTests.setUp
    tearDown=fixture.LiveTests.tearDown
    bind=fixture.LiveTests.bind
    acquire=fixture.LiveTests.acquire
    claim=fixture.LiveTests.claim

    def legacy(self,actual,status):
        self.bind();self.acquire();token=self.claim()
        with self.g.transaction() as db:
            self.g._audit(db,fixture.NOW,'odds-response','fixture',{'token':token,'http_status':status,'reason':'Missing or invalid provider quota header','charge_verified':False})
        self.g.unknown(token,'worker',fixture.NOW);self.g.release('worker')
        later=fixture.NOW+timedelta(minutes=3)
        with patch('corner.collection_retry.release_zero_charge_recoveries'):
            reconcile_known_failure(self.g,later,{'provider_used':actual,'provider_remaining':15000000-actual},accept_single_delta=True)
        return token,later

    def test_old_502_paid_charge_is_preserved_and_scope_rescheduled(self):
        token,later=self.legacy(2,502)
        before=tuple(self.g.db.execute('SELECT * FROM attempts').fetchone())
        reconcile_known_failure(self.g,later,{'provider_used':2,'provider_remaining':14999998},accept_single_delta=True)
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM collection_quarantine').fetchone()[0],0)
        self.assertEqual(tuple(self.g.db.execute('SELECT * FROM attempts').fetchone()),before)
        self.assertEqual(self.g._binding(self.g.db,later)['used'],2)
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM transport_quarantine_archive').fetchone()[0],1)
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM publication_outbox').fetchone()[0],0)

    def test_crash_after_verified_502_headers_recovers_without_refunding(self):
        self.bind();self.acquire();token=self.claim()
        with self.g.transaction() as db:
            self.g._check(db,fixture.NOW,fixture.headers(2,2))
            self.g._audit(db,fixture.NOW,'odds-response','fixture',{'token':token,'http_status':502,'reason':'','actual':2,'charge_verified':True})
        self.g.unknown(token,'worker',fixture.NOW);self.g.release('worker')
        reconcile_known_failure(self.g,fixture.NOW,{'provider_used':2,'provider_remaining':14999998})
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM collection_quarantine').fetchone()[0],0)
        self.assertEqual(self.g.db.execute('SELECT state,actual FROM attempts').fetchone()[:],('settled',2))

    def test_old_429_zero_cost_rescheduled_but_422_scope_error_not_released(self):
        for status,remaining in [(429,0),(422,1)]:
            with self.subTest(status=status):
                if status==422:self.tearDown();self.setUp()
                _,later=self.legacy(0,status)
                reconcile_known_failure(self.g,later,{'provider_used':0,'provider_remaining':15000000},accept_single_delta=True)
                self.assertEqual(self.g.db.execute('SELECT count(*) FROM collection_quarantine').fetchone()[0],remaining)

    def test_verified_transient_response_settles_cost_without_global_pause(self):
        self.bind();self.acquire();token=self.claim()
        result=self.g.finish(self.job,token,'worker',fixture.NOW,fixture.headers(2,2),[],502)
        self.assertEqual(result,'retry_scheduled')
        self.assertEqual(self.g.db.execute('SELECT state,actual FROM attempts').fetchone()[:],('settled',2))
        self.assertFalse(self.g.status()['paused'])
        self.assertFalse(self.g.ready(self.job,fixture.NOW+timedelta(seconds=121)))
        self.assertTrue(self.g.ready(self.job,fixture.NOW+timedelta(seconds=301)))
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM publication_outbox').fetchone()[0],0)
        self.g.release('worker');path=self.g.path;self.g.close();self.g=LiveGovernor(path)
        self.assertFalse(self.g.ready(self.job,fixture.NOW+timedelta(seconds=121)))

    def test_missing_headers_429_remains_unknown_until_quota_reconciled(self):
        self.bind();self.acquire();token=self.claim()
        self.assertEqual(self.g.finish(self.job,token,'worker',fixture.NOW,{},[],429),'unknown')
        self.assertEqual(self.g.status()['unknown_attempts'],1)
        self.g.release('worker')
        later=fixture.NOW+timedelta(minutes=3)
        reconcile_known_failure(self.g,later,{'provider_used':0,'provider_remaining':15000000},accept_single_delta=True)
        self.assertEqual(self.g.status()['unknown_attempts'],0)
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM collection_quarantine').fetchone()[0],0)

    def test_transient_error_cannot_override_reservation_ceiling(self):
        self.bind();self.acquire();token=self.claim()
        self.assertEqual(self.g.finish(self.job,token,'worker',fixture.NOW,fixture.headers(4,4),[],502),'paused')
        self.assertTrue(self.g.status()['paused'])
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM collection_retry_cooldowns').fetchone()[0],0)


if __name__=='__main__':unittest.main()
