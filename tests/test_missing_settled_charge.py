from datetime import timedelta
import json
import unittest
from corner.credit_governor import Refused
from tests.test_collection_live import LiveTests, NOW
from pipelines.collection_recover import reconcile_known_failure

class MissingCharge(unittest.TestCase):
    setUp=LiveTests.setUp
    tearDown=LiveTests.tearDown
    bind=LiveTests.bind
    acquire=LiveTests.acquire
    claim=LiveTests.claim

    def broken(self):
        self.bind();self.acquire();token=self.claim()
        with self.g.transaction() as db:
            db.execute("UPDATE attempts SET state='settled',actual=NULL WHERE token=?",(token,))
            db.execute("UPDATE controls SET paused='Recovery incomplete; preserve evidence for review' WHERE id=1")
        self.g.release('worker')
        return token

    def test_single_zero_charge_is_audited_and_normal_recovery_resumes(self):
        token=self.broken()
        result=reconcile_known_failure(self.g,NOW+timedelta(minutes=3),
            {'provider_used':0,'provider_remaining':15000000},accept_single_delta=True)
        self.assertEqual(result,{token:0})
        row=self.g.db.execute('SELECT state,actual,reserved FROM attempts WHERE token=?',(token,)).fetchone()
        self.assertEqual(tuple(row),('settled',0,3))
        audit=json.loads(self.g.db.execute("SELECT detail FROM quota_audit WHERE action='settled-charge-restored'").fetchone()[0])
        self.assertIsNone(audit['previous_actual'])
        self.assertFalse(self.g.status()['paused'])
        self.assertEqual(sum(self.g.accounted(self.g.db,'funded-cycle').values()),0)
        self.assertEqual(reconcile_known_failure(self.g,NOW+timedelta(minutes=4),{'provider_used':0,'provider_remaining':15000000},accept_single_delta=True),{})

    def test_missing_acceptance_young_and_excess_cost_leave_null_untouched(self):
        self.broken()
        for seconds,cost,accepted in [(180,0,False),(10,0,True),(180,4,True)]:
            with self.subTest(seconds=seconds,cost=cost,accepted=accepted):
                with self.assertRaises(Refused):
                    reconcile_known_failure(self.g,NOW+timedelta(seconds=seconds),{'provider_used':cost,'provider_remaining':15000000-cost},accept_single_delta=accepted)
                self.assertIsNone(self.g.db.execute('SELECT actual FROM attempts').fetchone()[0])

    def test_saved_charge_cannot_be_overridden_by_fresh_total(self):
        token=self.broken()
        with self.g.transaction() as db:
            self.g._audit(db,NOW,'odds-response','saved response',{'token':token,'actual':3})
        with self.assertRaises(Refused):
            reconcile_known_failure(self.g,NOW+timedelta(minutes=3),{'provider_used':0,'provider_remaining':15000000},accept_single_delta=True)
        self.assertIsNone(self.g.db.execute('SELECT actual FROM attempts').fetchone()[0])

    def test_more_than_one_missing_settlement_is_not_guessed(self):
        self.broken()
        row=dict(self.g.db.execute('SELECT * FROM attempts').fetchone())
        row['token']='another-missing-token'
        with self.g.transaction() as db:
            db.execute('INSERT INTO attempts ('+','.join(row)+') VALUES ('+','.join('?' for _ in row)+')',tuple(row.values()))
        with self.assertRaises(Refused):
            reconcile_known_failure(self.g,NOW+timedelta(minutes=3),{'provider_used':0,'provider_remaining':15000000},accept_single_delta=True)
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM attempts WHERE actual IS NULL').fetchone()[0],2)
