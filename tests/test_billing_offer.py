import json
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse
from pipelines.billing_service import create_router


class Context:
    def __init__(self, allowed): self.allowed = allowed
    def require(self, request, *, write):
        return ({'id':'fixture'},None) if self.allowed else (None,JSONResponse({'error':'Sign in'},status_code=401))


class BillingOffer(unittest.TestCase):
    def client(self, allowed):
        app = FastAPI()
        app.include_router(create_router(Context(allowed)))
        return TestClient(app)

    def test_offer_is_authenticated_and_cannot_initiate_payment(self):
        self.assertEqual(self.client(False).get('/api/refresh/v1/billing/status').status_code,401)
        with patch.dict('os.environ', {'CORNER_PRIVATE_BETA':'1'}):
            client = self.client(True)
            response = client.get('/api/refresh/v1/billing/status')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['cache-control'],'no-store')
        body = response.json()
        self.assertEqual(body['trial_days'],2)
        self.assertEqual(body['price_usd_cents'],5000)
        self.assertEqual(body['standard_monthly_usd_cents'],12500)
        self.assertEqual(body['founder_monthly_usd_cents'],5000)
        self.assertEqual(body['package_label'],'Pregame standard markets')
        self.assertEqual(body['launch_monthly_usd_cents'],12500)
        self.assertEqual(set(body['assets']),{'XRP','HBAR','XLM'})
        self.assertFalse(body['payments_enabled'])
        self.assertNotIn('address',json.dumps(body))
        self.assertEqual(client.post('/api/refresh/v1/billing/status',json={}).status_code,405)

    def test_local_mode_stays_outside_private_beta(self):
        with patch.dict('os.environ', {'CORNER_PRIVATE_BETA':'0'}):
            self.assertFalse(self.client(True).get('/api/refresh/v1/billing/status').json()['private_beta'])

    def test_founder_rate_is_server_selected(self):
        ctx = Context(True)
        ctx.require = lambda request, write: ({'id':'fixture', 'founder':True}, None)
        app = FastAPI()
        app.include_router(create_router(ctx))
        body = TestClient(app).get('/api/refresh/v1/billing/status').json()
        self.assertTrue(body['founder'])
        self.assertEqual(body['launch_monthly_usd_cents'],5000)
        self.assertFalse(body['payments_enabled'])

    def test_real_payment_mutations_remain_disabled(self):
        client = self.client(True)
        for path in ('requests','requests/fixture/submit','requests/fixture/cancel'):
            response = client.post('/api/refresh/v1/billing/'+path,json={'settled':True})
            self.assertEqual(response.status_code,503)
            self.assertEqual(response.json()['code'],'payments_disabled')
            self.assertNotIn('address',json.dumps(response.json()))
        self.assertEqual(self.client(False).post('/api/refresh/v1/billing/requests',json={}).status_code,401)
