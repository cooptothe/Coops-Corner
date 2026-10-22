from datetime import timedelta
import json
import unittest
from corner.credit_governor import Refused
from pipelines.collection_recover import reconcile_known_failure
from tests.test_collection_live import LiveTests, NOW, headers


class Recovery(LiveTests):
    def test_bad_but_accounted_payload_quarantines_scope_and_preserves_charge(self):
        self.bind();self.acquire();token=self.claim()
        result=self.g.finish(self.job,token,'worker',NOW,headers(3,3),{'bad':'envelope'})
        self.assertEqual(result,'quarantined')
        self.assertFalse(self.g.status()['paused'])
        self.assertEqual(self.g.db.execute('SELECT state,actual FROM attempts').fetchone()[:],('settled',3))
        self.assertFalse(self.g.ready(self.job,NOW+timedelta(minutes=10)))
        with self.assertRaises(Refused):
            self.g.claim(self.job,'worker',NOW)
        self.assertEqual(self.g._binding(self.g.db,NOW)['used'],3)
        self.assertIsNone(self.g.db.execute('SELECT 1 FROM publication_outbox').fetchone())

    def test_rejected_scope_does_not_pause_healthy_work(self):
        self.bind();self.acquire();token=self.claim()
        self.assertEqual(self.g.finish(self.job,token,'worker',NOW,headers(0,0),[],422),'quarantined')
        self.assertFalse(self.g.status()['paused'])
        self.assertEqual(self.g.status()['unknown_attempts'],0)

    def test_quota_drift_still_stops_everything(self):
        self.bind();self.acquire();token=self.claim()
        self.assertEqual(self.g.finish(self.job,token,'worker',NOW,headers(8,3),{'bad':'envelope'},422),'paused')
        self.assertTrue(self.g.status()['paused'])
        self.assertIsNone(self.g.db.execute('SELECT 1 FROM collection_quarantine').fetchone())

    def test_old_verified_charge_can_be_reconciled_without_new_purchase(self):
        self.bind();self.acquire();token=self.claim()
        # Reproduce legacy crash: quota update and response audit committed, snapshot rolled back.
        with self.g.transaction() as db:
            self.g._check(db,NOW,headers(3,3))
            self.g._audit(db,NOW,'odds-response','provider response',{'token':token,'reason':''})
        self.g.unknown(token,'worker',NOW);self.g.release('worker')
        settled=reconcile_known_failure(self.g,NOW,{'provider_used':3,'provider_remaining':14999997})
        self.assertEqual(settled,{token:3})
        self.assertEqual(self.g.status()['unknown_attempts'],0)
        self.assertFalse(self.g.status()['paused'])
        self.assertFalse(self.g.ready(self.job,NOW+timedelta(minutes=5)))
        self.assertEqual(self.g._binding(self.g.db,NOW)['used'],3)

    def test_unverified_network_failure_does_not_get_a_free_refund(self):
        self.bind();self.acquire();token=self.claim()
        self.g.unknown(token,'worker',NOW);self.g.release('worker')
        with self.assertRaises(Refused):
            reconcile_known_failure(self.g,NOW,{'provider_used':0,'provider_remaining':15000000})
        self.assertEqual(self.g.status()['unknown_attempts'],1)

    def test_changed_usage_cannot_be_hidden_in_one_unknown_charge(self):
        self.bind();self.acquire();token=self.claim()
        with self.g.transaction() as db:
            self.g._check(db,NOW,headers(3,3))
            self.g._audit(db,NOW,'odds-response','provider response',{'token':token,'reason':''})
        self.g.unknown(token,'worker',NOW);self.g.release('worker')
        with self.assertRaises(Refused):
            reconcile_known_failure(self.g,NOW,{'provider_used':4,'provider_remaining':14999996})
        self.assertEqual(self.g.status()['unknown_attempts'],1)

    def test_operator_can_accept_fresh_total_delta_for_one_stopped_old_request(self):
        self.bind();self.acquire();token=self.claim()
        self.g.unknown(token,'worker',NOW);self.g.release('worker')
        later=NOW+timedelta(minutes=3)
        settlements=reconcile_known_failure(self.g,later,
                    {'provider_used':2,'provider_remaining':14999998},accept_single_delta=True)
        self.assertEqual(settlements,{token:2})
        self.assertEqual(self.g._binding(self.g.db,later)['used'],2)
        self.assertEqual(self.g.status()['unknown_attempts'],0)
        self.assertFalse(self.g.ready(self.job,later))

    def test_quota_delta_cannot_override_a_young_request_or_its_reservation(self):
        self.bind();self.acquire();token=self.claim()
        self.g.unknown(token,'worker',NOW);self.g.release('worker')
        with self.assertRaises(Refused):
            reconcile_known_failure(self.g,NOW,{'provider_used':0,'provider_remaining':15000000},accept_single_delta=True)
        with self.assertRaises(Refused):
            reconcile_known_failure(self.g,NOW+timedelta(minutes=3),
                  {'provider_used':4,'provider_remaining':14999996},accept_single_delta=True)
        self.assertEqual(self.g.status()['unknown_attempts'],1)

class InventoryRecovery(unittest.TestCase):
    setUp=LiveTests.setUp
    tearDown=LiveTests.tearDown
    bind=LiveTests.bind
    acquire=LiveTests.acquire
    def uncertain_inventory(self):
        self.bind();self.acquire()
        token=self.g.authorize('worker',NOW,self.identity,inventory=True)
        self.g.inventory_unknown(token,'worker',NOW)
        self.g.release('worker')
        return token

    def test_old_inventory_recovers_with_fresh_unchanged_quota(self):
        token=self.uncertain_inventory()
        result=reconcile_known_failure(self.g,NOW+timedelta(minutes=3),
                    {'provider_used':0,'provider_remaining':15000000},accept_single_delta=True)
        self.assertEqual(result,{token:0})
        self.assertEqual(self.g.db.execute('SELECT state,actual FROM quota_inventory').fetchone()[:],('settled',0))
        self.assertFalse(self.g.status()['paused'])
        self.assertIsNone(self.g.db.execute('SELECT 1 FROM attempts').fetchone())

    def test_inventory_drift_young_or_no_acceptance_stays_unknown(self):
        self.uncertain_inventory()
        for later,used,accepted in [(180,1,True),(30,0,True),(180,0,False)]:
            with self.assertRaises(Refused):
                reconcile_known_failure(self.g,NOW+timedelta(seconds=later),
                  {'provider_used':used,'provider_remaining':15000000-used},accept_single_delta=accepted)
        self.assertEqual(self.g.db.execute('SELECT state FROM quota_inventory').fetchone()[0],'unknown')

    def test_multiple_inventory_failures_are_not_guessed(self):
        self.uncertain_inventory()
        self.g.db.execute("INSERT INTO quota_inventory SELECT 'second',cycle_id,owner,started,state,actual FROM quota_inventory")
        with self.assertRaises(Refused):
            reconcile_known_failure(self.g,NOW+timedelta(minutes=3),
                {'provider_used':0,'provider_remaining':15000000},accept_single_delta=True)

if __name__=='__main__':unittest.main()
