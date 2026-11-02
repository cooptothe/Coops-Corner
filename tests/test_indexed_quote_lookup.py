from pathlib import Path
import unittest
from fastapi.testclient import TestClient
from api.app import create_app
from api.catalog import FixtureCatalog
from api.database import QUOTE_SQL

class IndexedQuoteLookup(unittest.TestCase):
    def test_quote_query_filters_state_after_the_indexed_winner(self):
        self.assertIn('corner.trusted_quote_for_stream(o.id, b.id)',QUOTE_SQL)
        self.assertNotIn('trusted_current_quotes latest',QUOTE_SQL)
        self.assertIn("qs.code = 'active'",QUOTE_SQL)
        sql=(Path(__file__).resolve().parents[1]/'db/migrations/017_corner_indexed_trusted_quote_stream.sql').read_text()
        self.assertIn('o.outcome_id = requested_outcome AND o.sportsbook_id = requested_book',sql)
        self.assertIn("judgment.id IS NULL OR kind.code = 'reinstated'",sql)
        self.assertIn('ORDER BY o.observed_at DESC, o.id DESC\nLIMIT 1',sql)
        self.assertNotIn("qs.code = 'active'",sql)
        self.assertIn('SET search_path = pg_catalog',sql)
        self.assertIn('FROM PUBLIC',sql)

    def test_capabilities_and_games_pin_one_immutable_snapshot_per_request(self):
        base=FixtureCatalog()
        class Proxy:
            data_mode='fixture'
            def __init__(self):self._inner=base;self.calls=0
            def _current(self):self.calls+=1;return self._inner
            def __getattr__(self,name):return getattr(self._current(),name)
        proxy=Proxy();client=TestClient(create_app(catalog=proxy))
        for path in ('/api/v1/capabilities','/api/v1/games'):
            proxy.calls=0
            response=client.get(path,headers={'host':'127.0.0.1'})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(proxy.calls,1)
            self.assertEqual(response.json()['meta']['snapshot_id'],base.snapshot_id)
