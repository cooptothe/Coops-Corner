"""Synthetic invoice lifecycle; no provider/chain requests or funds."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from corner import beta_access as beta, beta_terms as terms
from corner.beta_invoices import BetaInvoices
from corner.tracker_store import TrackerStore, TrackerError


class InvoiceLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TrackerStore(self.tmp.name+'/accounts.sqlite3')
        self.owner = self.store.create_user('Owner','owner','hash')['id']
        beta.bootstrap(self.store._db,'owner')
        self.flags = patch.dict(os.environ,{'CORNER_PRIVATE_BETA':'1','CORNER_BETA_TRIALS':'0'})
        self.flags.start()
        self.users=[]
        for name in ('alice','bob'):
            _,token=beta.issue(self.store._db,self.owner,name,access_kind='preview',evidence='fixture')
            self.users.append(self.store.create_user(name,name,'hash',token)['id'])
        self.now=1792000000
        self.invoices=BetaInvoices(self.store,lambda:self.now)
        self.receiving=json.loads(Path('fixtures/billing/receiving-disabled.json').read_text())

    def tearDown(self):
        self.flags.stop();self.store.close();self.tmp.cleanup()

    def request(self,user=None,asset='XRP'):
        return self.invoices.request(user or self.users[0],asset,terms.VERSION)

    def quote(self,ident):
        return self.invoices.quote(self.owner,ident,usd_per_coin='2',observed_at=self.now,source='synthetic fixture, not market data',receiving=self.receiving)

    def test_terms_and_member_binding(self):
        with self.assertRaises(TrackerError):self.invoices.request(self.users[0],'XRP','old-terms')
        with self.assertRaises(TrackerError):self.request(asset='ONDO')
        with self.assertRaises(TrackerError):self.request(self.owner)
        ident=self.request()
        self.assertEqual(ident,self.request())
        with self.assertRaises(TrackerError):self.request(asset='XLM')
        with self.assertRaises(TrackerError):self.invoices.status(self.users[1],ident)
        with self.assertRaises(TrackerError):self.invoices.cancel(self.users[1],ident)

    def test_exact_quote_and_expiry_without_public_instructions(self):
        ident=self.request();quote=self.quote(ident)
        self.assertEqual(quote['amount_base_units'],'25000000')
        self.assertFalse(quote['send_funds'])
        status=self.invoices.status(self.users[0],ident)
        self.assertNotIn('address',json.dumps(status))
        self.assertEqual(status['state'],'quoted')
        self.now+=600
        self.assertEqual(self.invoices.status(self.users[0],ident)['state'],'expired')
        self.assertNotEqual(ident,self.request())

    def test_unreviewed_or_stale_rate_and_nonoperator_cannot_quote(self):
        ident=self.request()
        for observed in (self.now-61,self.now+1,float('nan')):
            with self.assertRaises(TrackerError):
                self.invoices.quote(self.owner,ident,usd_per_coin='2',observed_at=observed,source='fixture',receiving=self.receiving)
        with self.assertRaises(TrackerError):
            self.invoices.quote(self.users[0],ident,usd_per_coin='2',observed_at=self.now,source='fixture',receiving=self.receiving)
        self.assertEqual(self.invoices.status(self.users[0],ident)['state'],'requested')

    def test_claim_never_grants_access_and_exact_replay_is_safe(self):
        ident=self.request();self.quote(ident)
        self.assertEqual(self.invoices.submit(self.users[0],ident,'A'*64),'submitted')
        self.assertEqual(self.invoices.submit(self.users[0],ident,'a'*64),'submitted')
        with self.assertRaises(TrackerError):self.invoices.submit(self.users[0],ident,'b'*64)
        with self.assertRaises(TrackerError):self.invoices.cancel(self.users[0],ident)
        row=self.store.user_by_id(self.users[0])
        self.assertEqual(row['beta_access_kind'],'preview');self.assertFalse(row['beta_founder'])
        self.assertEqual(beta.occupied(self.store._db),2)

    def test_one_transfer_cannot_be_claimed_by_two_accounts(self):
        one=self.request();two=self.request(self.users[1]);self.quote(one);self.quote(two)
        self.invoices.submit(self.users[0],one,'a'*64)
        with self.assertRaises(TrackerError):self.invoices.submit(self.users[1],two,'a'*64)
        self.assertEqual(self.invoices.status(self.users[1],two)['state'],'quoted')

    def test_late_claim_is_retained_without_unlocking_or_silently_requoting(self):
        ident=self.request();self.quote(ident);self.now+=601
        self.invoices.status(self.users[0],ident)
        self.invoices.submit(self.users[0],ident,'b'*64)
        self.assertEqual(self.invoices.status(self.users[0],ident)['state'],'submitted')
        audit=self.store._db.execute("SELECT detail FROM beta_audit WHERE action='submit_payment_claim'").fetchone()
        self.assertEqual(audit[0],'late')
        self.assertEqual(self.store.user_by_id(self.users[0])['beta_access_kind'],'preview')

    def test_cancel_retry_and_beta_cutoff(self):
        ident=self.request();self.invoices.cancel(self.users[0],ident);self.invoices.cancel(self.users[0],ident)
        self.assertNotEqual(ident,self.request())
        self.now=terms.BETA_END
        with self.assertRaises(TrackerError):self.request(self.users[1])

    def test_backup_preserves_claim_and_exact_quote(self):
        ident=self.request();self.quote(ident);self.invoices.submit(self.users[0],ident,'d'*64)
        target=sqlite3.connect(self.tmp.name+'/recovered.sqlite3')
        self.store._db.backup(target)
        self.assertEqual(target.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        original=tuple(self.store._db.execute('SELECT * FROM beta_payment_requests WHERE id=?',(ident,)).fetchone())
        self.assertEqual(target.execute('SELECT * FROM beta_payment_requests WHERE id=?',(ident,)).fetchone(),original)
        target.close()

    def submitted(self):
        ident=self.request();quote=self.quote(ident)
        self.invoices.submit(self.users[0],ident,'e'*64)
        return ident,dict(evidence='synthetic wallet and explorer evidence only',
            delivered_base_units=quote['amount_base_units'],destination=quote['address'],memo=quote['memo'],received_at=self.now)

    def test_operator_approval_grants_founder_once(self):
        ident,review=self.submitted()
        with self.assertRaises(TrackerError):self.invoices.approve(self.users[1],ident,**review)
        first=self.invoices.approve(self.owner,ident,**review)
        self.assertFalse(first['reused'])
        member=self.store.user_by_id(self.users[0])
        self.assertEqual(member['beta_access_kind'],'paid_beta');self.assertTrue(member['beta_founder'])
        epoch=member['session_epoch']
        self.assertTrue(self.invoices.approve(self.owner,ident,**review)['reused'])
        self.assertEqual(self.store.user_by_id(self.users[0])['session_epoch'],epoch)
        self.assertEqual(self.store._db.execute('SELECT count(*) FROM beta_payment_receipts').fetchone()[0],1)

    def test_wrong_receipt_and_crash_cannot_partially_grant(self):
        ident,review=self.submitted()
        for change in ({'delivered_base_units':'1'},{'destination':'wrong'},{'memo':'wrong'},{'received_at':self.now+601}):
            with self.assertRaises(TrackerError):self.invoices.approve(self.owner,ident,**{**review,**change})
        original=beta.audit
        def crash(db,actor,action,*args):
            if action=='approve_invoice':raise RuntimeError('injected crash')
            return original(db,actor,action,*args)
        with patch('corner.beta_access.audit',side_effect=crash):
            with self.assertRaises(RuntimeError):self.invoices.approve(self.owner,ident,**review)
        self.assertEqual(self.store.user_by_id(self.users[0])['beta_access_kind'],'preview')
        self.assertEqual(self.store._db.execute('SELECT count(*) FROM beta_payment_receipts').fetchone()[0],0)
        self.assertEqual(self.invoices.status(self.users[0],ident)['state'],'submitted')
