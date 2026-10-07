"""Real Spring/JDBC acceptance using disposable canonical PostgreSQL data.

Existing DB_CONFIG is used only to create/remove the uniquely named test DB/role.
The service receives an ephemeral SELECT-only login via environment, never argv.
--preview keeps the disposable service on :8080 until Ctrl+C, then removes it.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import time
import unittest
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from uuid import uuid4

import psycopg2
from psycopg2 import sql
from config import DB_CONFIG

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('featured_fixture_support', ROOT/'tests/test_featured_store.py')
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)


class Harness:
    def __init__(self, port=0, configure=None):
        self.port = port
        self.role = 'corner_market_test_' + uuid4().hex
        self.password = secrets.token_urlsafe(32)
        self.process = None
        self.fixture = None
        self.database_created = False
        self.role_created = False
        self.configure = configure

    def start(self):
        support.FeaturedStoreTests.setUpClass()
        self.database_created = True
        self.database = support.FeaturedStoreTests.database_name
        self.fixture = support.FeaturedStoreTests('test_all_markets_persist_and_replay_exactly')
        self.fixture.setUp()
        self.fixture.ingest()
        # Original retained fixture timestamps remain untouched. Append a later
        # operational state per stream to exercise real freshness and suspension.
        conn = self.fixture.conn
        self.now = datetime.now(timezone.utc)
        # Fixture observations are in 2030. Reject them explicitly before adding
        # present-day test observations, rather than updating immutable history.
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO corner.observation_dispositions
                (observation_id,disposition_type_id,decision_key,reason,decided_at,authority_kind,authority_id)
                SELECT id,(SELECT id FROM corner.disposition_types WHERE code='rejected'),id::text,
                    'synthetic future fixture excluded for host test',%s,'service','market-acceptance'
                FROM corner.odds_observations WHERE provider_payload_id=%s""",(self.now,self.fixture.payload_id))
            cur.execute("""INSERT INTO corner.odds_observations
                (provider_payload_id,provider_id,outcome_id,sportsbook_id,quote_state_id,source_record_key,
                 decimal_odds,observed_at,provider_updated_at)
                SELECT provider_payload_id,provider_id,outcome_id,sportsbook_id,quote_state_id,
                    'acceptance-current:'||id::text,decimal_odds,%s,%s
                FROM corner.odds_observations WHERE provider_payload_id=%s RETURNING id,outcome_id,sportsbook_id""",
                (self.now,self.now,self.fixture.payload_id))
            self.current = [(str(a),str(b),str(c)) for a,b,c in cur.fetchall()]
            cur.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD %s NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT').format(sql.Identifier(self.role)),(self.password,))
            self.role_created = True
            cur.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(self.database),sql.Identifier(self.role)))
            cur.execute(sql.SQL('GRANT USAGE ON SCHEMA corner TO {}').format(sql.Identifier(self.role)))
            tables = ('events','competitions','participants','event_participants','markets','market_types','scopes',
                      'sportsbooks','outcomes','outcome_sides','odds_observations','quote_states','providers','trusted_current_quotes')
            cur.execute(sql.SQL('GRANT SELECT ON {} TO {}').format(
                sql.SQL(',').join(sql.Identifier('corner',t) for t in tables),sql.Identifier(self.role)))
        conn.commit()
        if not self.port:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0)); self.port=sock.getsockname()[1]
        self.env = os.environ.copy()
        host=DB_CONFIG.get('host','127.0.0.1'); port=DB_CONFIG.get('port',5432)
        self.env.update(CORNER_MARKET_JDBC_URL=f'jdbc:postgresql://{host}:{port}/{self.database}?connectTimeout=3&socketTimeout=8',
                        CORNER_MARKET_DB_USER=self.role,CORNER_MARKET_DB_PASSWORD=self.password,
                        CORNER_MARKET_PORT=str(self.port),CORNER_MARKET_MAX_AGE_SECONDS='120',CORNER_MARKET_DATASET='synthetic_acceptance')
        if self.configure:
            self.env.update(self.configure(self))
        java = os.getenv('CORNER_JAVA',str(ROOT/'.tools/jdk-21.0.12.1+1/bin/java.exe'))
        self.process=subprocess.Popen([java,'-jar',str(ROOT/'server/target/market-api-0.1.0.jar')],env=self.env,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        for _ in range(80):
            if self.process.poll() is not None: raise RuntimeError('Spring service exited during startup')
            try:
                status,body=self.get('/health')
                if status==200: return self
            except (URLError,TimeoutError): pass
            time.sleep(.25)
        raise RuntimeError('Spring service did not become ready')

    def get(self,path):
        try:
            with urlopen(f'http://127.0.0.1:{self.port}/api/market/v1'+path,timeout=10) as response:
                assert response.headers.get('Cache-Control')=='no-store'
                return response.status,json.load(response)
        except HTTPError as e:
            with e: return e.code,json.load(e)

    def board(self):
        event=next(iter(self.fixture.events.values()))
        return self.get(f'/games/{event}/odds')

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(timeout=15)
            except subprocess.TimeoutExpired: self.process.kill();self.process.wait(timeout=5)
        if self.fixture: self.fixture.doCleanups()
        if self.database_created: support.FeaturedStoreTests.doClassCleanups()
        if self.role_created:
            admin=psycopg2.connect(**DB_CONFIG);admin.autocommit=True
            try:
                with admin.cursor() as cur: cur.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(self.role)))
            finally: admin.close()


class MarketAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h=Harness()
        cls.addClassCleanup(cls.h.close)
        cls.h.start()

    def test_01_database_health_enforces_read_only(self):
        status,body=self.h.get('/health')
        self.assertEqual(200,status)
        self.assertEqual('on',body['data']['transaction_read_only'])
        cfg=dict(support.FeaturedStoreTests.connection_config,user=self.h.role,password=self.h.password)
        conn=psycopg2.connect(**cfg)
        try:
            with self.assertRaises(psycopg2.errors.InsufficientPrivilege),conn.cursor() as cur:
                cur.execute("UPDATE corner.events SET scheduled_start=scheduled_start")
        finally: conn.close()

    def test_02_games_paging_filters_and_exact_ids(self):
        status,body=self.h.get('/games?limit=1')
        self.assertEqual(200,status); self.assertEqual(1,len(body['data']['items']))
        self.assertGreater(body['data']['total'],1)
        status,filtered=self.h.get('/games?market_key=outrights')
        self.assertEqual(1,len(filtered['data']['items']))
        self.assertEqual('unknown',filtered['data']['items'][0]['phase'])
        self.assertEqual([],self.h.get('/games?search=nonexistent_zz')[1]['data']['items'])

    def test_03_board_retains_decimal_identity_and_missing_cells(self):
        status,body=self.h.board()
        self.assertEqual(200,status); self.assertEqual('database',body['meta']['data_mode'])
        quotes=body['data']['quotes']
        present=[q for q in quotes if q['observation_id']]
        self.assertTrue(present)
        self.assertTrue(all(isinstance(q['decimal_odds'],str) for q in present))
        self.assertTrue(all(q['provider_payload_id']==self.h.fixture.payload_id for q in present))
        self.assertTrue(all(q['display_status']=='fresh' for q in present))
        self.assertTrue(any(q['display_status']=='missing' for q in quotes))
        self.assertFalse(body['meta']['production_authorized'])

    def test_04_invalid_queries_and_ids(self):
        for path in ('/games?limit=101','/games?offset=-1','/games?market_key=player_points','/games?limit=1&limit=2','/games?unexpected=1','/games/nope/odds'):
            self.assertEqual(400,self.h.get(path)[0],path)
        self.assertEqual(404,self.h.get(f'/games/{uuid4()}/odds')[0])

    def test_05_repeated_reads_preserve_observation_time_and_revision(self):
        one=self.h.board()[1];two=self.h.board()[1]
        self.assertEqual(one['data'],two['data'])
        self.assertNotEqual(one['meta']['read_at'],two['meta']['read_at'])

    def test_06_suspension_and_withdrawal(self):
        _,before=self.h.board()
        q=next(q for q in before['data']['quotes'] if q['observation_id'])
        with self.h.fixture.conn.cursor() as cur:
            cur.execute("INSERT INTO corner.quote_states(code,display_name) VALUES ('suspended','Suspended') ON CONFLICT DO NOTHING")
            cur.execute("""INSERT INTO corner.odds_observations
                (provider_payload_id,provider_id,outcome_id,sportsbook_id,quote_state_id,source_record_key,decimal_odds,observed_at)
                SELECT provider_payload_id,provider_id,outcome_id,sportsbook_id,
                    (SELECT id FROM corner.quote_states WHERE code='suspended'),'acceptance-suspended',NULL,clock_timestamp()
                FROM corner.odds_observations WHERE id=%s RETURNING id""",(q['observation_id'],))
            suspended=str(cur.fetchone()[0])
        self.h.fixture.conn.commit()
        after=self.h.board()[1]['data']
        cell=next(c for c in after['quotes'] if c['outcome_id']==q['outcome_id'] and c['sportsbook_id']==q['sportsbook_id'])
        self.assertEqual(suspended,cell['observation_id']);self.assertIsNone(cell['decimal_odds'])
        self.assertEqual('suspended',cell['display_status'])
        self.assertNotEqual(before['data']['revision'],after['revision'])
        # Reject both retained candidates; the stream becomes missing and does
        # not resurrect the already-rejected future fixture observation.
        with self.h.fixture.conn.cursor() as cur:
            for observation in (q['observation_id'],suspended):
                cur.execute("""INSERT INTO corner.observation_dispositions
                    (observation_id,disposition_type_id,decision_key,reason,decided_at,authority_kind,authority_id)
                    VALUES (%s,(SELECT id FROM corner.disposition_types WHERE code='rejected'),%s,
                    'acceptance withdrawal',clock_timestamp(),'service','market-acceptance')""",(observation,str(uuid4())))
        self.h.fixture.conn.commit()
        missing=self.h.board()[1]['data']['quotes']
        cell=next(c for c in missing if c['outcome_id']==q['outcome_id'] and c['sportsbook_id']==q['sportsbook_id'])
        self.assertEqual('missing',cell['display_status']);self.assertIsNone(cell['observation_id'])

    def test_07_late_commit_is_visible_on_next_read(self):
        before=self.h.get('/games')[1]['data']['total']
        conn=self.h.fixture.conn
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO corner.events(competition_id,scheduled_start,event_status_id)
                SELECT competition_id,scheduled_start,event_status_id FROM corner.events LIMIT 1 RETURNING id""")
            event=cur.fetchone()[0]
            cur.execute("""INSERT INTO corner.markets(event_id,market_type_id,scope_id)
                SELECT %s,market_type_id,scope_id FROM corner.markets LIMIT 1""",(event,))
        self.assertEqual(before,self.h.get('/games')[1]['data']['total'])
        conn.commit()
        self.assertEqual(before+1,self.h.get('/games')[1]['data']['total'])

    def test_08_permission_failure_is_error_not_empty_board(self):
        with self.h.fixture.conn.cursor() as cur:
            cur.execute(sql.SQL('REVOKE SELECT ON corner.events FROM {}').format(sql.Identifier(self.h.role)))
        self.h.fixture.conn.commit()
        try:
            status,body=self.h.get('/games')
            self.assertEqual(503,status);self.assertNotIn('data',body)
            self.assertNotIn(self.h.password,json.dumps(body))
        finally:
            with self.h.fixture.conn.cursor() as cur:
                cur.execute(sql.SQL('GRANT SELECT ON corner.events TO {}').format(sql.Identifier(self.h.role)))
            self.h.fixture.conn.commit()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--preview',action='store_true');args=parser.parse_args()
    if args.preview:
        harness=Harness(8080)
        try:
            harness.start()
            print('Database-backed synthetic preview ready on :8080. Ctrl+C removes the disposable database and login.',flush=True)
            while True: time.sleep(1)
        except KeyboardInterrupt: pass
        finally: harness.close()
    else:
        unittest.main(argv=['market_api'],verbosity=2)
