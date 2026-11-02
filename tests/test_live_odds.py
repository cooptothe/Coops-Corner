from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from corner.collection_policy import Job, STANDARD, EXCHANGE, parse, interval, POOLS, TOTAL, PROTECTED
from corner.credit_governor import Governor, Refused
from corner.live_odds import active_market, feed, jobs, premium
from corner.live_tools import opportunities
from pipelines.live_odds_client import fetch
from pipelines.live_odds_service import create_router

NOW=parse('2026-10-22T18:00:00Z')
def event(books=None):
    return {'id':'live-one','sport_key':'basketball_nba','home_team':'Home','away_team':'Away',
        'commence_time':(NOW-timedelta(hours=1)).isoformat(),'bookmakers':books or []}
def block(key='h2h', price=2):
    return {'key':key,'last_update':NOW.isoformat(),'outcomes':[
        {'name':'Home' if key!='totals' else 'Over','price':price,**({'point':-3.5 if key=='spreads' else 200.5} if key!='h2h' else {})},
        {'name':'Away' if key!='totals' else 'Under','price':2,**({'point':3.5 if key=='spreads' else 200.5} if key!='h2h' else {})}]}

class LiveData(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'simulation.sqlite3'
        self.g=Governor(self.path)
        self.g.configure_cycle('simulation-oct',parse('2026-10-01T00:00:00Z'),parse('2026-11-01T00:00:00Z'))
    def tearDown(self): self.g.close();self.temp.cleanup()
    def publish(self,group,payload):
        books=STANDARD if group=='standard' else EXCHANGE
        with self.g.transaction() as db:
            from corner.live_odds import store
            store(db,Job('live','basketball_nba',group,books,('h2h','spreads','totals')),payload,NOW)
    def test_no_books_or_empty_markets_in_fresh_groups_infers_suspension(self):
        self.publish('standard',[event([{'key':'draftkings','markets':[]}])]);self.publish('exchange',[])
        item=feed(self.path,NOW)['events'][0]
        self.assertTrue(item['is_suspended']);self.assertFalse(item['game_stoppage_confirmed'])
        self.assertEqual(item['active_market_count'],0)
    def test_valid_book_counts_and_market_source_staleness(self):
        e=event([{'key':'draftkings','markets':[block(),block('totals')]}])
        self.publish('standard',[e]);self.publish('exchange',[])
        item=feed(self.path,NOW)['events'][0]
        self.assertFalse(item['is_suspended']);self.assertEqual(item['active_market_count'],2)
        stale=feed(self.path,NOW+timedelta(seconds=91))['events'][0]
        self.assertIsNone(stale['is_suspended']);self.assertEqual(stale['status'],'unknown');self.assertEqual(stale['opportunities'],[])
    def test_missing_capture_is_unknown_not_suspension(self):
        self.publish('standard',[event()])
        self.assertIsNone(feed(self.path,NOW)['events'][0]['is_suspended'])
    def test_paused_collector_invalidates_cached_live_lines(self):
        self.publish('standard',[event([{'key':'draftkings','markets':[block()]}])]);self.publish('exchange',[])
        self.g.db.execute("UPDATE controls SET paused='operator review'")
        item=feed(self.path,NOW)['events'][0]
        self.assertIsNone(item['is_suspended']);self.assertEqual(item['opportunities'],[])
    def test_price_validity_source_time_and_complete_outcomes(self):
        for bad in ('missing_price','locked','stale','incomplete','spread_pair','future'):
            m=block('spreads')
            if bad=='missing_price': del m['outcomes'][0]['price']
            if bad=='locked': m['suspended']=True
            if bad=='stale': m['last_update']=(NOW-timedelta(seconds=91)).isoformat()
            if bad=='incomplete': m['outcomes'].pop()
            if bad=='spread_pair': m['outcomes'][1]['point']=4
            if bad=='future': m['last_update']=(NOW+timedelta(seconds=6)).isoformat()
            self.assertFalse(active_market(m,event(),NOW),bad)
        self.assertTrue(active_market(block(),event(),NOW))
    def test_live_planner_is_opt_in_in_play_only_and_main_lines(self):
        inventory={'live_events':[event()]}
        with patch('corner.live_odds.enabled',return_value=False): self.assertEqual(jobs(NOW,inventory),[])
        with patch('corner.live_odds.enabled',return_value=True):
            planned=jobs(NOW,inventory)
        self.assertEqual(len(planned),2)
        for job in planned:
            job.validate();self.assertEqual(job.pool,'main');self.assertEqual(job.cost,3)
            self.assertEqual(job.markets,('h2h','spreads','totals'))
            self.assertEqual(interval('live',job.group,NOW),40 if job.group=='standard' else 10)
    def test_live_subcap_reservations_and_provider_standard_floor(self):
        self.assertEqual(sum(POOLS.values())+PROTECTED,TOTAL)
        job=Job('live','basketball_nba','standard',STANDARD,('h2h','spreads','totals'))
        self.g.acquire('worker',NOW)
        with patch('corner.live_odds.enabled',return_value=True),patch('corner.live_odds.MONTHLY_CAP',3):
            token=self.g.claim(job,'worker',NOW)
            self.g.finish(job,token,'worker',NOW,{'x-requests-last':'3','x-requests-remaining':'14999997'},[])
            self.assertFalse(self.g.ready(job,NOW+timedelta(seconds=39)))
            self.assertTrue(self.g.ready(job,NOW+timedelta(seconds=40)))
            self.g.prepare_due(job,'worker',NOW+timedelta(seconds=60))
            with self.assertRaisesRegex(Refused,'sub-limit'): self.g.claim(job,'worker',NOW+timedelta(seconds=60))
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM snapshots').fetchone()[0],0)
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM publication_outbox').fetchone()[0],0)
    def test_daily_subcap_covers_both_book_groups_and_held_reservations(self):
        first=Job('live','basketball_nba','standard',STANDARD,('h2h','spreads','totals'))
        second=Job('live','basketball_nba','exchange',EXCHANGE,('h2h','spreads','totals'))
        self.g.acquire('worker',NOW)
        with patch('corner.live_odds.enabled',return_value=True),patch('corner.live_odds.DAILY_CAP',3):
            self.g.claim(first,'worker',NOW)
            with self.assertRaisesRegex(Refused,'sub-limit'): self.g.claim(second,'worker',NOW)
        self.assertEqual(self.g.db.execute('SELECT sum(reserved) FROM attempts').fetchone()[0],3)

    def test_captures_replace_empty_scope_and_never_touch_pregame(self):
        self.publish('standard',[event()]);self.publish('standard',[])
        self.assertEqual(feed(self.path,NOW)['events'],[])
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM snapshots').fetchone()[0],0)

class LiveTransport(unittest.TestCase):
    def test_httpx_quota_headers_and_no_retry(self):
        calls=[]
        def handler(request):
            calls.append(request)
            return httpx.Response(200,json=[],headers={'x-requests-last':'0','x-requests-used':'3','x-requests-remaining':'14999997'})
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            status,data,headers=fetch(client,'/basketball_nba/odds',{'markets':'h2h'},'private-key')
        self.assertEqual(status,200);self.assertEqual(headers['x-requests-last'],'0');self.assertEqual(len(calls),1)
    def test_transport_failure_is_sanitized(self):
        def handler(request): raise httpx.ReadTimeout('secret apiKey=private-key')
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaisesRegex(RuntimeError,'quota reservation') as result: fetch(client,'/basketball_nba/odds',{},'private-key')
        self.assertNotIn('private-key',str(result.exception))

class LiveCalculations(unittest.TestCase):
    def test_reuses_devig_and_arb_and_does_not_claim_execution(self):
        books=[]
        for book,price in [('pinnacle',2),('fanduel',2),('draftkings',2.2)]:
            m=block();m['outcomes'][0]['price']=price;books.append({'key':book,'markets':[m]})
        items=opportunities(event(books))
        self.assertTrue(any(i['kind']=='ev' and i['book']=='draftkings' for i in items))
        self.assertTrue(any(i['kind']=='arbitrage' for i in items))
        self.assertTrue(all(not i['game_state_verified'] for i in items))
        books[0]['markets'][0]['last_update']=(NOW-timedelta(seconds=20)).isoformat()
        books[1]['markets'][0]['last_update']=(NOW-timedelta(seconds=20)).isoformat()
        self.assertEqual(opportunities(event(books)),[])

class Context:
    def __init__(self,user): self.identity=user
    def require(self,request,write=False):
        from pipelines.accounts import reply
        return (self.identity,None) if self.identity else (None,reply(401,{'error':'Sign in'}))

class LiveRoutes(unittest.TestCase):
    def client(self,user,host='127.0.0.1'):
        app=FastAPI();app.include_router(create_router(Context(user),path=Path('missing-live-db')))
        return TestClient(app,client=(host,40000),base_url='http://127.0.0.1')
    def test_owner_and_database_friend_cohort_are_premium_server_side(self):
        self.assertTrue(premium({'username':'Wonya'}));self.assertFalse(premium({'username':'admin'}))
        self.assertTrue(premium({'username':'friend-user','cohort':'friend'}))
        self.assertFalse(premium({'username':'member','cohort':'beta'}))
        self.assertEqual(self.client({'username':'friend-user','cohort':'friend'}).get('/api/v1/live-stoppages').status_code,200)
        self.assertEqual(self.client({'username':'other'}).get('/api/v1/live-stoppages?cohort=friend&premium=true').status_code,403)
        self.assertEqual(self.client(None).get('/api/v1/live-stoppages').status_code,401)
        self.assertEqual(self.client({'username':'other'}).get('/api/v1/live-stoppages?username=wonya').status_code,403)
        self.assertEqual(self.client({'username':'wonya'}).get('/api/v1/live-stoppages').status_code,200)
    def test_cron_is_authenticated_loopback_only_and_only_queues(self):
        token='x'*48
        with patch('corner.live_odds.config',return_value={'enabled':True,'cron_token':token}),patch('corner.live_odds.request_refresh') as queued:
            client=self.client(None)
            self.assertEqual(client.post('/api/v1/cron/refresh-live-odds',json={}).status_code,403)
            response=client.post('/api/v1/cron/refresh-live-odds',json={},headers={'Authorization':'Bearer '+token})
            self.assertEqual(response.status_code,202);queued.assert_called_once();self.assertEqual(response.json()['provider_calls'],0)
            self.assertEqual(client.post('/api/v1/cron/refresh-live-odds',json={},headers={'Authorization':'Bearer '+token,'X-Forwarded-For':'1.2.3.4'}).status_code,403)
            self.assertEqual(self.client(None,'1.2.3.4').post('/api/v1/cron/refresh-live-odds',json={},headers={'Authorization':'Bearer '+token}).status_code,403)

class LiveProductionBoundary(unittest.TestCase):
    def test_session_gate_bypasses_only_the_token_protected_cron_route(self):
        from api.app import create_app
        token='z'*48
        app=create_app(session_check=lambda token: token=='signed-session')
        client=TestClient(app,client=('127.0.0.1',40000),base_url='http://127.0.0.1')
        self.assertEqual(client.get('/api/v1/live-stoppages').status_code,401)
        self.assertEqual(client.post('/api/v1/cron/refresh-live-odds',json={}).status_code,403)
        with patch('corner.live_odds.config',return_value={'enabled':True,'cron_token':token}),patch('corner.live_odds.request_refresh') as queue:
            response=client.post('/api/v1/cron/refresh-live-odds',json={},headers={'Authorization':'Bearer '+token})
            self.assertEqual(response.status_code,202);queue.assert_called_once()
            self.assertEqual(client.post('/api/v1/cron/refresh-live-odds',json={},headers={'Authorization':'Bearer '+token,'Origin':'https://evil.invalid','X-Forwarded-For':'127.0.0.1'}).status_code,403)
        self.assertEqual(client.post('/api/v1/cron/refresh-live-odds',content='bad',headers={'Content-Type':'application/json'}).status_code,400)

class LiveBudgetAndDiscovery(unittest.TestCase):
    def test_scheduled_start_crossing_is_not_delayed_until_next_inventory_poll(self):
        with patch('corner.live_odds.enabled',return_value=True):
            planned=jobs(NOW,{'events':[event()],'live_events':[]})
        self.assertEqual(len(planned),2)

class LiveSignedEntitlement(unittest.TestCase):
    def test_signed_session_uses_database_identity_not_username_claim(self):
        from corner import auth
        from corner.tracker_store import TrackerStore
        from pipelines.accounts import AuthContext
        import os
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{'CORNER_PRIVATE_BETA':'0'}):
            store=TrackerStore(Path(folder)/'accounts.sqlite3')
            try:
                owner=store.create_user('wonya','wonya',auth.hash_password('long-fixture-pass'))
                other=store.create_user('member','member',auth.hash_password('long-fixture-pass'))
                ctx=AuthContext(store,'fixture-signing-secret',{'http://localhost:3000'})
                app=FastAPI();app.include_router(create_router(ctx,path=Path(folder)/'missing.sqlite3'))
                client=TestClient(app,base_url='http://localhost')
                client.cookies.set('corner_session',auth.issue_token('fixture-signing-secret',owner['id'],'wonya'))
                self.assertEqual(client.get('/api/v1/live-stoppages').status_code,200)
                client.cookies.set('corner_session',auth.issue_token('fixture-signing-secret',other['id'],'wonya'))
                self.assertEqual(client.get('/api/v1/live-stoppages?premium=true&username=wonya').status_code,403)
                with patch('corner.beta_access.decorate', side_effect=lambda db,row: {**row,'beta_cohort':'friend','beta_role':'member','beta_access_kind':'paid_beta','beta_founder':False,'beta_friend_rates':None}):
                    self.assertEqual(client.get('/api/v1/live-stoppages').status_code,200)
                self.assertEqual(client.get('/api/v1/live-stoppages').status_code,403)
                client.cookies.set('corner_session',auth.issue_token('wrong-secret',owner['id'],'wonya'))
                self.assertEqual(client.get('/api/v1/live-stoppages').status_code,401)
            finally:store.close()

if __name__=='__main__': unittest.main()
