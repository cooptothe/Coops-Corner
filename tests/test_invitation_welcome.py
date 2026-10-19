import unittest
from tests import test_friend_membership as fixtures
from corner import beta_access as beta,invitation_welcome as welcome,beta_terms
from corner.tracker_store import TrackerError
from pipelines.accounts import AuthContext
from pipelines.invitation_service import create_router
from fastapi import FastAPI
from fastapi.testclient import TestClient

class Welcome(unittest.TestCase):
    setUp=fixtures.FriendMembership.setUp
    tearDown=fixtures.FriendMembership.tearDown
    tx=fixtures.FriendMembership.tx
    def code(self,cohort='friend',kind='preview'):
        return self.tx(beta.issue,self.owner,'chosen',access_kind=kind,cohort=cohort,evidence='Synthetic invitation')
    def agreement(self,code):
        return self.tx(welcome.accept,code,dict(version=welcome.VERSION,terms_version=beta_terms.VERSION,eligible=True,agree=True))
    def test_preview_correct_terms_no_redemption_and_existing_link_no_extra_seat(self):
        ident,code=self.code()
        before=beta.occupied(self.store._db,cohort='friend')
        link=self.tx(welcome.wrap,self.owner,code)
        self.assertEqual(link,'https://coopscorner.tech/invite#'+code)
        offer=welcome.offer(self.store._db,code)
        self.assertIn('$25/month',offer['pricing'])
        self.assertIn('Complimentary',offer['access'])
        self.assertEqual(beta.occupied(self.store._db,cohort='friend'),before)
        self.assertIsNone(self.store._db.execute('SELECT redeemed_by FROM beta_invites WHERE id=?',(ident,)).fetchone()[0])
        self.assertNotIn(code,str(tuple(self.store._db.execute('SELECT * FROM beta_invites').fetchone())))
        with self.assertRaises(TrackerError):self.store.create_user('Chosen','chosen','hash',code)
        with self.assertRaises(TrackerError):self.tx(welcome.accept,code,dict(version='old',terms_version=beta_terms.VERSION,eligible=True,agree=True))
        self.agreement(code)
        user=self.store.create_user('Chosen','chosen','hash',code)
        self.assertEqual(user['cohort'],'friend')
        with self.assertRaises(TrackerError):welcome.offer(self.store._db,code)
        self.assertEqual(welcome.offer(self.store._db,code,user)['cohort'],'friend')
    def test_beta_and_paid_offers(self):
        _,code=self.code('beta')
        self.assertIn('Seven days',welcome.offer(self.store._db,code)['access'])
        self.assertIn('$125/month',welcome.offer(self.store._db,code)['pricing'])
        self.tx(beta.revoke,self.owner,self.store._db.execute('SELECT id FROM beta_invites').fetchone()[0])
        _,paid=self.code('beta','paid_beta')
        self.assertIn('verified paid',welcome.offer(self.store._db,paid)['access'])
        self.assertNotIn('$125',welcome.offer(self.store._db,paid)['pricing'])
    def test_feedback_claim_ownership_rate_and_bounds(self):
        _,code=self.code()
        body=dict(category='bug',title='Mobile control',message='Props / Safari. Filter clipped.')
        self.tx(welcome.feedback,code,body,None)
        self.tx(welcome.wrap,self.owner,code);self.agreement(code)
        user=self.store.create_user('Chosen','chosen','hash',code)
        with self.assertRaises(TrackerError):self.tx(welcome.feedback,code,body,None)
        with self.assertRaises(TrackerError):self.tx(welcome.feedback,code,body,{'id':self.owner})
        for _ in range(4):self.tx(welcome.feedback,code,body,user)
        with self.assertRaises(TrackerError):self.tx(welcome.feedback,code,body,user)
    def test_http_origin_body_limits_and_invalid_codes(self):
        _,code=self.code()
        app=FastAPI();app.include_router(create_router(AuthContext(self.store,'x'*64,{'http://localhost:3000'})))
        with TestClient(app,base_url='http://127.0.0.1') as client:
            path='/api/refresh/v1/invitations/preview'
            self.assertEqual(client.post(path,json={'token':code}).status_code,403)
            headers={'Origin':'http://localhost:3000'}
            result=client.post(path,json={'token':code},headers=headers)
            self.assertEqual(result.status_code,200)
            self.assertEqual(result.headers['cache-control'],'no-store')
            self.assertEqual(client.post(path,content='x'*12001,headers=headers).status_code,413)
            self.assertEqual(client.post(path,json={'token':'bad'},headers=headers).status_code,404)
            self.assertEqual(client.post(path,json={'token':code,'cohort':'beta'},headers=headers).status_code,400)
    def test_prepare_friends_cli_creates_only_five_and_requires_saved_codes_on_repeat(self):
        import subprocess,sys
        args=[sys.executable,'-m','pipelines.invitation_admin','--db',self.path,'--operator','owner','friends']
        result=subprocess.run(args,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.count('https://coopscorner.tech/invite#'),5)
        self.assertEqual(beta.occupied(self.store._db,cohort='friend'),5)
        self.assertEqual(self.store._db.execute('SELECT count(*) FROM beta_invitation_pages').fetchone()[0],5)

    def test_expired_and_revoked(self):
        ident,code=self.code()
        self.store._db.execute('UPDATE beta_invites SET expires_at=0 WHERE id=?',(ident,))
        with self.assertRaises(TrackerError):welcome.offer(self.store._db,code)
        with self.assertRaises(TrackerError):self.tx(welcome.feedback,code,dict(category='bug',title='t',message='m'),None)

if __name__=='__main__':unittest.main()
