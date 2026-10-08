"""Refresh guard tests: run with .venv-api (needs fastapi); no provider or database access."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pipelines import refresh_service as svc


class RefreshGuards(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / 'retained').mkdir()
        for name, value in (('ROOT', root), ('STATE', root / 'retained' / 'refresh_state.json')):
            p = patch.object(svc, name, value); p.start(); self.addCleanup(p.stop)
        self.calls = []

    def capture(self, dest, params, sport=None):
        self.calls.append((sport, params))
        dest.mkdir(parents=True)
        (dest / 'response.body').write_text('[{}]')
        (dest / 'manifest.json').write_text(json.dumps(
            {'received_at': '2026-10-06T00:00:00+00:00', 'response_headers': {'x-requests-remaining': '90'}}))

    def test_success_then_cooldown(self):
        code, body = svc.run_refresh(self.capture, lambda d: None, now=1000.0)
        self.assertEqual(code, 200)
        self.assertEqual(len(self.calls), len(svc.SPORTS))
        self.assertIn('commenceTimeFrom', self.calls[0][1])
        self.assertEqual(body['quota']['x-requests-remaining'], '90')
        code, body = svc.run_refresh(self.capture, lambda d: None, now=1001.0)
        self.assertEqual(code, 429)
        self.assertEqual(len(self.calls), len(svc.SPORTS))

    def test_daily_cap(self):
        for i in range(svc.DAILY_CAP):
            self.assertEqual(svc.run_refresh(self.capture, lambda d: None, now=1000.0 + i * 10000)[0], 200)
        self.assertEqual(svc.run_refresh(self.capture, lambda d: None, now=1000.0 + 99999)[0], 429)

    def test_failure_counts_and_hides_detail(self):
        def boom(dest, params, sport=None): raise RuntimeError('secret detail')
        code, body = svc.run_refresh(boom, lambda d: None, now=1000.0)
        self.assertEqual(code, 502)
        self.assertNotIn('secret', json.dumps(body))
        self.assertEqual(body['attempts_today'], 1)

    def test_failed_capture_stops_run(self):
        calls = []
        def boom(dest, params, sport=None):
            calls.append(sport); raise RuntimeError('x')
        svc.run_refresh(boom, lambda d: None, now=1000.0)
        self.assertEqual(len(calls), 1)

    def test_out_of_season_is_skipped_not_failed(self):
        from pipelines.odds_ingestion import InactiveSport
        def idle(dest, params, sport=None): raise InactiveSport('off')
        code, body = svc.run_refresh(idle, lambda d: None, now=1000.0)
        self.assertEqual(code, 200)
        self.assertEqual(set(body['last_results'].values()), {'not_in_season'})

    def test_league_selection(self):
        code, _ = svc.run_refresh(self.capture, lambda d: None, now=1000.0, sports=('basketball_nba',))
        self.assertEqual(code, 200)
        self.assertEqual([c[0] for c in self.calls], ['basketball_nba'])
        for bad in ((), ('nope',)):
            self.assertEqual(svc.run_refresh(self.capture, lambda d: None, now=9e9, sports=bad)[0], 400)
        self.assertEqual(len(self.calls), 1)

    def test_origin_required(self):
        from fastapi.testclient import TestClient
        client = TestClient(svc.create_app())
        self.assertEqual(client.post('/api/refresh/v1/odds').status_code, 403)
        self.assertEqual(client.post('/api/refresh/v1/odds', headers={'origin': 'http://evil.test'}).status_code, 403)

    def test_spending_credits_needs_a_signed_in_account(self):
        from fastapi.testclient import TestClient
        client = TestClient(svc.create_app(), base_url='http://localhost')
        local = {'origin': 'http://localhost:3000'}
        self.assertEqual(client.post('/api/refresh/v1/odds', json={'sports': ['basketball_nba']}, headers=local).status_code, 401)
        self.assertEqual(client.post('/api/refresh/v1/props', json={}, headers=local).status_code, 401)
        client.cookies.set('corner_session', 'forged.session.token')
        self.assertEqual(client.post('/api/refresh/v1/odds', json={'sports': ['basketball_nba']}, headers=local).status_code, 401)
        self.assertEqual(self.calls, [])

    def test_reads_and_media_need_a_signed_in_account_too(self):
        from fastapi.testclient import TestClient
        client = TestClient(svc.create_app(), base_url='http://localhost')
        for path in ('/api/refresh/v1/status', '/api/refresh/v1/props/status', '/api/refresh/v1/props',
                     '/api/refresh/v1/media/resolve?kind=team&sport=basketball_nba&n=Boston',
                     '/api/refresh/v1/media/img?u=https://a.espncdn.com/x.png'):
            self.assertEqual(client.get(path).status_code, 401, path)


if __name__ == '__main__':
    unittest.main()
