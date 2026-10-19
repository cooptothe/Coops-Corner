"""No-network, temporary-account beta acceptance and ten-session fixture rehearsal."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_TIME = datetime(2026,10,18,12,tzinfo=timezone.utc).timestamp()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def rehearse():
    # Block external transports before importing application modules as well as during requests.
    with ExitStack() as network:
        network.enter_context(patch('requests.sessions.Session.request',side_effect=AssertionError('External network forbidden in offline rehearsal')))
        network.enter_context(patch('httpx.HTTPTransport.handle_request',side_effect=AssertionError('External network forbidden in offline rehearsal')))
        network.enter_context(patch('socket.create_connection',side_effect=AssertionError('Socket network forbidden in offline rehearsal')))
        return _rehearse()


def _rehearse():
    import httpx
    import requests
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.app import create_app
    from api.catalog import FixtureCatalog
    from corner import auth, beta_access as beta, beta_terms
    from corner.beta_invoices import BetaInvoices
    from corner.tracker_store import TrackerStore, TrackerError
    from pipelines.accounts import AuthContext, create_router as accounts_router
    from pipelines.billing_service import create_router as billing_router
    from pipelines.tracker_service import create_router as tracker_router

    checks=[]
    def passed(name): checks.append({'check':name,'status':'passed'})
    with tempfile.TemporaryDirectory(prefix='corner-offline-acceptance-') as folder, ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, {'CORNER_PRIVATE_BETA':'0','CORNER_BETA_TRIALS':'0','ODDS_API_KEY':''}))
        stack.enter_context(patch('requests.sessions.Session.request',side_effect=AssertionError('External network forbidden in offline rehearsal')))
        stack.enter_context(patch('httpx.HTTPTransport.handle_request',side_effect=AssertionError('External network forbidden in offline rehearsal')))
        stack.enter_context(patch('socket.create_connection',side_effect=AssertionError('Socket network forbidden in offline rehearsal')))
        stack.enter_context(patch('time.time',return_value=FIXTURE_TIME))
        stack.enter_context(patch('pipelines.billing_service.BetaInvoices',side_effect=lambda store:BetaInvoices(store,lambda:FIXTURE_TIME)))
        store=TrackerStore(str(Path(folder)/'accounts.sqlite3'))
        stack.callback(store.close)
        password='Synthetic-offline-password-only'
        hashed=auth.hash_password(password)
        owner=store.create_user('FixtureOwner','fixtureowner',hashed)['id']
        beta.bootstrap(store._db,'fixtureowner')
        receiving=json.loads((ROOT/'fixtures/billing/receiving-disabled.json').read_text(encoding='utf-8'))
        receiving.update(payments_enabled=False,receive_test_passed=False,manual_review_ready=False)
        config=Path(folder)/'synthetic-billing.json'
        config.write_text(json.dumps(receiving),encoding='utf-8')
        stack.enter_context(patch.dict(os.environ,{'CORNER_PRIVATE_BETA':'1','CORNER_BETA_TRIALS':'1','CORNER_BILLING_CONFIG':str(config)}))
        users=[]
        for index in range(10):
            name=f'fixturemember{index}'
            _,invite=beta.issue(store._db,owner,name,access_kind='preview',evidence='synthetic offline acceptance')
            users.append(store.create_user(name,name,hashed,invite)['id'])
        try:
            beta.issue(store._db,owner,'overflow',access_kind='preview',evidence='synthetic capacity check')
        except TrackerError:
            passed('Ten member seats enforced; eleventh invitation rejected')
        else:
            raise AssertionError('Member capacity exceeded')
        secret='offline-rehearsal-session-secret-'+'x'*48
        ctx=AuthContext(store,secret,{'http://localhost:3000'})
        tools=create_app(catalog=FixtureCatalog(),session_check=lambda token:auth.session_user(secret,token,store.user_by_id) is not None)
        app=FastAPI()
        app.include_router(accounts_router(ctx));app.include_router(billing_router(ctx));app.include_router(tracker_router(ctx))
        app.mount('/',tools)
        origin={'Origin':'http://localhost:3000'}
        def client_for(user):
            client=TestClient(app,base_url='http://localhost:3000')
            row=store.user_by_id(user)
            client.cookies.set('corner_session',auth.issue_token(secret,user,row['username'],epoch=row['session_epoch']))
            return client
        with TestClient(app,base_url='http://localhost:3000') as anonymous:
            require(anonymous.get('/api/v1/health').status_code==401,'Anonymous tool access allowed')
            require(anonymous.get('/api/refresh/v1/tracker/state').status_code==401,'Anonymous tracker access allowed')
        passed('Anonymous feed and personal-ledger access denied')

        def session(index):
            user=users[index]
            with TestClient(app,base_url='http://localhost:3000') as client:
                response=client.post('/api/refresh/v1/auth/login',headers=origin,json={'username':f'fixturemember{index}','password':password,'remember':False})
                require(response.status_code==200,'Synthetic member sign-in failed')
                require('httponly' in response.headers.get('set-cookie','').lower(),'Session cookie not HttpOnly')
                response=client.post('/api/refresh/v1/tracker/bets',headers=origin,json=[dict(client_key=f'fixture-bet-{index}',strategy='manual',matchup='Synthetic away at synthetic home',selection=f'Synthetic selection {index}',book='draftkings',odds='2.1',stake='10')])
                require(response.status_code==200,'Synthetic tracked bet failed')
                response=client.post('/api/refresh/v1/billing/requests',headers=origin,json={})
                require(response.status_code==503,'Disabled checkout accepted a payment request')
                timings=[]
                for _ in range(3):
                    for route in ('/api/refresh/v1/auth/me','/api/refresh/v1/tracker/state','/api/refresh/v1/billing/status','/api/v1/capabilities','/api/v1/tools/positive_ev'):
                        start=time.perf_counter();response=client.get(route);timings.append((time.perf_counter()-start)*1000)
                        require(response.status_code==200,'Authenticated fixture route failed')
                        require('no-store' in response.headers.get('cache-control',''),'Personal response is cacheable')
                        if route.endswith('/tracker/state'):
                            bets=response.json()['bets']
                            require(len(bets)==1 and bets[0]['selection']==f'Synthetic selection {index}','Cross-account tracker data detected')
                return timings
        with ThreadPoolExecutor(max_workers=10) as pool:
            timings=[duration for batch in pool.map(session,range(10)) for duration in batch]
        passed('Ten concurrent authenticated fixture sessions: 150 reads, isolated trackers, no-store responses')
        passed('Checkout remains disabled before synthetic payment stage')

        # These flags exist ONLY in the disposable test configuration. No server file or wallet is touched.
        receiving.update(payments_enabled=True,receive_test_passed=True,manual_review_ready=True,memo_reviewed=True,terms_version=beta_terms.VERSION)
        config.write_text(json.dumps(receiving),encoding='utf-8')
        invoices=BetaInvoices(store,lambda:FIXTURE_TIME)
        receipts=[]
        for index,asset in enumerate(('XRP','HBAR','XLM')):
            user=users[index]
            with client_for(user) as client:
                response=client.post('/api/refresh/v1/billing/requests',headers=origin,json={'asset':asset,'terms_version':beta_terms.VERSION})
                require(response.status_code==200,'Synthetic payment request failed')
                ident=response.json()['payment']['id']
                quote=invoices.quote(owner,ident,usd_per_coin='2',observed_at=FIXTURE_TIME,source='SYNTHETIC TEST RATE: NOT A MARKET QUOTE',receiving=receiving)
                tx=f'0.0.123@{int(FIXTURE_TIME)}.000000001' if asset=='HBAR' else str(index+1)*64
                response=client.post(f'/api/refresh/v1/billing/requests/{ident}/submit',headers=origin,json={'transaction_id':tx})
                require(response.status_code==200,'Synthetic payment claim failed')
                require(not store.user_by_id(user)['beta_founder'],'Unverified claim granted founder access')
                review=dict(evidence='SYNTHETIC TEST EVIDENCE ONLY: NO CHAIN TRANSFER',delivered_base_units=quote['amount_base_units'],destination=quote['address'],memo=quote['memo'],received_at=FIXTURE_TIME,transfer_index=0)
                invoices.approve(owner,ident,**review)
                require(client.get('/api/refresh/v1/auth/me').status_code==401,'Paid upgrade did not revoke the old session')
                require(invoices.approve(owner,ident,**review)['reused'],'Repeated review created a new payment')
                receipts.append((ident,review))
            with client_for(user) as client:
                offer=client.get('/api/refresh/v1/billing/status').json()
                require(offer['founder'] and offer['launch_monthly_usd_cents']==5000,'Founder pricing lost after approval')
            passed(f'{asset}: synthetic request, quote, claim, operator grant, session revocation and exact replay')
        require(store._db.execute('SELECT count(*) FROM beta_payment_receipts').fetchone()[0]==3,'Duplicate synthetic receipts')
        row=store.user_by_id(users[4]);started=row['beta_trial_started_at']
        require(beta.access_status(row,started+604799)['allowed'],'Trial ended early')
        require(not beta.access_status(row,started+604800)['allowed'],'Trial exceeded seven days')
        with client_for(users[4]) as client:
            require(client.get('/api/refresh/v1/billing/status').json()['launch_monthly_usd_cents']==12500,'Nonfounder standard price is incorrect')
        passed('Seven-day trial boundary and $125 nonfounder / $50 founder pricing')
        with client_for(users[8]) as client:
            beta.state(store._db,owner,'fixturemember8','suspended')
            require(client.get('/api/v1/health').status_code==401,'Suspended member retained tool access')
        with client_for(users[9]) as client:
            copied=client.cookies.get('corner_session')
            require(client.post('/api/refresh/v1/auth/logout-all',headers=origin,json={}).status_code==200,'Sign-out-everywhere failed')
            client.cookies.set('corner_session',copied)
            require(client.get('/api/refresh/v1/auth/me').status_code==401,'Copied session survived revocation')
        passed('Suspension and sign-out-everywhere revoke copied session access')
        recovery=Path(folder)/'recovered.sqlite3'
        db=sqlite3.connect(recovery)
        try:store._db.backup(db)
        finally:db.close()
        restored=TrackerStore(str(recovery))
        try:
            require(restored._db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','Recovered account integrity failed')
            recovered=BetaInvoices(restored,lambda:FIXTURE_TIME)
            for ident,review in receipts:
                require(recovered.approve(owner,ident,**review)['reused'],'Recovered payment replay duplicated a grant')
            require(restored._db.execute('SELECT count(*) FROM beta_payment_receipts').fetchone()[0]==3,'Recovered receipt count changed')
            require(all(restored.user_by_id(user)['beta_founder'] for user in users[:3]),'Recovered founder status lost')
        finally:restored.close()
        passed('Isolated SQLite restore preserves three receipts and founder grants; replay remains idempotent')
    values=sorted(timings)
    return {'result':'passed','mode':'synthetic_offline_acceptance','checked_at_utc':datetime.now(timezone.utc).isoformat(),'checks':checks,
            'sessions':10,'authenticated_reads':len(values),
            'fixture_latency_ms':{'median':round(values[len(values)//2],2),'p95':round(values[math.ceil(len(values)*.95)-1],2),'maximum':round(values[-1],2)},
            'performance_scope':'In-process authenticated fixture API only; not VPS, browser, production database or paid-provider load proof.',
            'fixture_clock_utc':'2026-10-18T12:00:00Z',
            'external_network_requests':0,'odds_provider_calls':0,'funds_transferred':False,'production_configuration_changed':False,
            'deferred':['Real funded receive tests for XRP/HBAR/XLM','Live odds/quota smoke','VPS authenticated load, reboot and rollback evidence','Physical mobile installation checks']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    try:result=rehearse()
    except Exception as error:
        result={'result':'failed','mode':'synthetic_offline_acceptance','error_type':type(error).__name__,'production_configuration_changed':False}
        if isinstance(error,AssertionError):result['check']=str(error)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
    return 0 if result['result']=='passed' else 1

if __name__=='__main__':raise SystemExit(main())
