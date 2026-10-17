import unittest
from pipelines.trends_worker import warm
from pipelines.trends_service import ResearchUnavailable


class Worker(unittest.TestCase):
    def test_bounded_unique_players_and_no_paid_provider_path(self):
        class Service:
            calls=[]
            def research(self,item):
                self.calls.append(item['player'])
                if item['player']=='P1':raise ResearchUnavailable('missing')
        service=Service()
        items=[{'sport_key':'basketball_nba','player':f'P{i//3}','starts_at':f'2030-01-{i+1:02}'} for i in range(9)]
        result=warm(service,items,limit=2)
        self.assertEqual(service.calls,['P0','P1'])
        self.assertEqual(result,{'players_checked':2,'available':1,'unavailable':1,'odds_provider_calls':0})
