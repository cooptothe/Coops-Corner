import os
import sqlite3
import importlib.util
from pathlib import Path
from unittest.mock import patch
import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from corner import beta_access as beta, beta_terms, invitation_welcome as welcome, auth
from corner.tracker_store import TrackerError, TrackerStore, read_user
from corner.beta_invoices import BetaInvoices
from pipelines.accounts import AuthContext, create_router as accounts_router
from pipelines.billing_service import create_router as billing_router
from tests.test_friend_membership import FriendMembership


class FamilyMembership(unittest.TestCase):
    setUp=FriendMembership.setUp
    tearDown=FriendMembership.tearDown
    tx=FriendMembership.tx

    def codes(self):
        return self.tx(beta.issue_family_codes,self.owner,evidence='Owner requested two brothers permanently free')

    def claim(self,code,name='brother'):
        self.tx(welcome.wrap,self.owner,code)
        self.tx(welcome.accept,code,dict(version=welcome.VERSION,terms_version=beta_terms.VERSION,eligible=True,agree=True))
        return self.store.create_user(name,name,'hash',code)

    def test_two_extra_places_even_with_all_other_places_reserved(self):
        self.tx(beta.issue_beta_codes,self.owner,count=10,evidence='test')
        self.tx(beta.issue_friend_codes,self.owner,count=5,evidence='test')
        codes=self.codes()
        self.assertEqual(len(codes),2)
        self.assertTrue(all(code.startswith('FAMILY-') for _,code in codes))
        self.assertEqual(beta.occupied(self.store._db),10)
        self.assertEqual(beta.occupied(self.store._db,cohort='friend'),5)
        self.assertEqual(beta.occupied(self.store._db,cohort='family'),2)
        with self.assertRaises(TrackerError):self.codes()
        user=self.claim(codes[0][1])
        self.assertEqual(user['cohort'],'family')
        self.assertEqual(user['role'],'member')
        with self.assertRaises(TrackerError):self.store.create_user('reuse','reuse','hash',codes[0][1])
        self.assertEqual(beta.occupied(self.store._db,cohort='family'),2)
        self.assertFalse(self.store._db.execute('SELECT 1 FROM beta_friend_rates WHERE user_id=?',(user['id'],)).fetchone())

    def test_permanent_entitlement_and_no_payment_even_after_release(self):
        _,code=self.codes()[0]
        user=self.claim(code)
        row=self.store.user_by_id(user['id'])
        for flags in ({'CORNER_PRIVATE_BETA':'1','CORNER_BETA_TRIALS':'1'},
                      {'CORNER_PRIVATE_BETA':'0','CORNER_BETA_TRIALS':'0'}):
            with patch.dict(os.environ,flags):
                membership=beta.access_status(self.store.user_by_id(user['id']),beta_terms.BETA_END+10*365*86400)
                self.assertTrue(membership['allowed'])
                self.assertIsNone(membership['expires_at'])
                self.assertEqual(membership['packages'],['standard','live'])
                secret='s'*48
                token=auth.issue_token(secret,user['id'],'brother')
                session=auth.session_user(secret,token,self.store.user_by_id)
                self.assertEqual(session['cohort'],'family')
                self.assertTrue(session['membership']['allowed'])
                app=FastAPI();ctx=AuthContext(self.store,secret,{'http://localhost:3000'})
                app.include_router(billing_router(ctx))
                client=TestClient(app,base_url='http://localhost:3000')
                client.cookies.set('corner_session',token)
                offer=client.get('/api/refresh/v1/billing/status').json()
                self.assertEqual(offer['launch_monthly_usd_cents'],0)
                self.assertFalse(offer['checkout_eligible'])
                self.assertEqual(client.post('/api/refresh/v1/billing/requests',headers={'Origin':'http://localhost:3000'},json={'asset':'XRP','terms_version':beta_terms.VERSION}).status_code,403)
        with self.assertRaises(TrackerError):BetaInvoices(self.store).request(user['id'],'XRP',beta_terms.VERSION)
        self.tx(beta.state,self.owner,'brother','suspended')
        with patch.dict(os.environ,{'CORNER_PRIVATE_BETA':'0'}):
            self.assertFalse(beta.access_status(self.store.user_by_id(user['id']))['allowed'])
            self.assertIsNone(auth.session_user(secret,token,self.store.user_by_id))

    def test_family_welcome_after_beta_and_signup_cannot_select_free_access(self):
        _,code=self.codes()[0]
        with patch('corner.invitation_welcome.time.time',return_value=beta_terms.BETA_END+86400):
            # A newly issued invitation still has a finite redemption window.
            self.store._db.execute('UPDATE beta_invites SET expires_at=? WHERE token_hash=?',(beta_terms.BETA_END+2*86400,beta.digest(code)))
            offer=welcome.offer(self.store._db,code)
            self.assertEqual(offer['cohort'],'family')
            self.assertIn('Always free',offer['pricing'])
            self.assertEqual(offer['end_label'],'No expiry')
        os.environ['CORNER_PRIVATE_BETA']='0'
        user=self.claim(code)
        self.assertEqual(user['cohort'],'family')
        self.assertEqual(read_user(self.path,user['id'])['beta_cohort'],'family')
        os.environ['CORNER_PRIVATE_BETA']='1'
        _,ordinary=self.tx(beta.issue,self.owner,'',access_kind='preview',unbound=True,evidence='test')
        app=FastAPI();app.include_router(accounts_router(AuthContext(self.store,'s'*48,{'http://localhost:3000'})))
        c=TestClient(app,base_url='http://localhost:3000')
        response=c.post('/api/refresh/v1/auth/register',headers={'Origin':'http://localhost:3000'},json={'username':'ordinary','password':'StrongExamplePassword123','invite':ordinary,'cohort':'family','role':'admin'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['user']['cohort'],'beta')

    def test_backup_and_restore_preserve_permanent_grants(self):
        _,code=self.codes()[0];user=self.claim(code)
        restored_path=Path(self.tmp.name)/'restored.sqlite3'
        target=sqlite3.connect(restored_path)
        self.store._db.backup(target);target.close()
        restored=TrackerStore(restored_path)
        try:self.assertTrue(beta.access_status(restored.user_by_id(user['id']),beta_terms.BETA_END+86400)['allowed'])
        finally:restored.close()
        module_path=Path(__file__).resolve().parents[1]/'deploy/backup/billing_checkpoint.py'
        spec=importlib.util.spec_from_file_location('family_backup',module_path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        before=module.account_billing_summary(self.path)
        self.assertEqual(before['beta_family_members']['rows'],1)
        self.assertEqual(before['beta_family_invites']['rows'],2)
        self.store._db.execute("UPDATE beta_family_members SET evidence='tampered'")
        self.assertNotEqual(before,module.account_billing_summary(self.path))

    def test_private_issuance_receipt_is_idempotent_and_not_a_new_pool(self):
        from pipelines.family_invitations import prepare
        output=Path(self.tmp.name)/'brothers.json'
        first=prepare(self.store,output)
        self.assertEqual(len(first),2)
        self.assertEqual(prepare(self.store,output),first)
        self.assertEqual(beta.occupied(self.store._db,cohort='family'),2)
        self.assertEqual(beta.occupied(self.store._db,cohort='friend'),0)
        output.unlink()
        with self.assertRaises(TrackerError):prepare(self.store,output)
        self.assertFalse(output.exists())
