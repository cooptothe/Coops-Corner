from datetime import datetime,timezone
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests import test_trends_service as source
CONTRACT=source.CONTRACT
from pipelines.trends_service import create_router,contracts
import unittest
class ResearchBoardTests(unittest.TestCase):
 def client(self,service,allowed=True):
  class Context:
   def require(self,request,*,write):
    from starlette.responses import JSONResponse
    return ({},None) if allowed else (None,JSONResponse({},status_code=401))
  app=FastAPI();app.include_router(create_router(Context(),service));return TestClient(app)
 def test_negative_ev_is_not_a_research_inventory_filter(self):
  class Service:
   calls=[]
   def research(self,item,*,cached_only):
    self.calls.append(cached_only)
    return {'research_signal':False,'model_ev':-1,'windows':{'10':{'games':10,'wins':3,'losses':7,'pushes':0,'hit_rate':.3}},'matchup':{'games':0},'season_games':[]}
  service=Service();client=self.client(service)
  with patch('pipelines.trends_service.contracts',return_value={'id':CONTRACT}):
   data=client.get('/api/refresh/v1/props/trends/board?id=id').json()
   self.assertEqual('available',data['items'][0]['status']);self.assertEqual(.3,data['items'][0]['windows']['10']['hit_rate'])
   self.assertEqual([True],service.calls);self.assertEqual(0,data['odds_provider_calls'])
   self.assertEqual(422,client.get('/api/refresh/v1/props/trends/board?warm=1&'+ '&'.join(f'id={i}' for i in range(6))).status_code)
   client.get('/api/refresh/v1/props/trends/board?id=id&warm=1');self.assertEqual(False,service.calls[-1])
 def test_unknown_fee_quotes_are_included_in_research(self):
  now=datetime.now(timezone.utc).isoformat()
  data={'events':{'e':{'sport_key':'basketball_nba','home_team':'Home','away_team':'Away','commence_time':'2030-02-02T00:00:00Z','markets':{'player_points':{'captured_at':now,'quotes':[{'book':'kalshi','player':'Player','point':'10.5','side':0,'price':'2'}]}}}}}
  with patch('pipelines.props_ingestion.load',return_value=data),patch('pipelines.trends_service.fee_policy',return_value=SimpleNamespace(commission=None,status='unmodeled')):
   items=contracts();self.assertEqual(1,len(items));self.assertIsNone(next(iter(items.values()))['commission'])
 def test_authentication_precedes_inventory_and_research(self):
  with patch('pipelines.trends_service.contracts') as inventory:
   self.assertEqual(401,self.client(None,False).get('/api/refresh/v1/props/trends/board?id=id').status_code);inventory.assert_not_called()
class UnknownFeeResearch(unittest.TestCase):
 setUp=source.Sources.setUp
 fetch=source.Sources.fetch
 def test_history_does_not_require_execution_fee_model(self):
  result=self.service.research({**CONTRACT,'commission':None})
  self.assertGreater(result['windows']['10']['games'],0);self.assertIsNone(result['model_ev']);self.assertIsNone(result['projection']['model_ev']);self.assertFalse(result['research_signal'])
