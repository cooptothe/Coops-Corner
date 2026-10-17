import os
import tempfile
import unittest
from unittest.mock import patch
from starlette.requests import Request
from corner import auth, beta_access as beta, beta_terms
from corner.tracker_store import TrackerStore, TrackerError
from pipelines.accounts import AuthContext


class TrialEnforcement(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TrackerStore(self.tmp.name + '/accounts.sqlite3')
        self.owner = self.store.create_user('Owner', 'owner', 'hash')
        beta.bootstrap(self.store._db, 'owner')
        self.flags = patch.dict(os.environ, {'CORNER_PRIVATE_BETA': '1', 'CORNER_BETA_TRIALS': '0'})
        self.flags.start()
        _, token = beta.issue(self.store._db, self.owner['id'], 'alice', access_kind='preview', evidence='test')
        self.alice = self.store.create_user('Alice', 'alice', 'hash', token)

    def tearDown(self):
        self.flags.stop()
        self.store.close()
        self.tmp.cleanup()

    def row(self):
        return self.store.user_by_id(self.alice['id'])

    def test_disabled_preserves_preview_and_explicit_start_does_not_reset(self):
        self.assertTrue(beta.access_status(self.row())['allowed'])
        with patch('corner.beta_access.time.time', return_value=1792000000):
            first = beta.start_trial(self.store._db, self.owner['id'], 'alice')
        with patch('corner.beta_access.time.time', return_value=1792100000):
            self.assertEqual(beta.start_trial(self.store._db, self.owner['id'], 'alice'), first)
        with patch.dict(os.environ, {'CORNER_BETA_TRIALS': '1'}):
            self.assertTrue(beta.access_status(self.row(), first + 172799)['allowed'])
            self.assertFalse(beta.access_status(self.row(), first + 172800)['allowed'])
            self.assertFalse(beta.access_status(self.row(), first - 1)['allowed'])
        with self.assertRaises(TrackerError):
            beta.start_trial(self.store._db, self.alice['id'], 'alice')

    def test_existing_preview_fails_closed_until_started_but_account_remains(self):
        with patch.dict(os.environ, {'CORNER_BETA_TRIALS': '1'}):
            row = self.row()
            self.assertEqual(beta.access_status(row)['state'], 'not_started')
            secret = 's' * 48
            token = auth.issue_token(secret, row['id'], row['username'], epoch=row['session_epoch'])
            self.assertIsNone(auth.session_user(secret, token, self.store.user_by_id))
            self.assertIsNotNone(auth.session_user(secret, token, self.store.user_by_id, member_access_required=False))
            ctx = AuthContext(self.store, secret)
            for path, allowed in [('/api/refresh/v1/billing/status', True), ('/api/refresh/v1/auth/me', True), ('/api/refresh/v1/tracker/bets', True), ('/api/refresh/v1/props', False), ('/api/refresh/v1/tracker-exploit', False)]:
                request = Request({'type': 'http', 'method': 'GET', 'path': path, 'headers': [(b'host', b'localhost'), (b'cookie', ('corner_session=' + token).encode())]})
                _, denied = ctx.require(request, write=False)
                self.assertEqual(denied is None, allowed, path)

    def test_new_enrollment_starts_once_and_late_enrollment_rolls_back(self):
        with patch.dict(os.environ, {'CORNER_BETA_TRIALS': '1'}):
            _, token = beta.issue(self.store._db, self.owner['id'], 'bob', access_kind='preview', evidence='test')
            bob = self.store.create_user('Bob', 'bob', 'hash', token)
            self.assertEqual(self.store.user_by_id(bob['id'])['beta_trial_started_at'] is not None, True)
            with patch('corner.beta_access.time.time', return_value=beta_terms.BETA_END - 3600):
                _, late = beta.issue(self.store._db, self.owner['id'], 'late', access_kind='preview', evidence='test')
                with self.assertRaises(TrackerError):
                    self.store.create_user('Late', 'late', 'hash', late)
                self.assertIsNone(self.store.user_by_key('late'))

    def test_paid_cutoff_operator_and_suspension(self):
        with patch.dict(os.environ, {'CORNER_BETA_TRIALS': '1'}):
            self.store._db.execute("UPDATE beta_members SET access_kind='paid_beta' WHERE user_id=?", (self.alice['id'],))
            self.assertTrue(beta.access_status(self.row(), beta_terms.BETA_END - 1)['allowed'])
            self.assertFalse(beta.access_status(self.row(), beta_terms.BETA_END)['allowed'])
            self.assertTrue(beta.access_status(self.store.user_by_id(self.owner['id']), beta_terms.BETA_END + 1)['allowed'])
            beta.state(self.store._db, self.owner['id'], 'alice', 'suspended')
            self.assertFalse(beta.access_status(self.row())['allowed'])
