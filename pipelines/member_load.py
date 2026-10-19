"""Isolated, loopback HTTP load rehearsal with disposable authenticated members.

Reads saved PostgreSQL odds only. Never uses production accounts or auth secrets,
creates database roles, calls a provider, or activates checkout/collection.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import secrets
import socket
import tempfile
import threading
import time
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler
from pipelines.release_probe import NoRedirects

ROUTES = ('/api/v1/capabilities', '/api/v1/games?limit=100',
          '/api/v1/tools/positive_ev?limit=1000', '/api/v1/tools/arbitrage?limit=1000',
          '/api/v1/tools/middle?limit=1000', '/api/v1/quotes?limit=1000')


def summary(values):
    ordered = sorted(values)
    return dict(samples=len(ordered), median_ms=round(ordered[len(ordered)//2], 2),
                p95_ms=round(ordered[math.ceil(len(ordered)*.95)-1], 2),
                maximum_ms=round(ordered[-1], 2))


def rehearse(catalog, *, sessions=10, rounds=2, budget_ms=1500):
    if not 1 <= sessions <= 15 or not 1 <= rounds <= 5 or not 1 <= budget_ms <= 10000:
        raise ValueError('Use 1-15 sessions, 1-5 rounds, and a 1-10000 ms request budget')
    import uvicorn
    from api.app import create_app
    from corner import auth, beta_access
    from corner.tracker_store import TrackerStore

    def blocked(*args, **kwargs):
        raise RuntimeError('Provider transports disabled in member load rehearsal')

    with tempfile.TemporaryDirectory(prefix='corner-member-load-') as directory, ExitStack() as stack:
        stack.enter_context(patch('requests.sessions.Session.request', side_effect=blocked))
        stack.enter_context(patch('httpx.HTTPTransport.handle_request', side_effect=blocked))
        stack.enter_context(patch.dict(os.environ, {'CORNER_PRIVATE_BETA':'0', 'CORNER_BETA_TRIALS':'0', 'ODDS_API_KEY':''}))
        store = TrackerStore(str(Path(directory)/'accounts.sqlite3'))
        stack.callback(store.close)
        password_hash = auth.hash_password(secrets.token_urlsafe(32))
        owner = store.create_user('loadowner', 'loadowner', password_hash)['id']
        beta_access.bootstrap(store._db, 'loadowner')
        stack.enter_context(patch.dict(os.environ, {'CORNER_PRIVATE_BETA':'1'}))
        users = []
        for index in range(sessions):
            name = f'loadmember{index}'
            _, invite = beta_access.issue(store._db, owner, name, access_kind='preview', cohort='beta' if index<10 else 'friend', evidence='Disposable HTTP load rehearsal')
            users.append(store.create_user(name, name, password_hash, invite))
        secret = secrets.token_urlsafe(64)
        app = create_app(data_mode=catalog.data_mode, catalog=catalog,
                         session_check=lambda token: auth.session_user(secret, token, store.user_by_id) is not None)
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(128)
        stack.callback(listener.close)
        origin = f'http://127.0.0.1:{listener.getsockname()[1]}'
        server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False, timeout_graceful_shutdown=5))
        thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
        thread.start()
        def stop():
            server.should_exit = True
            thread.join(10)
            if thread.is_alive():
                raise RuntimeError('Isolated load server did not stop')
        stack.callback(stop)
        deadline = time.monotonic()+15
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.02)
        if not server.started:
            raise RuntimeError('Isolated load server startup failed')

        def read(path, token=None):
            headers = {'Accept':'application/json'}
            if token:
                headers['Cookie'] = 'corner_session='+token
            start = time.perf_counter()
            # Disable ambient proxies; the only destination is the ephemeral loopback server.
            opener = build_opener(ProxyHandler({}), NoRedirects())
            try:
                response = opener.open(Request(origin+path, headers=headers), timeout=15)
            except HTTPError as error:
                response = error
            with response:
                body = response.read(16*1024*1024+1)
                if len(body)>16*1024*1024:
                    raise AssertionError('Response exceeds load-test body bound')
                payload = json.loads(body)
                return response.status, response.headers.get('Cache-Control',''), payload, (time.perf_counter()-start)*1000

        if read('/api/v1/health')[0] != 401:
            raise AssertionError('Anonymous member data exposed')
        barrier = threading.Barrier(sessions)
        def member(user):
            row = store.user_by_id(user['id'])
            token = auth.issue_token(secret, row['id'], row['username'], epoch=row['session_epoch'])
            barrier.wait(timeout=15)
            samples=[]
            for _ in range(rounds):
                for path in ROUTES:
                    status, cache, payload, elapsed = read(path, token)
                    if status != 200 or 'no-store' not in cache or payload['meta']['snapshot_id'] != catalog.snapshot_id:
                        raise AssertionError('Authenticated read, no-store, or snapshot consistency failed')
                    samples.append((path, elapsed))
            # Invalid signatures must never inherit a previous authenticated response.
            if read('/api/v1/health', token+'invalid')[0] != 401:
                raise AssertionError('Invalid session accepted')
            return samples
        with ThreadPoolExecutor(max_workers=sessions) as pool:
            samples = [sample for batch in pool.map(member, users) for sample in batch]
        suspended = store.user_by_id(users[0]['id'])
        copied = auth.issue_token(secret, suspended['id'], suspended['username'], epoch=suspended['session_epoch'])
        beta_access.state(store._db, owner, suspended['username'], 'suspended')
        if read('/api/v1/health', copied)[0] != 401:
            raise AssertionError('Suspended member retained copied-session access')
        if sessions > 1:
            active = store.user_by_id(users[1]['id'])
            token = auth.issue_token(secret, active['id'], active['username'], epoch=active['session_epoch'])
            if read('/api/v1/health', token)[0] != 200:
                raise AssertionError('Suspending one member revoked another member')
        by_route={path:summary([ms for route,ms in samples if route==path]) for path in ROUTES}
        passed=all(stats['p95_ms']<=budget_ms for stats in by_route.values())
        return dict(result='passed' if passed else 'failed', checked_at_utc=datetime.now(timezone.utc).isoformat(),
                    scope='Isolated loopback HTTP, '+('saved-odds database catalog' if catalog.data_mode=='database' else 'synthetic fixture catalog')+', disposable signed member sessions; excludes public proxy, browser rendering, and production account store.',
                    data_mode=catalog.data_mode, snapshot_id=catalog.snapshot_id,
                    games=len(catalog.games), quotes=len(catalog.quotes), tool_rows=len(catalog.rows),
                    sessions=sessions, rounds=rounds, per_route=by_route, p95_budget_ms=budget_ms,
                    anonymous_denied=True, invalid_sessions_denied=True, suspension_revokes_copied_token=True, private_responses_no_store=True,
                    provider_calls=0, wallet_transfers=0, production_account_mutations=0)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--sessions', type=int, default=10)
    parser.add_argument('--rounds', type=int, default=2)
    args=parser.parse_args()
    import psycopg2
    from api.database import LiveCatalog
    from config import DB_CONFIG
    if DB_CONFIG.get('host') not in ('127.0.0.1','localhost','::1'):
        parser.error('Use the local PostgreSQL connection only')
    start=time.perf_counter()
    # Every SQL transaction is read-only; statement/connection timeouts bound failures.
    login={**DB_CONFIG, 'connect_timeout':5, 'options':'-c statement_timeout=8000 -c default_transaction_read_only=on'}
    catalog=LiveCatalog(lambda:psycopg2.connect(**login))
    cold=time.perf_counter()-start
    result=rehearse(catalog, sessions=args.sessions, rounds=args.rounds)
    result['cold_catalog_seconds']=round(cold,3)
    if not catalog.quotes:
        result['result']='incomplete'
        result['coverage_warning']='No currently eligible saved quotes; this does not prove realistic data-load performance. No provider retry performed.'
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
    return 0 if result['result']=='passed' else 2 if result['result']=='incomplete' else 1


if __name__=='__main__':
    raise SystemExit(main())
