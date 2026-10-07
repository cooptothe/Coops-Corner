"""Disposable HTTP/PostgreSQL acceptance for local account and past-activity records."""
import json
import secrets
import unittest
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from psycopg2 import sql
from acceptance.market_api import Harness, ROOT


class PersonalAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        def configure(h):
            with h.fixture.conn.cursor() as cur:
                cur.execute((ROOT/'db/migrations/014_personal_records.sql').read_text())
                # Test login has permissions on personal records only in addition
                # to the fixture's SELECT privileges, never on domain writes.
                cur.execute(sql.SQL('GRANT USAGE ON SCHEMA corner_app TO {}').format(sql.Identifier(h.role)))
                cur.execute(sql.SQL('GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA corner_app TO {}').format(sql.Identifier(h.role)))
                cur.execute(sql.SQL('GRANT UPDATE(id) ON corner_app.users TO {}').format(sql.Identifier(h.role)))
                cur.execute(sql.SQL('GRANT UPDATE ON corner_app.auth_limits TO {}').format(sql.Identifier(h.role)))
                cur.execute(sql.SQL('GRANT DELETE ON corner_app.sessions TO {}').format(sql.Identifier(h.role)))
            h.fixture.conn.commit()
            return {'CORNER_ACCOUNTS_ENABLED':'true','CORNER_ACCOUNTS_JDBC_URL':h.env['CORNER_MARKET_JDBC_URL'],
                    'CORNER_ACCOUNTS_DB_USER':h.role,'CORNER_ACCOUNTS_DB_PASSWORD':h.password}
        cls.h=Harness(configure=configure)
        cls.addClassCleanup(cls.h.close)
        cls.h.start()
        cls.password=secrets.token_urlsafe(24)
        cls.username='owner_'+uuid4().hex[:12]
        _,cls.owner,cls.cookie=cls.call('register',{'username':cls.username,'password':cls.password})
        _,cls.other,cls.other_cookie=cls.call('register',{'username':'other_'+uuid4().hex[:12],'password':secrets.token_urlsafe(24)})

    @classmethod
    def call(cls,path,body=None,cookie=None,csrf=None,origin='http://127.0.0.1:3000'):
        headers={'Origin':origin,'X-Corner-Request':'1'}
        if cookie: headers['Cookie']=cookie
        if csrf: headers['X-CSRF-Token']=csrf
        if body is not None: headers['Content-Type']='application/json'
        request=Request(f'http://127.0.0.1:{cls.h.port}/api/account/v1/'+path,
                        data=None if body is None else json.dumps(body).encode(),headers=headers)
        try: response=urlopen(request,timeout=15)
        except HTTPError as e: response=e
        with response:
            return response.status,json.load(response),response.headers.get('Set-Cookie','').split(';')[0]

    def record(self):
        placed=datetime.now(timezone.utc)-timedelta(days=3)
        settled=placed+timedelta(hours=3)
        return dict(request_key=str(uuid4()),description='Retrospective acceptance record',sportsbook='Manual book',
                    stake='10.00',returned='21.50',decimal_odds='2.15000000',placed_at=placed.isoformat().replace('+00:00','Z'),
                    settled_at=settled.isoformat().replace('+00:00','Z'))

    def test_01_authentication_and_hashes(self):
        self.assertEqual(401,self.call('records')[0])
        status,profile,cookie=self.call('login',{'username':self.username,'password':self.password})
        self.assertEqual(200,status); self.assertEqual(self.owner['id'],profile['id'])
        self.assertNotEqual(self.cookie,cookie)
        self.assertEqual(401,self.call('login',{'username':self.username,'password':'not-the-correct-password'})[0])
        with self.h.fixture.conn.cursor() as cur:
            cur.execute('SELECT password_hash FROM corner_app.users WHERE username=%s',(self.username,))
            stored=cur.fetchone()[0]
        self.assertTrue(stored.startswith('$2')); self.assertNotIn(self.password,stored)

    def test_02_origin_and_csrf(self):
        body=self.record()
        self.assertEqual(403,self.call('records',body,self.cookie,origin='https://outside.invalid')[0])
        self.assertEqual(403,self.call('records',body,self.cookie)[0])
        self.assertEqual(403,self.call('records',body,self.cookie,'incorrect')[0])

    def test_03_exact_money_and_idempotency(self):
        body=self.record()
        first=self.call('records',body,self.cookie,self.owner['csrf_token'])
        second=self.call('records',body,self.cookie,self.owner['csrf_token'])
        self.assertEqual(200,first[0]);self.assertEqual(first[1]['id'],second[1]['id'])
        self.assertTrue(second[1]['reused'])
        self.assertEqual(409,self.call('records',{**body,'returned':'22.00'},self.cookie,self.owner['csrf_token'])[0])
        dashboard=self.call('records',cookie=self.cookie)[1]
        row=next(r for r in dashboard['records'] if r['id']==first[1]['id'])
        self.assertEqual('10.00',row['stake']);self.assertEqual('21.50',row['returned'])

    def test_04_cross_user_isolation(self):
        own=self.call('records',self.record(),self.cookie,self.owner['csrf_token'])[1]
        other=self.call('records',cookie=self.other_cookie)[1]
        self.assertNotIn(own['id'],[r['id'] for r in other['records']])
        self.assertEqual('0',other['summary']['net_profit'])

    def test_05_no_future_or_malformed_records(self):
        body=self.record()
        for patch in ({'stake':'NaN'},{'returned':'-1'},{'stake':'1.001'},{'decimal_odds':'1'},
                      {'settled_at':'2099-01-01T00:00:00Z'},{'settled_at':'2000-01-01T00:00:00Z'}):
            self.assertEqual(400,self.call('records',{**body,**patch},self.cookie,self.owner['csrf_token'])[0],patch)

    def test_06_cash_and_summary(self):
        now=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat().replace('+00:00','Z')
        for kind,amount in [('deposit','100.00'),('withdrawal','20.00')]:
            status,_,_=self.call('cash',dict(request_key=str(uuid4()),kind=kind,amount=amount,note='Acceptance',occurred_at=now),self.other_cookie,self.other['csrf_token'])
            self.assertEqual(200,status)
        summary=self.call('records',cookie=self.other_cookie)[1]['summary']
        self.assertEqual('80.00',summary['recorded_balance'])

    def test_07_concurrent_duplicate_save(self):
        body=self.record()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.call('records',body,self.cookie,self.owner['csrf_token']),range(2)))
        self.assertEqual([200,200],[r[0] for r in results])
        self.assertEqual(results[0][1]['id'],results[1][1]['id'])
        self.assertEqual(1,sum(not r[1]['reused'] for r in results))

    def test_08_logout_revokes_session(self):
        _,p,cookie=self.call('login',{'username':self.username,'password':self.password})
        self.assertEqual(200,self.call('logout',{},cookie,p['csrf_token'])[0])
        self.assertEqual(401,self.call('session',cookie=cookie)[0])
        self.assertEqual(200,self.call('session',cookie=self.cookie)[0])

    def test_09_expired_session(self):
        with self.h.fixture.conn.cursor() as cur:
            cur.execute("UPDATE corner_app.sessions SET expires_at=clock_timestamp()-interval '1 second' WHERE user_id=%s",(self.other['id'],))
        self.h.fixture.conn.commit()
        self.assertEqual(401,self.call('session',cookie=self.other_cookie)[0])

    def test_10_throttle(self):
        for _ in range(21):
            result=self.call('login',{'username':self.username,'password':'wrong-but-long-password'})
            if result[0]==429: break
        self.assertEqual(429,result[0])


if __name__=='__main__':
    unittest.main(verbosity=2)
