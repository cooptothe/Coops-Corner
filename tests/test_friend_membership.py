import os
import sqlite3
import importlib.util
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from unittest.mock import patch
from corner import auth, beta_access as beta, beta_terms as terms
from corner.tracker_store import TrackerStore, TrackerError, read_user
from corner.beta_invoices import BetaInvoices
from pipelines.accounts import AuthContext
from pipelines.billing_service import create_router
from fastapi import FastAPI
from fastapi.testclient import TestClient

class FriendMembership(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=self.tmp.name+'/accounts.sqlite3'
        self.flags=patch.dict(os.environ,{'CORNER_PRIVATE_BETA':'0','CORNER_BETA_TRIALS':'0'})
        self.flags.start()
        self.store=TrackerStore(self.path)
        self.owner=self.store.create_user('Owner','owner','hash')['id']
        self.tx(beta.bootstrap,'owner')
        os.environ['CORNER_PRIVATE_BETA']='1'

    def tearDown(self):
        self.store.close();self.flags.stop();self.tmp.cleanup()

    def tx(self,fn,*args,**kwargs):
        with self.store._lock:
            self.store._db.execute('BEGIN IMMEDIATE')
            try:
                result=fn(self.store._db,*args,**kwargs)
                self.store._db.execute('COMMIT');return result
            except BaseException:
                self.store._db.execute('ROLLBACK');raise

    def member(self,name,cohort='friend'):
        _,token=self.tx(beta.issue,self.owner,name,access_kind='preview',cohort=cohort,evidence='Owner approved contributor')
        return self.store.create_user(name,name,'hash',token)

    def test_independent_ten_and_five_pools_and_reservations(self):
        for i in range(10):self.tx(beta.issue,self.owner,f'beta{i}',access_kind='preview',evidence='test')
        for i in range(5):self.member(f'friend{i}')
        self.assertEqual(beta.occupied(self.store._db),10)
        self.assertEqual(beta.occupied(self.store._db,cohort='friend'),5)
        for cohort in ('beta','friend'):
            with self.assertRaises(TrackerError):self.member('overflow'+cohort,cohort)
        self.tx(beta.state,self.owner,'friend0','suspended')
        self.assertEqual(beta.occupied(self.store._db,cohort='friend'),5)
        self.tx(beta.state,self.owner,'friend0','closed')
        self.member('replacement')
        with self.assertRaises(TrackerError):self.tx(beta.state,self.owner,'friend0','active')

    def test_friend_capacity_is_atomic_across_connections(self):
        def issue(index):
            store=TrackerStore(self.path)
            try:
                store._db.execute('BEGIN IMMEDIATE')
                try:
                    beta.issue(store._db,self.owner,f'friend{index}',cohort='friend',access_kind='preview',evidence='test')
                    store._db.execute('COMMIT');return True
                except TrackerError:
                    store._db.execute('ROLLBACK');return False
            finally:store.close()
        with ThreadPoolExecutor(max_workers=5) as pool:self.assertEqual(sum(pool.map(issue,range(9))),5)
        self.assertEqual(beta.occupied(self.store._db),0)

    def test_friend_full_beta_and_prices_survive_readonly_lookup_and_restore(self):
        user=self.member('friend')
        for trials in ('0','1'):
            with patch.dict(os.environ,{'CORNER_BETA_TRIALS':trials}):
                row=read_user(self.path,user['id'])
                self.assertTrue(beta.access_status(row,terms.BETA_END-1)['allowed'])
                self.assertFalse(beta.access_status(row,terms.BETA_END)['allowed'])
                self.assertEqual(row['beta_friend_rates'],dict(standard_usd_cents=2500,live_usd_cents=5000,locked=True))
        backup=self.tmp.name+'/restored.sqlite3'
        with closing(sqlite3.connect(backup)) as target:self.store._db.backup(target)
        restored=TrackerStore(backup)
        try:self.assertEqual(restored.user_by_id(user['id'])['beta_friend_rates'],self.store.user_by_id(user['id'])['beta_friend_rates'])
        finally:restored.close()

    def test_friend_cannot_be_charged_beta_fee_and_offer_is_server_selected(self):
        user=self.member('friend')
        with self.assertRaises(TrackerError):BetaInvoices(self.store).request(user['id'],'XRP',terms.VERSION)
        from corner.beta_billing import BetaBilling
        from tests.test_beta_billing import receipt
        billing=BetaBilling(self.store)
        ident=billing.verify(self.owner,'friend',receipt())
        with self.assertRaises(TrackerError):billing.fulfill(self.owner,ident)
        app=FastAPI();ctx=AuthContext(self.store,'s'*48,{'http://localhost:3000'})
        app.include_router(create_router(ctx))
        row=self.store.user_by_id(user['id'])
        client=TestClient(app,base_url='http://localhost:3000')
        client.cookies.set('corner_session',auth.issue_token('s'*48,user['id'],'friend',epoch=row['session_epoch']))
        offer=client.get('/api/refresh/v1/billing/status').json()
        self.assertEqual(offer['cohort'],'friend')
        self.assertFalse(offer['checkout_eligible'])
        self.assertFalse(offer['founder'])
        self.assertEqual(offer['launch_monthly_usd_cents'],2500)
        self.assertEqual(offer['friend_rates']['live_usd_cents'],5000)
        self.tx(beta.state,self.owner,'friend','suspended')
        self.assertIsNone(auth.session_user('s'*48,client.cookies.get('corner_session'),self.store.user_by_id))

    def test_explicit_move_frees_beta_seat_and_revokes_sessions(self):
        user=self.member('tester','beta')
        old=auth.issue_token('s'*48,user['id'],'tester')
        self.tx(beta.move_friend,self.owner,'tester','Owner approved friend')
        self.assertEqual(beta.occupied(self.store._db),0)
        self.assertEqual(beta.occupied(self.store._db,cohort='friend'),1)
        self.assertIsNone(auth.session_user('s'*48,old,self.store.user_by_id))
        with self.assertRaises(TrackerError):self.tx(beta.issue,self.owner,'invalid',cohort='friend',access_kind='paid_beta',evidence='test')

    def test_migration_preserves_legacy_members_invites_and_trial_starts(self):
        user=self.member('legacy','beta')
        _,paid=self.tx(beta.issue,self.owner,'paid',access_kind='paid_beta',evidence='Synthetic verified receipt')
        self.store.create_user('paid','paid','hash',paid)
        self.tx(beta.issue,self.owner,'pending',access_kind='preview',evidence='pending test')
        self.tx(beta.start_trial,self.owner,'legacy')
        db=self.store._db
        before=[tuple(row) for row in db.execute('SELECT user_id,role,state,founder,access_kind,evidence,created_at FROM beta_members')]
        trials=[tuple(row) for row in db.execute('SELECT * FROM beta_trials')]
        db.execute('DROP INDEX beta_member_pool');db.execute('DROP INDEX beta_invite_pool')
        db.execute('ALTER TABLE beta_members DROP COLUMN cohort');db.execute('ALTER TABLE beta_invites DROP COLUMN cohort')
        beta.initialize(db);beta.initialize(db)
        self.assertEqual(before,[tuple(row) for row in db.execute('SELECT user_id,role,state,founder,access_kind,evidence,created_at FROM beta_members')])
        self.assertEqual(trials,[tuple(row) for row in db.execute('SELECT * FROM beta_trials')])
        self.assertEqual(self.store.user_by_id(user['id'])['beta_cohort'],'beta')
        self.assertEqual(beta.occupied(db),3)
        self.assertTrue(self.store.user_by_key('paid')['beta_founder'])

    def test_signup_uses_invite_cohort_not_client_selected_cohort(self):
        from pipelines.accounts import create_router as accounts_router
        app=FastAPI();app.include_router(accounts_router(AuthContext(self.store,'s'*48,{'http://localhost:3000'})))
        _,code=self.tx(beta.issue,self.owner,'friendnew',cohort='friend',access_kind='preview',evidence='friend')
        client=TestClient(app,base_url='http://localhost:3000')
        response=client.post('/api/refresh/v1/auth/register',headers={'Origin':'http://localhost:3000'},json={'username':'friendnew','password':'StrongPrivateExample123','invite':code,'cohort':'beta','friend_rates':{'standard_usd_cents':1},'remember':False})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['user']['cohort'],'friend')
        self.assertEqual(response.json()['user']['membership']['state'],'friend')
        self.assertEqual(response.json()['user']['friend_rates']['standard_usd_cents'],2500)
        _,code=self.tx(beta.issue,self.owner,'betanew',access_kind='preview',evidence='beta')
        response=client.post('/api/refresh/v1/auth/register',headers={'Origin':'http://localhost:3000'},json={'username':'betanew','password':'StrongPrivateExample123','invite':code,'cohort':'friend','role':'admin'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['user']['cohort'],'beta')
        self.assertIsNone(response.json()['user']['friend_rates'])

    def test_backup_summary_covers_friend_rates_and_rejects_tampering(self):
        module_path=Path(__file__).resolve().parents[1]/'deploy/backup/billing_checkpoint.py'
        spec=importlib.util.spec_from_file_location('friend_backup_check',module_path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.member('friend')
        before=module.account_billing_summary(self.path)
        self.assertEqual(before['beta_friend_rates']['rows'],1)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE beta_friend_rates SET evidence='tampered'");db.commit()
        self.assertNotEqual(before,module.account_billing_summary(self.path))
        with self.assertRaises(ValueError):module.recover_billing(Path(self.tmp.name),{'account_billing':before})

if __name__=='__main__':unittest.main()
