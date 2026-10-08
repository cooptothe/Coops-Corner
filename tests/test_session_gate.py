"""The sign-in requirement on the odds API and the media routes, and sessions that die with a password change."""
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.app import create_app
from corner import auth
from corner.tracker_store import TrackerStore, read_user
from pipelines import accounts
from pipelines import media as media_service

SECRET = 'gate-test-secret-' + 'g' * 32


class Gate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 't.sqlite3'
        self.store = TrackerStore(self.path)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.store.close)
        self.user = self.store.create_user('Ann', 'ann', 'hash')

    def check(self, token):
        return auth.session_user(SECRET, token, lambda uid: read_user(self.path, uid)) is not None

    def token(self, **over):
        return auth.issue_token(SECRET, self.user['id'], 'Ann', **over)

    def api(self):
        return TestClient(create_app(session_check=self.check), base_url='http://localhost')

    def test_the_odds_api_refuses_anonymous_and_forged_requests(self):
        for path in ('/api/v1/games', '/api/v1/tools/positive_ev', '/api/v1/capabilities'):
            response = self.api().get(path)
            self.assertEqual(response.status_code, 401, path)
            self.assertEqual(response.json()['error']['code'], 'auth_required')
        client = self.api()
        client.cookies.set(accounts.COOKIE, auth.issue_token('some-other-secret-' + 'q' * 30, self.user['id'], 'Ann'))
        self.assertEqual(client.get('/api/v1/games').status_code, 401)
        client.cookies.set(accounts.COOKIE, 'junk')
        self.assertEqual(client.get('/api/v1/games').status_code, 401)

    def test_a_valid_session_reaches_the_odds_api(self):
        client = self.api()
        client.cookies.set(accounts.COOKIE, self.token())
        self.assertEqual(client.get('/api/v1/games').status_code, 200)

    def test_without_a_check_the_fixture_api_stays_open(self):
        self.assertEqual(TestClient(create_app(), base_url='http://localhost').get('/api/v1/games').status_code, 200)

    def test_a_password_change_ends_old_sessions_everywhere(self):
        old = self.token()
        self.assertTrue(self.check(old))
        epoch = self.store.set_password(self.user['id'], 'new-hash')
        self.assertFalse(self.check(old))
        self.assertTrue(self.check(self.token(epoch=epoch)))
        client = self.api()
        client.cookies.set(accounts.COOKIE, old)
        self.assertEqual(client.get('/api/v1/games').status_code, 401)

    def test_an_unknown_account_or_missing_database_is_not_signed_in(self):
        ghost = auth.issue_token(SECRET, 'nobody', 'Ghost')
        self.assertFalse(self.check(ghost))
        self.assertIsNone(read_user(Path(self.tmp.name) / 'missing.sqlite3', 'x'))

    def test_media_routes_need_a_session_when_guarded(self):
        def denied(request):
            return None if request.cookies.get('ok') else accounts.reply(401, accounts.UNAUTHENTICATED)
        app = FastAPI()
        app.include_router(media_service.create_router(guard=denied))
        client = TestClient(app, base_url='http://localhost')
        self.assertEqual(client.get('/api/refresh/v1/media/resolve?kind=team&sport=basketball_nba&n=Boston').status_code, 401)
        self.assertEqual(client.get('/api/refresh/v1/media/img?u=https://a.espncdn.com/x.png').status_code, 401)
        client.cookies.set('ok', '1')
        self.assertNotEqual(client.get('/api/refresh/v1/media/img?u=https://evil.example/x.png').status_code, 401)


if __name__ == '__main__':
    unittest.main()
