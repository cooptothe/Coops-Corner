"""Opt-in real database round trip. Creates/drops only a disposable test database."""
import os,json,tempfile,hashlib,unittest
from uuid import uuid4
from pathlib import Path
from datetime import timedelta
from tests import test_featured_store as store
from tests.test_additional_markets import NOW,START,quotes
from corner.additional_markets import MARKET_TYPES
from pipelines.odds_ingestion import ingest
from corner.ingestion import _ensure_vocabulary
from api.database import QUOTE_SQL,PARTICIPANT_SQL,MARKET_KEYS,build_raw
from api.catalog import FixtureCatalog
from psycopg2.extras import RealDictCursor
@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE')=='1' and os.getenv('CORNER_TEST_CONCURRENCY')=='1','opt-in disposable database')
class AdditionalPersistenceTests(unittest.TestCase):
 setUpClass=classmethod(store.FeaturedStoreTests.setUpClass.__func__)
 connect=classmethod(store.FeaturedStoreTests.connect.__func__)
 drop_database=classmethod(store.FeaturedStoreTests.drop_database.__func__)
 def test_recorded_ingestion_replay_reader_and_tools(self):
  e={'id':'additional-validation','sport_key':'basketball_nba','home_team':'Hawks','away_team':'Bears','commence_time':START.isoformat(),'bookmakers':[]}
  reverse={v:k for k,v in MARKET_TYPES.items()}
  for r in quotes():
   book=next((b for b in e['bookmakers'] if b['key']==r['book_code']),None)
   if book is None:book={'key':r['book_code'],'title':r['book_name'],'last_update':NOW.isoformat(),'markets':[]};e['bookmakers'].append(book)
   key=reverse[r['market_code']];market=next((m for m in book['markets'] if m['key']==key),None)
   if market is None:market={'key':key,'last_update':NOW.isoformat(),'outcomes':[]};book['markets'].append(market)
   names={'home':'Hawks','away':'Bears','over':'Over','under':'Under','yes':'Yes','no':'No'}
   o={'name':names[r['side']],'price':str(r['decimal_odds'])}
   if r['point'] is not None:o['point']=str(r['point'])
   if key=='team_totals':o['description']=r['selection_name']
   market['outcomes'].append(o)
  raw=json.dumps([e]).encode()
  conn=self.connect()
  with conn.cursor() as cur:
   cur.execute((Path(__file__).resolve().parents[1]/'db/migrations/015_corner_quote_links.sql').read_text())
  with conn.cursor() as cur:_ensure_vocabulary(cur,'quote_states','active','Active')
  conn.commit()
  writer='additional_writer_'+uuid4().hex
  reader='additional_reader_'+uuid4().hex
  with conn.cursor() as cur:
   for role in (writer,reader):
    cur.execute(f'CREATE ROLE {role} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS')
    cur.execute(f'GRANT USAGE ON SCHEMA corner TO {role}')
   cur.execute((Path(__file__).resolve().parents[1]/'fixtures/additional/writer-grants.sql').read_text().format(writer=writer))
   tables='events,competitions,markets,market_types,scopes,outcomes,outcome_sides,event_participants,participants,sportsbooks,quote_states,quote_links,trusted_current_quotes'
   cur.execute('GRANT SELECT ON '+','.join('corner.'+x for x in tables.split(','))+f' TO {reader}')
  conn.commit();conn.close()
  def cleanup():
   c=self.connect();c.autocommit=True
   with c.cursor() as cur:
    for role in (writer,reader):cur.execute(f'DROP OWNED BY {role}');cur.execute(f'DROP ROLE {role}')
   c.close()
  self.addCleanup(cleanup)
  def restricted_writer():
   c=self.connect()
   with c.cursor() as cur:cur.execute(f'SET ROLE {writer}')
   return c
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);(root/'response.body').write_bytes(raw)
   (root/'manifest.json').write_text(json.dumps({'http_status':200,'sport':'basketball_nba','sha256':hashlib.sha256(raw).hexdigest(),'received_at':NOW.isoformat()}))
   ingest(root,connect=restricted_writer);ingest(root,connect=restricted_writer)
  conn=self.connect()
  with conn.cursor() as cur:
   cur.execute('SELECT count(*) FROM corner.odds_observations');self.assertEqual(len(quotes()),cur.fetchone()[0])
  with conn.cursor() as cur:
   cur.execute(f'SET ROLE {reader}')
   cur.execute("SELECT has_table_privilege(current_user,'corner.provider_payloads','SELECT'),has_table_privilege(current_user,'corner.odds_observations','INSERT')")
   self.assertEqual((False,False),cur.fetchone())
  with conn.cursor(cursor_factory=RealDictCursor) as cur:
   cur.execute(QUOTE_SQL,dict(market_codes=list(MARKET_KEYS),now=NOW,oldest=NOW-timedelta(minutes=1)));rows=cur.fetchall()
  with conn.cursor() as cur:
   cur.execute(PARTICIPANT_SQL,dict(events=list({str(r['event_id']) for r in rows})));people=cur.fetchall()
  conn.close()
  catalog=FixtureCatalog(raw=build_raw(rows,people,now=NOW))
  for kind in ('positive_ev','arbitrage'):
   self.assertEqual(set(MARKET_TYPES),{r.market_key for r in catalog.rows if r.kind==kind})
  self.assertTrue(any(r.kind=='middle' and r.market_key=='team_totals' for r in catalog.rows))
