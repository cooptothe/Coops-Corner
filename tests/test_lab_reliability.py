from unittest import TestCase
from unittest.mock import patch
from tests.test_lab_research_board import ResearchBoardTests
from tests.test_trends_service import Sources, payload
from pipelines.trends_service import normalize_games
from pipelines.media import UpstreamError

class Paging(TestCase):
    def test_pages_remain_pinned_when_collection_changes(self):
        client=ResearchBoardTests().client(None)
        items={str(i):dict(id=str(i),price='2',observed_at='2026-10-26',starts_at='2026-10-27') for i in range(3)}
        with patch('pipelines.trends_service.contracts',return_value=items) as load:
            first=client.get('/api/refresh/v1/props/trends/options?limit=1').json()
            load.return_value={}
            rest=client.get('/api/refresh/v1/props/trends/options',params={'offset':1,'limit':2,'snapshot':first['snapshot_id']}).json()
            self.assertEqual([x['id'] for x in rest['contracts']],['1','2'])
            self.assertEqual(rest['total'],3)
            self.assertEqual(load.call_count,1)
            self.assertEqual(client.get('/api/refresh/v1/props/trends/options?snapshot=missing').status_code,409)

    def test_unauthorized_options_never_load_catalog(self):
        with patch('pipelines.trends_service.contracts') as load:
            self.assertEqual(ResearchBoardTests().client(None,False).get('/api/refresh/v1/props/trends/options').status_code,401)
            load.assert_not_called()

class History(TestCase):
    setUp=Sources.setUp
    fetch=Sources.fetch

    def test_saved_history_survives_outage_and_retains_timestamp(self):
        initial=self.service.cached('games:test',10,lambda:{'games':[1]})
        self.now+=11
        calls=[]
        def fail():
            calls.append(1)
            raise UpstreamError('offline')
        self.assertEqual(self.service.cached('games:test',10,fail),initial)
        self.assertEqual(self.service.cached('games:test',10,fail,cached_only=True),initial)
        self.assertEqual(self.service.cached('games:test',10,fail),initial)
        self.assertEqual(len(calls),1)

    def test_atomic_threes_are_not_dropped(self):
        data=payload()
        data['names']=['minutes','threePointFieldGoalsMade']
        data['seasonTypes'][0]['categories'][0]['events'][0]['stats']=['30','4']
        games=normalize_games(data,'basketball_nba','player_threes',2030)
        self.assertEqual(len(games),1)
        self.assertEqual(float(games[0]['value']),4)
