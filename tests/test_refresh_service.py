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


class RefreshOverlap(unittest.TestCase):
    """The next league is captured while the previous one is ingested; nothing else about a run changes."""
    LEAGUES = ('basketball_nba', 'baseball_mlb', 'icehockey_nhl')
    setUp = RefreshGuards.setUp
    capture = RefreshGuards.capture

    def test_next_capture_starts_while_the_previous_ingest_runs(self):
        import threading
        captured_second = threading.Event()
        order, active, widest = [], [0], [0]
        guard = threading.Lock()

        def capture(dest, params, sport=None):
            order.append(('capture', sport))
            if sport == self.LEAGUES[1]:
                captured_second.set()
            return RefreshGuards.capture(self, dest, params, sport=sport)

        def ingest(dest):
            with guard:
                active[0] += 1
                widest[0] = max(widest[0], active[0])
            order.append(('ingest', dest.name))
            try:
                if dest.name == self.LEAGUES[0]:
                    # Can only finish if the second capture really began meanwhile.
                    self.assertTrue(captured_second.wait(5), 'next capture did not overlap the ingest')
            finally:
                with guard:
                    active[0] -= 1

        code, body = svc.run_refresh(capture, ingest, now=1000.0, sports=self.LEAGUES)
        self.assertEqual(200, code)
        self.assertEqual(1, widest[0])
        self.assertEqual({k: 'ok' for k in self.LEAGUES}, body['last_results'])
        self.assertEqual(list(self.LEAGUES), list(body['last_results']))

    def test_ingest_failure_is_recorded_and_the_run_continues(self):
        def ingest(dest):
            if dest.name == self.LEAGUES[1]:
                raise RuntimeError('db')

        code, body = svc.run_refresh(self.capture, ingest, now=1000.0, sports=self.LEAGUES)
        self.assertEqual(200, code)
        self.assertEqual(['ok', 'ingest_failed (RuntimeError)', 'ok'], list(body['last_results'].values()))
        self.assertEqual(3, len(self.calls))
        self.assertIn(self.LEAGUES[1], body['last_error'])

    def test_a_failed_capture_still_waits_for_and_keeps_the_earlier_ingest(self):
        done = []

        def capture(dest, params, sport=None):
            if sport == self.LEAGUES[1]:
                raise RuntimeError('provider')
            return RefreshGuards.capture(self, dest, params, sport=sport)

        def ingest(dest):
            import time
            time.sleep(0.2)
            done.append(dest.name)

        code, body = svc.run_refresh(capture, ingest, now=1000.0, sports=self.LEAGUES)
        self.assertEqual([self.LEAGUES[0]], done)
        self.assertEqual({self.LEAGUES[0]: 'ok', self.LEAGUES[1]: 'capture_failed (RuntimeError)'}, body['last_results'])
        self.assertEqual(200, code)

    def test_credit_floor_stops_after_the_current_league_and_still_ingests_it(self):
        ingested = []

        def capture(dest, params, sport=None):
            RefreshGuards.capture(self, dest, params, sport=sport)
            low = json.loads((dest / 'manifest.json').read_text())
            low['response_headers']['x-requests-remaining'] = '2'
            (dest / 'manifest.json').write_text(json.dumps(low))

        code, body = svc.run_refresh(capture, lambda d: ingested.append(d.name), now=1000.0, sports=self.LEAGUES)
        self.assertEqual(1, len(self.calls))
        self.assertEqual([self.LEAGUES[0]], ingested)
        self.assertEqual({self.LEAGUES[0]: 'ok', 'stopped': 'credit_floor'}, body['last_results'])


class PublicOrigins(unittest.TestCase):
    """A tunnel's https origin can be allowed exactly; nothing broader slips in."""
    def test_only_plain_https_origins_are_taken(self):
        got = svc.public_origins('https://abc-123.ngrok-free.app, https://x.ngrok.dev/ ,https://h.example:8443')
        self.assertEqual({'https://abc-123.ngrok-free.app', 'https://x.ngrok.dev', 'https://h.example:8443'}, got)

    def test_everything_else_is_ignored(self):
        for bad in ('', None, 'http://abc.ngrok-free.app', 'https://*.ngrok-free.app', 'https://abc.ngrok-free.app/path',
                    'https://abc.ngrok-free.app?x=1', 'https://user:pw@abc.ngrok-free.app', 'abc.ngrok-free.app',
                    'https://', 'javascript:alert(1)', 'https://abc.ngrok-free.app:notaport'):
            self.assertEqual(set(), svc.public_origins(bad), bad)

    def test_local_origins_stay_allowed_and_an_unlisted_tunnel_is_not(self):
        self.assertIn('http://localhost:3000', svc.ALLOWED_ORIGINS)
        self.assertNotIn('https://other.ngrok-free.app', svc.ALLOWED_ORIGINS)

    def test_a_listed_tunnel_may_write_and_an_unlisted_one_may_not(self):
        from fastapi.testclient import TestClient
        with patch.object(svc, 'ALLOWED_ORIGINS', svc.ALLOWED_ORIGINS | svc.public_origins('https://me.ngrok-free.app')):
            client = TestClient(svc.create_app(), base_url='http://localhost')
            body = {'username': 'tunnel-test', 'password': 'a long enough password'}
            allowed = client.post('/api/refresh/v1/auth/login', json=body, headers={'origin': 'https://me.ngrok-free.app'})
            denied = client.post('/api/refresh/v1/auth/login', json=body, headers={'origin': 'https://evil.ngrok-free.app'})
        self.assertNotEqual(403, allowed.status_code)  # passes the origin check (then fails as an unknown account)
        self.assertEqual(403, denied.status_code)

    def test_session_cookie_is_secure_behind_an_https_tunnel(self):
        from types import SimpleNamespace
        from pipelines.accounts import _secure

        def request(scheme, forwarded=None):
            headers = {} if forwarded is None else {'x-forwarded-proto': forwarded}
            return SimpleNamespace(url=SimpleNamespace(scheme=scheme), headers=headers)

        self.assertTrue(_secure(request('http', 'https')))
        self.assertTrue(_secure(request('http', 'https,http')))
        self.assertTrue(_secure(request('https')))
        self.assertFalse(_secure(request('http')))
        self.assertFalse(_secure(request('http', 'http,https')))


if __name__ == '__main__':
    unittest.main()
