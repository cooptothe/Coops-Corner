import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from api.app import create_app
from api.catalog import FixtureCatalog
from api.database import LiveCatalog


class FeedQuoteBundles(unittest.TestCase):
    def setUp(self):
        self.catalog=FixtureCatalog()
        self.client=TestClient(create_app(catalog=self.catalog),base_url='http://127.0.0.1')

    def tearDown(self):self.client.close()

    def test_each_feed_page_includes_exactly_its_referenced_quotes(self):
        for kind in ('positive_ev','arbitrage','middle'):
            with self.subTest(kind=kind):
                response=self.client.get('/api/v1/tools/'+kind,params={'include_quotes':True,'limit':1,'snapshot_id':self.catalog.snapshot_id})
                self.assertEqual(response.status_code,200,response.text)
                page=response.json()['data']
                self.assertTrue(page['items'])
                wanted={q for row in page['items'] for q in row['quote_ids']}
                self.assertEqual({q['id'] for q in page['quotes']},wanted)
                self.assertEqual(response.json()['meta']['snapshot_id'],self.catalog.snapshot_id)

    def test_unrelated_quote_inventory_is_not_serialized_into_feed_page(self):
        quote=self.catalog.quotes[0]
        for i in range(5000):self.catalog.quote_map['unused'+str(i)]=quote.model_copy(update={'id':'unused'+str(i)})
        response=self.client.get('/api/v1/tools/positive_ev?include_quotes=true&limit=1')
        self.assertEqual(response.status_code,200)
        self.assertNotIn('unused',response.text)
        self.assertLess(len(response.content),100000)

    def test_empty_feed_has_empty_quote_bundle(self):
        response=self.client.get('/api/v1/tools/positive_ev?include_quotes=true&minimum_ev_ratio=99999')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['data']['items'],[])
        self.assertEqual(response.json()['data']['quotes'],[])

    def test_default_response_is_backwards_compatible_and_snapshot_guard_still_applies(self):
        response=self.client.get('/api/v1/tools/positive_ev')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['data']['quotes'],[])
        self.assertEqual(self.client.get('/api/v1/tools/positive_ev?include_quotes=true&snapshot_id=wrong').status_code,409)

    def test_schedule_and_parlay_quote_queries_are_scoped(self):
        game=self.catalog.games[0].id
        response=self.client.get('/api/v1/quotes',params={'game_id':game,'main_lines_only':True,'limit':1000})
        self.assertEqual(response.status_code,200)
        rows=response.json()['data']['items']
        self.assertTrue(rows)
        self.assertTrue(all(q['game_id']==game and q['market_key'] in ('h2h','spreads','totals') for q in rows))
        missing=self.client.get('/api/v1/quotes?game_id=withdrawn-event')
        self.assertEqual(missing.json()['data']['total'],0)

    def test_tool_response_pins_one_catalog_generation_for_rows_quotes_and_metadata(self):
        fixture=self.catalog
        class Proxy:
            data_mode='fixture'
            calls=0
            def _current(self):self.calls+=1;return fixture
        proxy=Proxy()
        with TestClient(create_app(catalog=proxy),base_url='http://127.0.0.1') as client:
            response=client.get('/api/v1/tools/positive_ev?include_quotes=true')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(proxy.calls,1)

    def test_unauthorized_requests_do_not_rebuild_the_live_catalog(self):
        catalog=LiveCatalog.__new__(LiveCatalog)
        catalog._inner=self.catalog
        with patch.object(LiveCatalog,'_current',side_effect=AssertionError('auth must not rebuild')):
            with TestClient(create_app(data_mode='database',catalog=catalog,session_check=lambda token:False),base_url='http://127.0.0.1') as client:
                self.assertEqual(client.get('/api/v1/capabilities').status_code,401)

    def test_response_header_metadata_never_rebuilds_the_live_catalog(self):
        catalog=LiveCatalog.__new__(LiveCatalog)
        with patch.object(LiveCatalog,'_current',side_effect=AssertionError('header must not rebuild')):
            self.assertEqual(catalog.data_mode,'database')


if __name__=='__main__':unittest.main()
