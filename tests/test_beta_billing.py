"""Offline payment-record integrity; synthetic evidence never verifies a chain."""
import os
import tempfile
import unittest
from unittest.mock import patch
from corner import beta_access as beta
from corner.beta_billing import BetaBilling
from corner.tracker_store import TrackerStore, TrackerError


def receipt(tx='synthetic-transfer-001'):
    return dict(network='xrpl-mainnet', asset_id='XRP', transaction_id=tx,
                transfer_index=0, destination='fixture-wallet-with-required-tag',
                amount_base_units='123456789', usd_cents=5000, settled=True,
                quote_id='fixture-quote', quote_evidence='fixture $50 conversion, not a real rate',
                terms_version='unapproved-fixture-terms', settlement_evidence='synthetic fixture only')


class Billing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TrackerStore(self.tmp.name+'/accounts.sqlite3')
        self.owner = self.store.create_user('Owner', 'owner', 'fixture-hash')['id']
        beta.bootstrap(self.store._db, 'owner')
        self.billing = BetaBilling(self.store)
        self.flag = patch.dict(os.environ, {'CORNER_PRIVATE_BETA':'1'})
        self.flag.start()

    def tearDown(self):
        self.flag.stop()
        self.store.close()
        self.tmp.cleanup()

    def test_record_does_not_grant_and_same_receipt_cannot_pay_twice(self):
        ident = self.billing.verify(self.owner, 'Alice', receipt())
        self.assertEqual(beta.occupied(self.store._db), 0)
        self.assertEqual(ident, self.billing.verify(self.owner, 'alice', receipt()))
        with self.assertRaises(TrackerError):
            self.billing.verify(self.owner, 'other', receipt())
        with self.assertRaises(TrackerError):
            self.billing.verify(self.owner, 'alice', {**receipt(), 'amount_base_units':'42'})
        result = self.billing.fulfill(self.owner, ident)
        self.assertTrue(result['invitation_code'])
        again = self.billing.fulfill(self.owner, ident)
        self.assertTrue(again['reused'])
        self.assertIsNone(again['invitation_code'])
        self.assertEqual(beta.occupied(self.store._db), 1)
        user = self.store.create_user('Alice', 'alice', 'fixture-hash', result['invitation_code'])
        member = self.store.user_by_id(user['id'])
        self.assertEqual(member['beta_access_kind'], 'paid_beta')
        self.assertTrue(member['beta_founder'])

    def test_preview_upgrade_preserves_seat_and_revokes_sessions(self):
        _, token = beta.issue(self.store._db, self.owner, 'alice', access_kind='preview', evidence='fixture')
        user = self.store.create_user('Alice','alice','fixture-hash',token)
        before = self.store.user_by_id(user['id'])['session_epoch']
        ident = self.billing.verify(self.owner, 'alice', receipt())
        self.billing.fulfill(self.owner, ident)
        self.assertEqual(beta.occupied(self.store._db), 1)
        self.assertEqual(self.store.user_by_id(user['id'])['session_epoch'], before+1)

    def test_full_capacity_rolls_back_fulfillment(self):
        for i in range(10):
            beta.issue(self.store._db, self.owner, f'user{i}', access_kind='preview', evidence='fixture')
        ident = self.billing.verify(self.owner, 'alice', receipt())
        with self.assertRaises(TrackerError):
            self.billing.fulfill(self.owner, ident)
        row = self.store._db.execute('SELECT state FROM beta_payment_receipts WHERE id=?',(ident,)).fetchone()
        self.assertEqual(row[0], 'verified')
        self.assertEqual(beta.occupied(self.store._db), 10)

    def test_nonoperator_and_unsettled_or_rounded_claims_are_rejected(self):
        with self.assertRaises(TrackerError):
            self.billing.verify('not-an-operator', 'alice', receipt())
        for field, value in [('settled', False), ('usd_cents', 5000.0),
                             ('amount_base_units','1.234'), ('amount_base_units','0'),
                             ('transfer_index',True), ('settlement_evidence',''),
                             ('asset_id','ONDO'), ('network','stellar-mainnet')]:
            with self.subTest(field=field), self.assertRaises(TrackerError):
                self.billing.verify(self.owner, 'alice', {**receipt(), field:value})

    def test_case_variants_and_concurrent_connections_cannot_duplicate_receipt(self):
        from concurrent.futures import ThreadPoolExecutor
        def record():
            store = TrackerStore(self.tmp.name+'/accounts.sqlite3')
            try:
                return BetaBilling(store).verify(self.owner, 'alice', receipt())
            finally:
                store.close()
        with ThreadPoolExecutor(max_workers=2) as workers:
            identifiers = list(workers.map(lambda _: record(), range(2)))
        self.assertEqual(identifiers[0], identifiers[1])
        same = self.billing.verify(self.owner, 'alice', {**receipt(), 'transaction_id':receipt()['transaction_id'].upper()})
        self.assertEqual(same, identifiers[0])

    def test_crash_after_invite_creation_rolls_back_both_grant_and_receipt_state(self):
        ident = self.billing.verify(self.owner, 'alice', receipt())
        issue = beta.issue
        def crash(*args, **kwargs):
            issue(*args, **kwargs)
            raise RuntimeError('simulated crash before receipt update')
        with patch.object(beta, 'issue', side_effect=crash), self.assertRaises(RuntimeError):
            self.billing.fulfill(self.owner, ident)
        self.assertEqual(beta.occupied(self.store._db), 0)
        self.assertEqual(self.store._db.execute('SELECT state FROM beta_payment_receipts WHERE id=?',(ident,)).fetchone()[0], 'verified')
        self.assertTrue(self.billing.fulfill(self.owner, ident)['invitation_code'])

    def test_account_backup_preserves_receipt_and_replay_identity(self):
        import sqlite3
        from contextlib import closing
        ident = self.billing.verify(self.owner, 'alice', receipt())
        self.billing.fulfill(self.owner, ident)
        copy_path = self.tmp.name+'/recovered.sqlite3'
        with closing(sqlite3.connect(copy_path)) as recovered:
            self.store._db.backup(recovered)
            self.assertEqual(recovered.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
        store = TrackerStore(copy_path)
        try:
            billing = BetaBilling(store)
            self.assertEqual(billing.verify(self.owner, 'alice', receipt()), ident)
            self.assertTrue(billing.fulfill(self.owner, ident)['reused'])
            self.assertEqual(beta.occupied(store._db), 1)
        finally:
            store.close()
