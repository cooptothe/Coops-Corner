"""Isolated member checkout and operator review; synthetic rates and transfers."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from corner import auth, beta_access as beta, beta_terms
from corner.beta_invoices import BetaInvoices
from corner.billing_config import checkout_config
from corner.tracker_store import TrackerStore
from pipelines.accounts import AuthContext
from pipelines.billing_service import create_router


class Checkout(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=TrackerStore(self.tmp.name+'/accounts.sqlite3')
        self.owner=self.store.create_user('Owner','owner','hash')['id']
        beta.bootstrap(self.store._db,'owner')
        self.config=json.loads(Path('fixtures/billing/receiving-disabled.json').read_text())
        self.config.update(payments_enabled=True,memo_reviewed=True,receive_test_passed=True,manual_review_ready=True,terms_version=beta_terms.VERSION)
        self.path=Path(self.tmp.name)/'billing.json';self.save()
        self.flags=patch.dict(os.environ,{'CORNER_PRIVATE_BETA':'1','CORNER_BETA_TRIALS':'1','CORNER_BILLING_CONFIG':str(self.path)})
        self.flags.start()
        self.users=[]
        for name in ('alice','bob'):
            _,token=beta.issue(self.store._db,self.owner,name,access_kind='preview',evidence='fixture')
            self.users.append(self.store.create_user(name,name,'hash',token)['id'])
        self.ctx=AuthContext(self.store,'s'*48,{'http://localhost:3000'})
        app=FastAPI();app.include_router(create_router(self.ctx))
        self.client=TestClient(app,base_url='http://localhost:3000')
        self.login(self.users[0])
        self.invoices=BetaInvoices(self.store)

    def save(self):self.path.write_text(json.dumps(self.config))
    def login(self,user):
        row=self.store.user_by_id(user)
        self.client.cookies.set('corner_session',auth.issue_token('s'*48,user,row['username'],epoch=row['session_epoch']))
    def tearDown(self):self.flags.stop();self.store.close();self.tmp.cleanup()
    def post(self,path,body):return self.client.post('/api/refresh/v1/billing/'+path,json=body,headers={'Origin':'http://localhost:3000'})
    def request(self):return self.post('requests',{'asset':'XRP','terms_version':beta_terms.VERSION}).json()['payment']['id']
    def quote(self,ident):
        return self.invoices.quote(self.owner,ident,usd_per_coin='2',observed_at=time.time(),source='synthetic test rate, not a market quote',receiving=self.config)

    def test_off_by_default_and_all_receiver_gates_required(self):
        for changes in ({'payments_enabled':False},{'memo_reviewed':False},{'receive_test_passed':False},{'manual_review_ready':False},{'terms_version':'old'}):
            with patch.dict(os.environ,{'CORNER_BILLING_CONFIG':''}):self.assertIsNone(checkout_config())
            original=dict(self.config);self.config.update(changes);self.save()
            self.assertIsNone(checkout_config())
            self.assertEqual(self.post('requests',{}).status_code,503)
            self.config=original;self.save()
        self.path.write_text('{broken')
        self.assertIsNone(checkout_config())

    def test_end_to_end_member_quote_claim_and_manual_approval(self):
        ident=self.request()
        self.assertEqual(self.client.get('/api/refresh/v1/billing/requests/current').json()['payment']['state'],'requested')
        self.quote(ident)
        payment=self.client.get('/api/refresh/v1/billing/requests/current').json()['payment']
        self.assertEqual(payment['instructions']['amount'],'25.000000')
        self.assertEqual(payment['instructions']['address'],self.config['receiving']['XRP']['address'])
        response=self.post('requests/'+ident+'/submit',{'transaction_id':'f'*64})
        self.assertEqual(response.status_code,200)
        self.assertNotIn('instructions',response.json()['payment'])
        self.assertEqual(self.store.user_by_id(self.users[0])['beta_access_kind'],'preview')
        self.invoices.approve(self.owner,ident,evidence='synthetic wallet and explorer evidence',delivered_base_units='25000000',destination=self.config['receiving']['XRP']['address'],memo=None,received_at=time.time(),transfer_index=0)
        # Paid fulfillment revokes the old session; a new login sees founder pricing.
        self.assertEqual(self.client.get('/api/refresh/v1/billing/status').status_code,401)
        self.login(self.users[0])
        offer=self.client.get('/api/refresh/v1/billing/status').json()
        self.assertTrue(offer['founder']);self.assertEqual(offer['launch_monthly_usd_cents'],5000)
        self.assertFalse(offer['checkout_eligible'])

    def test_ownership_origin_and_extra_fields_fail_closed(self):
        ident=self.request();self.quote(ident);self.login(self.users[1])
        self.assertIsNone(self.client.get('/api/refresh/v1/billing/requests/current').json()['payment'])
        for action,body in (('submit',{'transaction_id':'a'*64}),('cancel',{})):
            self.assertEqual(self.post('requests/'+ident+'/'+action,body).status_code,404)
        response=self.client.post('/api/refresh/v1/billing/requests',json={},headers={'Origin':'https://example.invalid'})
        self.assertEqual(response.status_code,403)
        self.assertEqual(self.post('requests',{'asset':'XRP','terms_version':beta_terms.VERSION,'settled':True}).status_code,400)
        self.client.cookies.clear()
        self.assertEqual(self.post('requests',{}).status_code,401)

    def test_expired_quote_and_disabled_checkout_hide_instructions(self):
        ident=self.request();self.quote(ident)
        self.store._db.execute('UPDATE beta_payment_requests SET expires_at=? WHERE id=?',(time.time()-1,ident))
        current=self.client.get('/api/refresh/v1/billing/requests/current').json()['payment']
        self.assertEqual(current['state'],'expired');self.assertNotIn('instructions',current)
        self.config['payments_enabled']=False;self.save()
        self.assertEqual(self.client.get('/api/refresh/v1/billing/requests/current').status_code,503)

    def test_rehearsal_quote_never_becomes_payable_by_enabling_config(self):
        ident=self.request()
        disabled={**self.config,'payments_enabled':False}
        self.invoices.quote(self.owner,ident,usd_per_coin='2',observed_at=time.time(),source='synthetic fixture',receiving=disabled)
        current=self.client.get('/api/refresh/v1/billing/requests/current').json()['payment']
        self.assertNotIn('instructions',current)

    def test_malformed_asset_and_json_are_rejected_without_server_error(self):
        for asset in ([],{},None):
            self.assertEqual(self.post('requests',{'asset':asset,'terms_version':beta_terms.VERSION}).status_code,400)
        response=self.client.post('/api/refresh/v1/billing/requests',content='{broken',headers={'Origin':'http://localhost:3000','Content-Type':'application/json'})
        self.assertEqual(response.status_code,400)

    def test_recovered_paid_invoice_replay_keeps_founder_and_receipt_once(self):
        import sqlite3
        ident=self.request();quote=self.quote(ident)
        self.post('requests/'+ident+'/submit',{'transaction_id':'d'*64})
        review=dict(evidence='synthetic independent review for restore test',delivered_base_units=quote['amount_base_units'],destination=quote['address'],memo=None,received_at=time.time(),transfer_index=0)
        self.invoices.approve(self.owner,ident,**review)
        recovery=self.tmp.name+'/recovered.sqlite3'
        db=sqlite3.connect(recovery)
        try:self.store._db.backup(db)
        finally:db.close()
        restored=TrackerStore(recovery)
        try:
            result=BetaInvoices(restored).approve(self.owner,ident,**review)
            self.assertTrue(result['reused'])
            self.assertTrue(restored.user_by_id(self.users[0])['beta_founder'])
            self.assertEqual(restored._db.execute('SELECT count(*) FROM beta_payment_receipts').fetchone()[0],1)
        finally:restored.close()

    def test_approved_invoice_cannot_be_cancelled(self):
        ident=self.request();quote=self.quote(ident)
        self.post('requests/'+ident+'/submit',{'transaction_id':'c'*64})
        self.invoices.approve(self.owner,ident,evidence='synthetic reviewed evidence only',delivered_base_units=quote['amount_base_units'],destination=quote['address'],memo=None,received_at=time.time(),transfer_index=0)
        self.login(self.users[0])
        self.assertEqual(self.post('requests/'+ident+'/cancel',{}).status_code,409)
        self.assertEqual(self.invoices.status(self.users[0],ident)['state'],'approved')
