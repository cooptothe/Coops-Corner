import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from corner import auth, beta_access as beta
from corner.tracker_store import TrackerStore, TrackerError, read_user
from pipelines.accounts import AuthContext, create_router


class PrivateBeta(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = self.tmp.name+'/accounts.sqlite3'
        self.store = TrackerStore(self.path)
        self.owner = self.store.create_user('Owner','owner',auth.hash_password('private-owner-pass'))
        self.tx(beta.bootstrap,'owner')
        self.flag = patch.dict(os.environ, {'CORNER_PRIVATE_BETA':'1'})
        self.flag.start()

    def tearDown(self):
        self.flag.stop()
        self.store.close()
        self.tmp.cleanup()

    def tx(self, fn, *args, **kwargs):
        with self.store._lock:
            self.store._db.execute('BEGIN IMMEDIATE')
            try:
                result=fn(self.store._db,*args,**kwargs)
                self.store._db.execute('COMMIT')
                return result
            except BaseException:
                self.store._db.execute('ROLLBACK')
                raise

    def invite(self,name,kind='preview'):
        return self.tx(beta.issue,self.owner['id'],name,access_kind=kind,evidence='fixture verification')

    def client(self):
        ctx=AuthContext(store=self.store,secret='s'*48,allowed_origins={'http://localhost:3000'})
        app=FastAPI();app.include_router(create_router(ctx))
        return TestClient(app,base_url='http://localhost:3000')

    def test_no_public_signup_and_failure_rolls_back_account(self):
        with self.assertRaises(TrackerError):
            self.store.create_user('Admin','admin','hash')
        self.assertIsNone(self.store.user_by_key('admin'))

    def test_hashed_identity_bound_single_use_and_no_client_role(self):
        ident,token=self.invite('alice')
        self.assertNotIn(token, str(self.store._db.execute('SELECT * FROM beta_invites').fetchall()))
        with self.assertRaises(TrackerError):
            self.store.create_user('Wrong','wrong','hash',token)
        alice=self.store.create_user('Alice','alice','hash',token)
        row=self.store.user_by_id(alice['id'])
        self.assertEqual((row['beta_role'],row['beta_state'],row['beta_founder']),('member','active',False))
        with self.assertRaises(TrackerError):
            beta.enroll(self.store._db,'fake','alice',token)
        self.assertEqual(beta.occupied(self.store._db),1)

    def test_expiration_revocation_and_duplicate_identity(self):
        ident,token=self.invite('alice')
        with self.assertRaises(TrackerError): self.invite('alice')
        self.tx(beta.revoke,self.owner['id'],ident)
        with self.assertRaises(TrackerError): self.store.create_user('Alice','alice','h',token)
        ident,token=self.invite('alice')
        self.store._db.execute('UPDATE beta_invites SET expires_at=0,non_expiring=0 WHERE id=?',(ident,))
        with self.assertRaises(TrackerError): self.store.create_user('Alice','alice','h',token)
        self.assertEqual(beta.occupied(self.store._db),0)

    def test_ten_reservations_across_independent_connections(self):
        owner=self.owner['id']
        def issue(i):
            store=TrackerStore(self.path)
            try:
                store._db.execute('BEGIN IMMEDIATE')
                try:
                    beta.issue(store._db,owner,f'member{i}',access_kind='preview',evidence='fixture')
                    store._db.execute('COMMIT');return True
                except TrackerError:
                    store._db.execute('ROLLBACK');return False
            finally: store.close()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(issue,range(14)))
        self.assertEqual(sum(results),10)
        self.assertEqual(beta.occupied(self.store._db),10)

    def test_suspension_revokes_readonly_api_session_and_keeps_seat(self):
        _,token=self.invite('alice')
        u=self.store.create_user('Alice','alice','hash',token)
        jwt=auth.issue_token('s'*48,u['id'],'Alice')
        lookup=lambda uid:read_user(self.path,uid)
        self.assertIsNotNone(auth.session_user('s'*48,jwt,lookup))
        self.tx(beta.state,self.owner['id'],'alice','suspended')
        self.assertIsNone(auth.session_user('s'*48,jwt,lookup))
        self.assertEqual(beta.occupied(self.store._db),1)
        self.tx(beta.state,self.owner['id'],'alice','active')
        self.assertIsNone(auth.session_user('s'*48,jwt,lookup))
        self.tx(beta.state,self.owner['id'],'alice','closed')
        self.assertEqual(beta.occupied(self.store._db),0)

    def test_operator_explicit_not_username_and_excluded_from_capacity(self):
        self.assertEqual(beta.occupied(self.store._db),0)
        _,token=self.invite('admin')
        user=self.store.create_user('Admin','admin','hash',token)
        with self.assertRaises(TrackerError): self.tx(beta.require_operator,user['id'])
        with self.assertRaises(TrackerError): self.tx(beta.bootstrap,'admin')
        with self.assertRaises(TrackerError): self.tx(beta.state,self.owner['id'],'owner','closed')

    def test_existing_unenrolled_login_denied_then_grant_preserves_account(self):
        with patch.dict(os.environ,{'CORNER_PRIVATE_BETA':'0'}):
            u=self.store.create_user('Legacy','legacy',auth.hash_password('old-private-pass'))
        client=self.client()
        response=client.post('/api/refresh/v1/auth/login',headers={'Origin':'http://localhost:3000'},json={'username':'Legacy','password':'old-private-pass'})
        self.assertEqual(response.status_code,403)
        self.tx(beta.grant,self.owner['id'],'legacy','preview','existing staging user')
        response=client.post('/api/refresh/v1/auth/login',headers={'Origin':'http://localhost:3000'},json={'username':'Legacy','password':'old-private-pass'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['user']['id'],u['id'])

    def test_http_signup_invite_replay_and_suspension(self):
        client=self.client(); headers={'Origin':'http://localhost:3000'}
        body={'username':'Alice','password':'private-alice-pass','role':'admin'}
        self.assertEqual(client.post('/api/refresh/v1/auth/register',headers=headers,json=body).status_code,403)
        _,body['invite']=self.invite('alice','paid_beta')
        self.assertEqual(client.post('/api/refresh/v1/auth/register',headers=headers,json=body).status_code,200)
        response=client.get('/api/refresh/v1/auth/me')
        self.assertEqual(response.json()['user']['role'],'member')
        self.assertTrue(response.json()['user']['founder'])
        self.tx(beta.state,self.owner['id'],'alice','suspended')
        self.assertEqual(client.get('/api/refresh/v1/auth/me').status_code,401)

    def test_logout_all_revokes_copied_token_and_wrong_origin_is_denied(self):
        _,invite=self.invite('alice')
        u=self.store.create_user('Alice','alice',auth.hash_password('private-alice-pass'),invite)
        token=auth.issue_token('s'*48,u['id'],'Alice')
        client=self.client()
        client.cookies.set('corner_session',token)
        self.assertEqual(client.post('/api/refresh/v1/auth/logout-all',headers={'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(client.get('/api/refresh/v1/auth/me').status_code,200)
        self.assertEqual(client.post('/api/refresh/v1/auth/logout-all',headers={'Origin':'http://localhost:3000'}).status_code,200)
        self.assertIsNone(auth.session_user('s'*48,token,lambda uid:read_user(self.path,uid)))


if __name__=='__main__': unittest.main()
