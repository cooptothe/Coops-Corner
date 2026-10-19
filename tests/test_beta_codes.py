import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from tests import test_friend_membership as fixtures
from corner import beta_access as beta,invitation_welcome as welcome,beta_terms
from corner.tracker_store import TrackerStore,TrackerError

class BetaCodes(unittest.TestCase):
    setUp=fixtures.FriendMembership.setUp
    tearDown=fixtures.FriendMembership.tearDown
    tx=fixtures.FriendMembership.tx
    def codes(self,count=1):
        return self.tx(beta.issue_beta_codes,self.owner,count=count,evidence='Owner-approved test beta trial')
    def test_capacity_and_username_binding(self):
        codes=self.codes(10)
        self.assertEqual(beta.occupied(self.store._db),10)
        self.assertEqual(beta.occupied(self.store._db,cohort='friend'),0)
        with self.assertRaises(TrackerError):self.codes()
        ident,code=codes[0]
        self.assertTrue(code.startswith('BETA-'))
        self.assertNotIn(code,str(tuple(self.store._db.execute('SELECT * FROM beta_invites WHERE id=?',(ident,)).fetchone())))
        user=self.store.create_user('MyOwnName','myownname','hash',code)
        self.assertEqual(user['cohort'],'beta')
        self.assertFalse(user['founder'])
        self.assertEqual(self.store._db.execute('SELECT username_key FROM beta_invites WHERE id=?',(ident,)).fetchone()[0],'myownname')
        with self.assertRaises(TrackerError):self.store.create_user('Another','another','hash',code)
        self.assertIsNone(self.store.user_by_key('another'))
    def test_first_successful_signup_wins(self):
        _,code=self.codes()[0]
        def signup(index):
            store=TrackerStore(self.path)
            try:
                try:store.create_user('User'+str(index),'user'+str(index),'hash',code);return True
                except TrackerError:return False
            finally:store.close()
        with ThreadPoolExecutor(max_workers=2) as pool:self.assertEqual(sum(pool.map(signup,range(2))),1)
    def test_partial_batch_is_not_issued_and_named_codes_still_match(self):
        self.codes(9)
        with self.assertRaises(TrackerError):self.codes(2)
        self.assertEqual(beta.occupied(self.store._db),9)
        _,named=self.tx(beta.issue,self.owner,'intended',access_kind='preview',evidence='Existing named invite')
        with self.assertRaises(TrackerError):self.store.create_user('Wrong','wrong','hash',named)
        self.store.create_user('Intended','intended','hash',named)
    def test_prepare_only_remaining_seats_and_welcome_required(self):
        _,existing=self.tx(beta.issue,self.owner,'existing',access_kind='preview',evidence='Existing beta')
        self.store.create_user('Existing','existing','hash',existing)
        result=subprocess.run([sys.executable,'-m','pipelines.invitation_admin','--db',self.path,'--operator','owner','betas'],capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.count('https://coopscorner.tech/invite#'),9)
        self.assertEqual(beta.occupied(self.store._db),10)
        code=result.stdout.split('/invite#')[1].split()[0]
        with self.assertRaises(TrackerError):self.store.create_user('Chosen','chosen','hash',code)
        self.tx(welcome.accept,code,dict(version=welcome.VERSION,terms_version=beta_terms.VERSION,eligible=True,agree=True))
        self.store.create_user('Chosen','chosen','hash',code)
    def test_optional_username_cli(self):
        args=[sys.executable,'-m','pipelines.beta_admin','--db',self.path,'--operator','owner','invite','--kind','preview','--evidence','Owner-approved trial']
        result=subprocess.run(args,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('/invite#BETA-',result.stdout)
        self.assertEqual(beta.occupied(self.store._db),1)

if __name__=='__main__':unittest.main()
