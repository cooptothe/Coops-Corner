import gzip
import json
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse
from api.compression import MarketCompression


class MarketCompressionTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.add_middleware(MarketCompression)
        self.body = {'quotes': [{'book': 'fanduel', 'price': '1.91', 'line': '25.5'}] * 500}
        @app.api_route('/{path:path}', methods=['GET', 'POST'])
        def data(path: str):
            return JSONResponse(self.body, headers={'Cache-Control': 'no-store'})
        self.client = TestClient(app)

    def test_large_market_data_round_trips_and_is_not_cached(self):
        response = self.client.get('/api/v1/quotes', headers={'Accept-Encoding': 'gzip'})
        self.assertEqual('gzip', response.headers['content-encoding'])
        self.assertEqual('no-store', response.headers['cache-control'])
        self.assertIn('Accept-Encoding', response.headers['vary'])
        self.assertEqual(self.body, response.json())
        self.assertLess(int(response.headers['content-length']), len(response.content) / 5)

    def test_private_and_write_responses_bypass_compression(self):
        for path in ['/api/refresh/v1/auth/me', '/api/refresh/v1/tracker', '/api/refresh/v1/billing']:
            response = self.client.get(path)
            self.assertNotIn('content-encoding', response.headers)
        self.assertNotIn('content-encoding', self.client.post('/api/refresh/v1/props').headers)

    def test_identity_clients_and_small_responses_are_unchanged(self):
        response = self.client.get('/api/v1/quotes', headers={'Accept-Encoding': 'identity'})
        self.assertNotIn('content-encoding', response.headers)
        self.assertEqual(self.body, response.json())
        self.body.clear()
        self.assertNotIn('content-encoding', self.client.get('/api/v1/quotes').headers)

    def test_all_market_route_families_support_compression(self):
        for path in ['/api/v1/tools/middle', '/api/v1/games', '/api/v1/games/game/odds', '/api/v1/live-stoppages', '/api/refresh/v1/props', '/api/refresh/v1/props/trends/options', '/api/refresh/v1/props/trends/board']:
            self.assertEqual('gzip', self.client.get(path).headers.get('content-encoding'), path)
