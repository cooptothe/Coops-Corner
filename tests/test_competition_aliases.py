"""Rotating tournament identity regression, with an opt-in disposable PostgreSQL DB."""
from contextlib import redirect_stdout
from io import StringIO
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4
from corner.ingestion import SPORT_KEY_MAPPINGS

ROOT=Path(__file__).resolve().parents[1]
MIGRATION=ROOT/'db/migrations/016_corner_competition_provider_aliases.sql'

class TourMappingTests(unittest.TestCase):
    def test_distinct_rotating_provider_keys_share_the_intended_canonical_tour(self):
        for tour in ('wta','atp'):
            first=SPORT_KEY_MAPPINGS[f'tennis_{tour}_pan_pacific_open']
            second=SPORT_KEY_MAPPINGS[f'tennis_{tour}_another_tournament']
            self.assertEqual(first,second)
            self.assertEqual(first[2],tour)
        self.assertNotEqual(SPORT_KEY_MAPPINGS['tennis_wta_a'][2],SPORT_KEY_MAPPINGS['tennis_atp_a'][2])

@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE')=='1','opt-in disposable PostgreSQL database')
class CompetitionAliasPersistence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg2
        from psycopg2 import sql
        from config import DB_CONFIG
        cls.name='corner_alias_test_'+uuid4().hex
        cls.config={**DB_CONFIG,'dbname':cls.name,'connect_timeout':3}
        cls.config.pop('database',None)
        admin=psycopg2.connect(**{**DB_CONFIG,'connect_timeout':3});admin.autocommit=True
        try:
            with admin.cursor() as cur:cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.name)))
        finally:admin.close()
        cls.addClassCleanup(cls.drop_database)
        conn=cls.connect()
        try:
            for path in [*sorted((ROOT/'db/migrations').glob('00[2-6]_*.sql')),ROOT/'db/migrations/015_corner_quote_links.sql']:
                with conn.cursor() as cur:cur.execute(path.read_text(encoding='utf-8'))
            from corner.ingestion import _ensure_vocabulary
            with conn.cursor() as cur:_ensure_vocabulary(cur,'quote_states','active','Active')
            conn.commit()
        finally:conn.close()

    @classmethod
    def connect(cls):
        import psycopg2
        return psycopg2.connect(**cls.config)

    @classmethod
    def drop_database(cls):
        import psycopg2
        from psycopg2 import sql
        from config import DB_CONFIG
        if not cls.name.startswith('corner_alias_test_') or len(cls.name)!=50:raise AssertionError('Unexpected disposable target')
        admin=psycopg2.connect(**{**DB_CONFIG,'connect_timeout':3});admin.autocommit=True
        try:
            with admin.cursor() as cur:cur.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.name)))
        finally:admin.close()

    def test_real_ingestion_reproduces_collision_then_replays_without_duplicate_observations(self):
        from psycopg2.errors import UniqueViolation
        from pipelines.odds_ingestion import _ingest_one
        with tempfile.TemporaryDirectory() as folder:
            captures=[]
            for index,sport in enumerate(('tennis_wta_previous_event','tennis_wta_pan_pacific_open','tennis_atp_first_event','tennis_atp_next_event')):
                path=Path(folder)/str(index);path.mkdir()
                raw=json.dumps([{'id':f'event-{index}','sport_key':sport,'sport_title':sport,
                    'home_team':f'Player {index} A','away_team':f'Player {index} B','commence_time':'2030-01-02T12:00:00Z',
                    'bookmakers':[{'key':'draftkings','title':'DraftKings','last_update':'2030-01-01T12:00:00Z',
                    'markets':[{'key':'h2h','last_update':'2030-01-01T12:00:00Z','outcomes':[
                        {'name':f'Player {index} A','price':1.9},{'name':f'Player {index} B','price':2.1}]}]}]}]).encode()
                (path/'response.body').write_bytes(raw)
                (path/'manifest.json').write_text(json.dumps({'http_status':200,'sha256':hashlib.sha256(raw).hexdigest(),
                    'sport':sport,'received_at':'2030-01-01T12:00:00Z'}),encoding='utf-8')
                captures.append(path)
            with redirect_stdout(StringIO()):_ingest_one(captures[0],connect=self.connect)
            with self.assertRaises(UniqueViolation) as failed:
                _ingest_one(captures[1],connect=self.connect)
            self.assertEqual(failed.exception.diag.constraint_name,'competition_provider_current_identity_key')
            conn=self.connect()
            try:
                # Applying twice is safe for interrupted/repeated operator batches.
                for _ in range(2):
                    with conn.cursor() as cur:cur.execute(MIGRATION.read_text(encoding='utf-8'))
            finally:conn.close()
            with redirect_stdout(StringIO()):
                for path in captures[1:]:_ingest_one(path,connect=self.connect)
                for path in captures:_ingest_one(path,connect=self.connect)
            conn=self.connect()
            try:
                with conn.cursor() as cur:
                    cur.execute('SELECT count(*) FROM corner.odds_observations');self.assertEqual(cur.fetchone()[0],8)
                    cur.execute('SELECT count(*) FROM corner.provider_payloads');self.assertEqual(cur.fetchone()[0],4)
                    cur.execute('SELECT count(*) FROM corner.competition_provider_identities WHERE active');self.assertEqual(cur.fetchone()[0],4)
                    cur.execute("SELECT count(*) FROM corner.competitions WHERE code IN ('wta','atp')");self.assertEqual(cur.fetchone()[0],2)
                    # The same provider key still cannot point at another tour.
                    with self.assertRaises(UniqueViolation) as duplicate:
                        cur.execute("INSERT INTO corner.competition_provider_identities(provider_id,competition_id,external_id) SELECT p.provider_id,c.id,p.external_id FROM corner.competition_provider_identities p JOIN corner.competitions c ON c.code='atp' WHERE p.external_id='tennis_wta_pan_pacific_open'")
                    self.assertEqual(duplicate.exception.diag.constraint_name,'competition_provider_external_key')
            finally:conn.rollback();conn.close()
