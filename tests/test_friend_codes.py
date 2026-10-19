import unittest
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from tests import test_friend_membership as fixtures
from corner import beta_access as beta
from corner.tracker_store import TrackerError,TrackerStore

class FriendCodes(unittest.TestCase):
    setUp=fixtures.FriendMembership.setUp
    tearDown=fixtures.FriendMembership.tearDown
    tx=fixtures.FriendMembership.tx
    def codes(self,count=5):
        return self.tx(beta.issue_friend_codes,self.owner,count=count,evidence='Owner approved friends')

    def test_five_codes_reserve_only_friend_places_and_bind_first_username(self):
        codes=self.codes()
        self.assertEqual(len({token for _,token in codes}),5)
        self.assertTrue(all(token.startswith('FRIEND-') for _,token in codes))
        self.assertEqual(beta.occupied(self.store._db),0)
        self.assertEqual(beta.occupied(self.store._db,cohort='friend'),5)
        with self.assertRaises(TrackerError):self.codes(1)
        ident,code=codes[0]
        row=self.store._db.execute('SELECT * FROM beta_invites WHERE id=?',(ident,)).fetchone()
        self.assertNotIn(code,str(tuple(row)))
        user=self.store.create_user('Chosen','chosen','hash',code)
        self.assertEqual(user['cohort'],'friend')
        self.assertEqual(user['friend_rates']['standard_usd_cents'],2500)
        self.assertEqual(self.store._db.execute('SELECT username_key FROM beta_invites WHERE id=?',(ident,)).fetchone()[0],'chosen')
        with self.assertRaises(TrackerError):self.store.create_user('Other','other','hash',code)
        self.assertIsNone(self.store.user_by_key('other'))
        self.assertEqual(beta.occupied(self.store._db,cohort='friend'),5)

    def test_same_code_concurrently_creates_exactly_one_account(self):
        _,code=self.codes(1)[0]
        def redeem(index):
            store=TrackerStore(self.path)
            try:
                try:store.create_user('Choice'+str(index),'choice'+str(index),'hash',code);return True
                except TrackerError:return False
            finally:store.close()
        with ThreadPoolExecutor(max_workers=2) as pool:self.assertEqual(sum(pool.map(redeem,range(2))),1)
        self.assertEqual(beta.occupied(self.store._db,cohort='friend'),1)

    def test_expired_revoked_and_unbound_beta_codes_are_denied(self):
        codes=self.codes(2)
        self.tx(beta.revoke,self.owner,codes[0][0])
        self.store._db.execute('UPDATE beta_invites SET expires_at=0 WHERE id=?',(codes[1][0],))
        for index,(_,code) in enumerate(codes):
            with self.assertRaises(TrackerError):self.store.create_user('Denied'+str(index),'denied'+str(index),'hash',code)
        with self.assertRaises(TrackerError):self.tx(beta.issue,self.owner,'',access_kind='preview',cohort='beta',unbound=True,evidence='test')
        with self.assertRaises(TrackerError):self.tx(beta.issue,self.owner,'',access_kind='preview',cohort='friend',evidence='test')
        self.assertEqual(beta.occupied(self.store._db,cohort='friend'),0)

    def test_cli_displays_five_committed_codes_and_refuses_second_batch(self):
        args=[sys.executable,'-m','pipelines.beta_admin','--db',self.path,'--operator','owner','friend-codes','--count','5','--hours','168','--evidence','Synthetic CLI check']
        result=subprocess.run(args,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.count('Code (shown once): FRIEND-'),5)
        self.assertEqual(beta.occupied(self.store._db,cohort='friend'),5)
        second=subprocess.run(args,capture_output=True,text=True,timeout=20)
        self.assertNotEqual(second.returncode,0)
        self.assertNotIn('Code (shown once)',second.stdout)

if __name__=='__main__':unittest.main()
