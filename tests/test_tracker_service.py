"""Tracker HTTP service: guards, validation errors, round trips and live status, with no network."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from corner import auth
from corner.tracker_store import TrackerStore
from pipelines import accounts
from pipelines import media as media_service
from pipelines import tracker_service as svc

ORIGIN = 'http://localhost:3000'
SECRET = 'test-secret-' + 'x' * 40


def signed_in(store, name, client_factory):
    """A test client holding a valid session cookie for a fresh account."""
    user = store.create_user(name, name.lower(), 'unused-hash')
    client = client_factory()
    client.cookies.set(accounts.COOKIE, auth.issue_token(SECRET, user['id'], user['username']))
    return client, store.ledger(user['id'])


def bet_payload(key='k1', **extra):
    body = {'client_key': key, 'strategy': 'ev', 'matchup': 'Minnesota Timberwolves at Indiana Pacers',
            'selection': 'Jaden McDaniels Over 14.5 PTS', 'book': 'fanduel', 'odds': '2.1', 'stake': '50',
            'sport_key': 'basketball_nba', 'market': 'Player points'}
    body.update(extra)
    return body


class Service(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = TrackerStore(Path(self.dir.name) / 't.sqlite3')
        self.board = {}
        app = FastAPI()
        self.ctx = accounts.AuthContext(self.store, SECRET, {ORIGIN})
        app.include_router(svc.create_router(self.ctx))
        self.anonymous = lambda: TestClient(app, base_url='http://localhost')
        self.client, self.ledger = signed_in(self.store, 'Ann', self.anonymous)
        self.write = {'Origin': ORIGIN}
        self.addCleanup(self.dir.cleanup)
        self.addCleanup(self.store.close)

    def url(self, tail=''):
        return '/api/refresh/v1/tracker' + tail

    def test_round_trip_log_settle_cash_and_state(self):
        saved = self.client.post(self.url('/bets'), json=[bet_payload()], headers=self.write)
        self.assertEqual(saved.status_code, 200)
        bet = saved.json()['bets'][0]
        again = self.client.post(self.url('/bets'), json=[bet_payload()], headers=self.write).json()['bets'][0]
        self.assertEqual(again['id'], bet['id'])
        settled = self.client.post(self.url(f"/bets/{bet['id']}/settle"), json={'result': 'won'}, headers=self.write)
        self.assertEqual(settled.json()['bet']['returned_cents'], 10500)
        cash = self.client.post(self.url('/cash'), json={'client_key': 'c1', 'kind': 'deposit', 'book': 'fanduel', 'amount': '500'}, headers=self.write)
        self.assertEqual(cash.json()['cash']['amount_cents'], 50000)
        state = self.client.get(self.url('/state')).json()
        self.assertEqual((len(state['bets']), len(state['cash'])), (1, 1))
        self.assertEqual(self.client.get(self.url('/export')).json()['format'], 'corner.tracker/1')
        self.assertEqual(self.client.post(self.url(f"/bets/{bet['id']}/reopen"), headers=self.write).json()['bet']['status'], 'pending')
        self.assertEqual(self.client.delete(self.url(f"/bets/{bet['id']}"), headers=self.write).status_code, 200)
        self.assertEqual(self.client.delete(self.url(f"/bets/{bet['id']}"), headers=self.write).status_code, 404)

    def test_validation_errors_are_plain_400s(self):
        bad = self.client.post(self.url('/bets'), json=[bet_payload(stake='1e3')], headers=self.write)
        self.assertEqual(bad.status_code, 400)
        self.assertIn('stake', bad.json()['error'])
        self.assertEqual(self.client.post(self.url('/bets'), content=b'not json', headers=self.write).status_code, 400)
        american = self.client.post(self.url('/bets'), json=[bet_payload(odds='+110')], headers=self.write)
        self.assertEqual(american.status_code, 400)
        self.assertIn('decimal', american.json()['error'])
        self.assertEqual(self.client.post(self.url('/cash'), json={'client_key': 'x', 'kind': 'transfer', 'book': 'a', 'to_book': 'a', 'amount': '5'}, headers=self.write).status_code, 400)

    def test_every_route_needs_a_signed_in_account_and_stays_in_it(self):
        guest = self.anonymous()
        for method, path in (('get', '/state'), ('get', '/export'), ('get', '/live')):
            self.assertEqual(getattr(guest, method)(self.url(path)).status_code, 401, path)
        for method, path in (('post', '/bets'), ('post', '/cash'), ('post', '/clv'), ('post', '/bets/x/settle'),
                             ('post', '/bets/x/reopen'), ('delete', '/bets/x'), ('delete', '/cash/x'), ('patch', '/bets/x')):
            self.assertEqual(getattr(guest, method)(self.url(path), headers=self.write).status_code, 401, path)
        forged = self.anonymous()
        forged.cookies.set(accounts.COOKIE, auth.issue_token('some-other-secret-' + 'y' * 30, 'ann', 'Ann'))
        self.assertEqual(forged.get(self.url('/state')).status_code, 401)
        # Another account never sees or touches Ann's data.
        mine = self.client.post(self.url('/bets'), json=[bet_payload()], headers=self.write).json()['bets'][0]
        bob, _ = signed_in(self.store, 'Bob', self.anonymous)
        self.assertEqual(bob.get(self.url('/state')).json(), {'bets': [], 'cash': []})
        self.assertEqual(bob.post(self.url(f"/bets/{mine['id']}/settle"), json={'result': 'won'}, headers=self.write).status_code, 404)
        self.assertEqual(bob.delete(self.url(f"/bets/{mine['id']}"), headers=self.write).status_code, 404)
        self.assertEqual(self.client.get(self.url('/state')).json()['bets'][0]['status'], 'pending')

    def test_writes_need_the_local_origin_and_every_request_needs_a_local_host(self):
        self.assertEqual(self.client.post(self.url('/bets'), json=[bet_payload()]).status_code, 403)
        self.assertEqual(self.client.post(self.url('/bets'), json=[bet_payload()], headers={'Origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(self.client.delete(self.url('/cash/x')).status_code, 403)
        self.assertEqual(self.client.get(self.url('/state')).status_code, 200)
        rebinding = self.client.get(self.url('/state'), headers={'Host': 'evil.example:8766'})
        self.assertEqual(rebinding.status_code, 403)
        self.assertEqual(self.client.get(self.url('/state'), headers={'Host': '127.0.0.1:8766'}).status_code, 200)
        self.assertEqual(self.client.get(self.url('/state'), headers={'Host': '[::1]:8766'}).status_code, 200)


class Clv(unittest.TestCase):
    GAME = '11111111-1111-4111-8111-111111111111'

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = TrackerStore(Path(self.dir.name) / 't.sqlite3')
        self.calls = []
        self.start = datetime.now(timezone.utc) - timedelta(hours=3)
        app = FastAPI()
        app.include_router(svc.create_router(accounts.AuthContext(self.store, SECRET, {ORIGIN}), close_fetch=self.close))
        self.client, self.ledger = signed_in(self.store, 'Ann', lambda: TestClient(app, base_url='http://localhost'))
        self.addCleanup(self.dir.cleanup)
        self.addCleanup(self.store.close)

    def close(self, game_id, market_key):
        self.calls.append((game_id, market_key))
        if self.fail:
            raise RuntimeError('db down')
        pin = lambda side, odds, point=None: {'book': 'pinnacle', 'side': side, 'point': point, 'decimal_odds': odds}
        return self.start, [pin('home', Decimal('1.95')), pin('away', Decimal('1.95'))]

    fail = False

    def log(self, key, **ref):
        body = bet_payload(key, odds='2.1', starts_at=self.start.isoformat(),
                           ref={'game_id': self.GAME, 'market_key': 'h2h', 'side': 'home', **ref})
        return self.client.post('/api/refresh/v1/tracker/bets', json=[body], headers={'Origin': ORIGIN}).json()['bets'][0]

    def test_started_main_line_bets_get_a_stored_measurement_once(self):
        first, second = self.log('a'), self.log('b')
        out = self.client.post('/api/refresh/v1/tracker/clv', headers={'Origin': ORIGIN}).json()['bets']
        self.assertEqual({b['id'] for b in out}, {first['id'], second['id']})
        self.assertEqual(out[0]['clv']['pct'], '0.05')
        self.assertEqual(len(self.calls), 1)  # one lookup serves both bets on the same game and market
        self.assertEqual(self.client.post('/api/refresh/v1/tracker/clv', headers={'Origin': ORIGIN}).json()['bets'], [])
        self.assertEqual(self.ledger.bet(first['id'])['clv']['books'], ['pinnacle'])

    def test_records_unavailable_for_unmatchable_bets_and_waits_for_future(self):
        self.log('prop', market_key='prop')
        self.log('lay', lay=True)
        future = bet_payload('f', odds='2.1', starts_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
                             ref={'game_id': self.GAME, 'market_key': 'h2h', 'side': 'home'})
        manual = bet_payload('m', odds='2.1', starts_at=self.start.isoformat(), ref={'game_id': 'not-a-uuid', 'market_key': 'h2h', 'side': 'home'})
        self.client.post('/api/refresh/v1/tracker/bets', json=[future, manual], headers={'Origin': ORIGIN})
        out = self.client.post('/api/refresh/v1/tracker/clv', headers={'Origin': ORIGIN}).json()['bets']
        self.assertEqual(len(out), 3)
        self.assertTrue(all(b['clv']['status'] == 'unavailable' for b in out))
        self.assertEqual(self.calls, [])

    def test_database_failure_is_reported_and_nothing_is_recorded(self):
        bet = self.log('a')
        self.fail = True
        response = self.client.post('/api/refresh/v1/tracker/clv', headers={'Origin': ORIGIN})
        self.assertEqual(response.status_code, 502)
        self.assertIsNone(self.ledger.bet(bet['id'])['clv'])
        self.fail = False
        self.assertEqual(len(self.client.post('/api/refresh/v1/tracker/clv', headers={'Origin': ORIGIN}).json()['bets']), 1)

    def test_origin_is_required(self):
        self.assertEqual(self.client.post('/api/refresh/v1/tracker/clv').status_code, 403)


class LiveStatus(unittest.TestCase):
    def setUp(self):
        self.calls = []
        start = (datetime.now(timezone.utc) - timedelta(hours=4)).replace(microsecond=0)
        self.start = start.isoformat()
        self.event = {'id': '401', 'date': self.start, 'competitions': [{'competitors': [
            {'homeAway': 'home', 'team': {'displayName': 'Indiana Pacers'}, 'score': '123'},
            {'homeAway': 'away', 'team': {'displayName': 'Minnesota Timberwolves'}, 'score': '112'}],
            'status': {'type': {'state': 'post', 'shortDetail': 'Final', 'completed': True}}}]}
        self.summary = {'boxscore': {'players': [{'statistics': [{'name': '', 'keys': ['points'], 'athletes': [
            {'athlete': {'displayName': 'Jaden McDaniels'}, 'stats': ['16']}]}]}]}}

    def fetch(self, url, ttl):
        self.calls.append(url)
        if '/scoreboard' in url:
            return {'events': [self.event]}
        if '/summary' in url:
            return self.summary
        raise AssertionError(url)

    def bet(self, **ref):
        return {'id': 'b1', 'status': 'pending', 'starts_at': self.start, 'sport_key': 'basketball_nba',
                'matchup': 'Minnesota Timberwolves at Indiana Pacers', 'ref': ref}

    def test_prop_bet_gets_progress_and_a_suggested_result(self):
        out = svc.live_view([self.bet(prop_market='player_points', player='Jaden McDaniels', side='over', point=14.5)], self.fetch)
        self.assertEqual(out['b1']['progress']['value'], 16)
        self.assertEqual(out['b1']['suggest']['result'], 'won')
        self.assertTrue(any('/summary' in c for c in self.calls))

    def test_main_line_needs_no_box_score_call(self):
        out = svc.live_view([self.bet(market_key='spreads', side='home', point=-10.5)], self.fetch)
        self.assertEqual(out['b1']['suggest']['result'], 'won')
        self.assertFalse(any('/summary' in c for c in self.calls))

    def test_skips_future_settled_and_unsupported_bets(self):
        future = dict(self.bet(), id='f', starts_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
        done = dict(self.bet(), id='d', status='won')
        tennis = dict(self.bet(), id='t', sport_key='tennis_atp')
        self.assertEqual(svc.live_view([future, done, tennis], self.fetch), {})
        self.assertEqual(self.calls, [])

    def test_unmatched_game_reports_unknown_and_upstream_failure_does_not_raise(self):
        self.event['competitions'][0]['competitors'][0]['team']['displayName'] = 'Boston Celtics'
        self.assertEqual(svc.live_view([self.bet(market_key='h2h', side='home')], self.fetch)['b1']['state'], 'unknown')

        def down(url, ttl):
            raise media_service.UpstreamError('HTTP 503')
        self.assertEqual(svc.live_view([self.bet(market_key='h2h', side='home')], down)['b1']['state'], 'unknown')

    def test_scoreboard_dates_cover_late_us_games(self):
        self.assertEqual(svc.scoreboard_dates('2026-10-08T01:30:00+00:00'), ['20261007', '20261008'])


if __name__ == '__main__':
    unittest.main()
