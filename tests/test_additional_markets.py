import json
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch
from corner.additional_markets import ADDITIONAL_MARKETS, SCHEDULED_ADDITIONAL_MARKETS
from corner.featured_markets import normalize_featured_payload,FeaturedMarketError
from corner.collection_policy import Job,STANDARD,EXCHANGE,plan,interval
from corner.credit_governor import Governor,Refused
from api.database import build_raw,keep_latest_capture
from api.catalog import FixtureCatalog
from api.app import create_app
from fastapi.testclient import TestClient
NOW=datetime(2030,1,1,15,tzinfo=timezone.utc)
START=NOW+timedelta(minutes=20)
EVENT='11111111-1111-1111-1111-111111111111'
PEOPLE=[(EVENT,'home','Hawks'),(EVENT,'away','Bears')]
def row(book,market,side,price,point=None,subject=None):
 return dict(event_id=EVENT,competition_code='nba',competition_name='NBA',scheduled_start=START,
 market_code=market,scope_code='full_game',side=side,point=None if point is None else D(point),
 selection_name=subject,book_code=book,book_name=book,decimal_odds=D(price),observed_at=NOW,
 provider_updated_at=NOW,provider_payload_id='capture')
def quotes():
 rows=[]
 for code,sides,line in [('alternate_spread',('home','away'),'-2.5'),('alternate_total',('over','under'),'10.5'),('btts',('yes','no'),None),('draw_no_bet',('home','away'),None),('team_total',('over','under'),'4.5'),('alternate_team_total',('over','under'),'5.5')]:
  for book,prices in [('draftkings',('2.30','1.80')),('pinnacle',('1.95','2.10')),('prophetx',('1.95','2.10'))]:
   for side,price in zip(sides,prices):
    value=str(-D(line)) if code=='alternate_spread' and side=='away' else line
    rows.append(row(book,code,side,price,value,'Hawks' if code in {'team_total','alternate_team_total'} else None))
 # Cross-line opportunities; keep home/away team totals isolated.
 for book,line,subject in [('fanduel','12.5',None)]:
  rows.extend([row(book,'alternate_total','over','1.9',line),row(book,'alternate_total','under','2.1',line)])
 for subject,line in [('Hawks','6.5'),('Bears','6.5')]:
  rows.extend([row('fanduel','team_total','over','1.9',line,subject),row('fanduel','team_total','under','2.1',line,subject)])
 return rows
class AdditionalTests(unittest.TestCase):
 def test_all_five_reach_ev_and_arbs(self):
  c=FixtureCatalog(raw=build_raw(quotes(),PEOPLE,now=NOW))
  for kind in ('positive_ev','arbitrage'):
   self.assertEqual(set(ADDITIONAL_MARKETS),{r.market_key for r in c.rows if r.kind==kind})
  self.assertTrue(all(c.contracts[r.contract_id].refund_possible for r in c.rows if r.market_key=='draw_no_bet'))
  for r in c.rows:
   if r.kind=='arbitrage' and r.market_key=='draw_no_bet':self.assertEqual(D(0),r.calculation.minimum_modeled_profit)
 def test_middles_only_line_markets_and_same_team(self):
  c=FixtureCatalog(raw=build_raw(quotes(),PEOPLE,now=NOW));middles=[r for r in c.rows if r.kind=='middle']
  self.assertTrue(middles)
  self.assertTrue({'alternate_totals','team_totals'} <= {r.market_key for r in middles})
  for r in middles:
   if r.market_key=='team_totals':
    names=[c.quote_map[q].selection_name for q in r.quote_ids]
    self.assertTrue(all(n.startswith('Hawks ') for n in names),names)
 def test_alternate_and_featured_lines_can_form_middle(self):
  rows=quotes()+[row('betmgm','total','over','1.9','13.5'),row('betmgm','total','under','2.1','13.5')]
  c=FixtureCatalog(raw=build_raw(rows,PEOPLE,now=NOW))
  self.assertTrue(any({c.quote_map[q].market_key for q in r.quote_ids}=={'totals','alternate_totals'} for r in c.rows if r.kind=='middle'))
 def test_missing_reference_side_does_not_invent_probability(self):
  rows=[r for r in quotes() if not(r['book_code']=='prophetx' and r['side']=='yes')]
  c=FixtureCatalog(raw=build_raw(rows,PEOPLE,now=NOW))
  self.assertFalse(any(r.market_key=='btts' and r.kind=='positive_ev' for r in c.rows))
 def test_authenticated_api_serializes_added_markets(self):
  c=FixtureCatalog(raw=build_raw(quotes(),PEOPLE,now=NOW))
  app=create_app(data_mode='database',catalog=c,session_check=lambda t:t=='member')
  client=TestClient(app,base_url='http://127.0.0.1')
  self.assertEqual(401,client.get('/api/v1/quotes').status_code)
  response=client.get('/api/v1/quotes',cookies={'corner_session':'member'})
  # The public data schemas validate every quote before endpoint serialization.
  for q in c.quotes:self.assertIn(q.market_key,ADDITIONAL_MARKETS)
  self.assertEqual(200,response.status_code)
  self.assertEqual(set(ADDITIONAL_MARKETS),{q['market_key'] for q in response.json()['data']['items']})
 def test_promo_conversion_all_five_exact_contracts(self):
  from corner.featured_promos import PromoTerms,convert_promo_back_hedge
  c=FixtureCatalog(raw=build_raw(quotes(),PEOPLE,now=NOW))
  terms=PromoTerms('terms:1','bonus_stake_not_returned',D(100),D(100),D('1.5'),D(0),'eligibility:fixture',True)
  covered=set()
  for contract in c.contracts.values():
   offers=[o for o in c.offers.values() if o.contract_id==contract.contract_id]
   a=next(o for o in offers if o.sportsbook_id=='draftkings') if any(o.sportsbook_id=='draftkings' for o in offers) else None
   if a is None:continue
   b=next(o for o in offers if o.sportsbook_id=='pinnacle' and o.selection_id!=a.selection_id)
   result=convert_promo_back_hedge(contract,a,b,terms)
   self.assertGreaterEqual(result.hedge_stake,D(0));covered.add(contract.market_key)
   if contract.market_key=='draw_no_bet':self.assertEqual(D(0),result.minimum_modeled_cash_profit)
  self.assertEqual(set(ADDITIONAL_MARKETS),covered)
 def test_normalization_team_identity_and_yes_no(self):
  e={'id':'e','sport_key':'soccer_epl','home_team':'Hawks','away_team':'Bears','commence_time':START.isoformat(),'bookmakers':[{'key':'draftkings','markets':[{'key':'team_totals','outcomes':[{'name':s,'description':team,'point':1.5,'price':2} for team in ('Hawks','Bears') for s in ('Over','Under')]},{'key':'btts','outcomes':[{'name':s,'price':2} for s in ('Yes','No')]}]}]}
  snap=normalize_featured_payload(json.dumps([e]).encode(),received_at=NOW)
  self.assertEqual(6,len(snap.quotes));self.assertEqual({'Hawks','Bears'},{q.subject_name for q in snap.quotes if q.market_key=='team_totals'})
  del e['bookmakers'][0]['markets'][0]['outcomes'][0]['description']
  with self.assertRaises(FeaturedMarketError):normalize_featured_payload(json.dumps([e]).encode(),received_at=NOW)
 def test_local_capture_family_coexists(self):
  a=row('draftkings','moneyline','home','2');a['provider_payload_id']='main';a['observed_at']=NOW+timedelta(seconds=1)
  b=row('draftkings','btts','yes','2');b['provider_payload_id']='extra'
  self.assertEqual(2,len(keep_latest_capture([a,b])))
 def test_scheduled_plan_and_cadence(self):
  e={'id':'e','sport_key':'basketball_nba','commence_time':START.isoformat()}
  jobs=[j for j in plan(NOW,['basketball_nba'],[e],additional=True) if j.kind=='additional']
  self.assertEqual(2,len(jobs));self.assertTrue(all(j.pool=='main' and j.cost==5 for j in jobs))
  self.assertEqual(60,interval('additional','standard',NOW,START));self.assertEqual(20,interval('additional','exchange',NOW,START))
  e['commence_time']=(NOW+timedelta(hours=2,seconds=1)).isoformat()
  self.assertFalse(any(j.kind=='additional' for j in plan(NOW,['basketball_nba'],[e],additional=True)))
 def test_additional_snapshot_authority_withdrawal_and_expiry(self):
  from corner.collection_readers import main_scopes
  from pipelines.collection_publication import MainPublisher
  from dataclasses import asdict
  with tempfile.TemporaryDirectory() as folder:
   g=Governor(Path(folder)/'ledger.sqlite3');g.configure_cycle('test',NOW-timedelta(days=1),NOW+timedelta(days=1));g.acquire('owner',NOW)
   event={'id':'scope-event','sport_key':'basketball_nba','home_team':'Hawks','away_team':'Bears','commence_time':START.isoformat()}
   jobs=[];rows=[]
   for group,books in [('standard',STANDARD),('exchange',EXCHANGE)]:
    j=Job('additional','basketball_nba',group,books,SCHEDULED_ADDITIONAL_MARKETS,event['id'],event['commence_time']);jobs.append(j)
    token=g.claim(j,'owner',NOW)
    payload=[{**event,'bookmakers':[{'key':books[0],'last_update':NOW.isoformat(),'markets':[{'key':'btts','outcomes':[{'name':'Yes','price':2},{'name':'No','price':2}]}]}]}]
    g.finish(j,token,'owner',NOW,{'x-requests-last':'1','x-requests-remaining':'14999999'},payload)
    r=row(books[0],'btts','yes','2');r['source_event_id']=event['id'];rows.append(r)
   self.assertEqual(2,len(main_scopes(rows,g.path,NOW)))
   self.assertEqual(2,len(main_scopes(rows,g.path,NOW+timedelta(seconds=61))))
   self.assertEqual([],main_scopes(rows,g.path,NOW+timedelta(seconds=1801)))
   calls=[];pub=MainPublisher(Path(folder)/'retained',lambda:None,lambda path,**kw:calls.append(path))
   g.publish_pending('owner',NOW,pub);self.assertEqual(2,len(calls))
   info=json.loads((calls[0]/'manifest.json').read_text());self.assertIn('/events/scope-event/odds',info['endpoint'])
   later=NOW+timedelta(seconds=120);g.acquire('owner',later);g.prepare_due(jobs[0],'owner',later)
   token=g.claim(jobs[0],'owner',later);g.finish(jobs[0],token,'owner',later,{'x-requests-last':'0','x-requests-remaining':'14999999'},[])
   self.assertFalse(any(r['book_code']=='draftkings' for r in main_scopes(rows,g.path,later)))
   g.close()
 def test_local_manual_capture_retains_every_upcoming_event_response(self):
  from pipelines.odds_ingestion import capture_additional,PARAMS
  def fetched(session,url,params):
   self.assertIn('/events/',url);self.assertEqual(set(ADDITIONAL_MARKETS),set(params['markets'].split(',')))
   event={'id':url.split('/events/')[1].split('/')[0],'sport_key':'basketball_nba','home_team':'Hawks','away_team':'Bears','commence_time':START.isoformat(),'bookmakers':[]}
   return 200,json.dumps(event).encode(),{'x-requests-last':'0','x-requests-remaining':'15000000'}
  with tempfile.TemporaryDirectory() as folder,patch('pipelines.odds_ingestion.fetch',side_effect=fetched) as request:
   path=Path(folder);(path/'manifest.json').write_text('{}')
   events=[{'id':str(i),'commence_time':START.isoformat()} for i in range(7)]
   capture_additional(path,'basketball_nba',events,PARAMS,{'x-requests-remaining':'15000000'},now=NOW)
   self.assertEqual(7,request.call_count);self.assertEqual(7,len(list((path/'additional').glob('*/response.raw'))))
 def test_durable_daily_cap_and_window(self):
  with tempfile.TemporaryDirectory() as folder:
   g=Governor(Path(folder)/'ledger.sqlite3');g.configure_cycle('test',NOW-timedelta(days=1),NOW+timedelta(days=31));g.acquire('owner',NOW)
   day=NOW.date().isoformat()
   g.db.executemany('INSERT INTO additional_events VALUES(?,?,?)',[(day,'basketball_nba',str(i)) for i in range(50)])
   j=Job('additional','basketball_nba','standard',STANDARD,SCHEDULED_ADDITIONAL_MARKETS,'new',START.isoformat())
   with self.assertRaisesRegex(Refused,'event cap'):g.claim(j,'owner',NOW)
   far=Job('additional','basketball_nba','standard',STANDARD,SCHEDULED_ADDITIONAL_MARKETS,'0',(NOW+timedelta(minutes=121)).isoformat())
   with self.assertRaisesRegex(Refused,'final two pregame hours'):g.claim(far,'owner',NOW)
   g.close()
if __name__=='__main__':unittest.main()
