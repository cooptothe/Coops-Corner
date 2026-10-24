from datetime import timedelta
import json
import unittest
from unittest.mock import patch

from corner.collection_retry import release_zero_charge_recoveries
from corner.credit_governor import Refused
from pipelines.collection_recover import reconcile_known_failure
from tests.test_collection_live import LiveTests, NOW


class ZeroChargeRetry(unittest.TestCase):
    setUp=LiveTests.setUp
    tearDown=LiveTests.tearDown
    bind=LiveTests.bind
    acquire=LiveTests.acquire
    claim=LiveTests.claim

    def legacy(self,actual=0):
        self.bind();self.acquire();token=self.claim()
        self.g.unknown(token,'worker',NOW);self.g.release('worker')
        later=NOW+timedelta(minutes=3)
        with patch('corner.collection_retry.release_zero_charge_recoveries'):
            reconcile_known_failure(self.g,later,{'provider_used':actual,'provider_remaining':15000000-actual},accept_single_delta=True)
        return token,later

    def test_legacy_zero_charge_released_after_cooldown_without_accounting_change(self):
        token,later=self.legacy()
        before=tuple(self.g.db.execute('SELECT * FROM attempts').fetchone())
        released=release_zero_charge_recoveries(self.g,later)
        self.assertEqual(len(released),1)
        self.assertEqual(released[0]['retry_after'],(later+timedelta(minutes=5)).timestamp())
        self.assertFalse(self.g.ready(self.job,later+timedelta(minutes=4)))
        self.g.acquire('worker',later)
        self.g.prepare_due(self.job,'worker',later)
        with self.assertRaisesRegex(Refused,'cooling down'):
            self.g.claim(self.job,'worker',later)
        self.g.release('worker')
        self.assertTrue(self.g.ready(self.job,later+timedelta(minutes=6)))
        self.assertEqual(tuple(self.g.db.execute('SELECT * FROM attempts').fetchone()),before)
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM snapshots').fetchone()[0],0)
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM publication_outbox').fetchone()[0],0)
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM transport_quarantine_archive').fetchone()[0],1)

    def test_future_recovery_automatically_uses_cooldown(self):
        self.bind();self.acquire();token=self.claim()
        self.g.unknown(token,'worker',NOW);self.g.release('worker')
        later=NOW+timedelta(minutes=3)
        result=reconcile_known_failure(self.g,later,{'provider_used':0,'provider_remaining':15000000},accept_single_delta=True)
        self.assertEqual(result,{token:0})
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM collection_quarantine').fetchone()[0],0)
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM transport_quarantine_archive').fetchone()[0],1)

    def test_nonzero_charge_remains_quarantined(self):
        _,later=self.legacy(2)
        self.assertEqual(release_zero_charge_recoveries(self.g,later),[])
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM collection_quarantine').fetchone()[0],1)

    def test_missing_reconciliation_proof_cannot_release(self):
        _,later=self.legacy()
        self.g.db.execute("DELETE FROM quota_audit WHERE action='reconcile'")
        self.assertEqual(release_zero_charge_recoveries(self.g,later),[])

    def test_saved_response_or_settlement_failure_stays_blocked(self):
        for action,detail in [('odds-response',{'http_status':200}),('request-failed',{'phase':'settlement_and_snapshot'})]:
            with self.subTest(action=action):
                if action!='odds-response':
                    self.tearDown();self.setUp()
                token,later=self.legacy()
                with self.g.transaction() as db:
                    self.g._audit(db,later,action,'fixture',{'token':token,**detail})
                reconcile_known_failure(self.g,later,{'provider_used':0,'provider_remaining':15000000},accept_single_delta=True)
                self.assertEqual(self.g.db.execute('SELECT count(*) FROM collection_quarantine').fetchone()[0],1)

    def test_active_worker_refused(self):
        _,later=self.legacy()
        self.g.acquire('worker',later)
        with self.assertRaises(Refused):release_zero_charge_recoveries(self.g,later)

    def test_repeated_scope_failure_increases_cooldown(self):
        _,later=self.legacy()
        self.g.db.execute('CREATE TABLE transport_quarantine_archive(job_key TEXT,token TEXT,created REAL,code TEXT,detail TEXT,released REAL,retry_after REAL,PRIMARY KEY(job_key,token))')
        for i in range(6):
            self.g.db.execute('INSERT INTO transport_quarantine_archive VALUES(?,?,?,?,?,?,?)',(self.job.key,str(i),0,'fixture','{}',0,0))
        released=release_zero_charge_recoveries(self.g,later)
        self.assertEqual(released[0]['retry_after'],later.timestamp()+3600)


if __name__=='__main__':unittest.main()
