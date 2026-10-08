"""Accounts: hashing, session tokens, usernames, throttling and the register / sign in / sign out endpoints."""
import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from corner import auth
from corner.tracker_store import TrackerStore
from pipelines import accounts

ORIGIN = 'http://localhost:3000'
SECRET = 'unit-test-secret-' + 'k' * 32
JSON_ORIGIN = {'Origin': ORIGIN}


class Passwords(unittest.TestCase):
    def test_hash_is_salted_and_verifies_only_the_right_password(self):
        a, b = auth.hash_password('correct horse'), auth.hash_password('correct horse')
        self.assertNotEqual(a, b)
        self.assertNotIn('correct horse', a)
        self.assertTrue(auth.verify_password('correct horse', a))
        self.assertFalse(auth.verify_password('correct horsE', a))
        self.assertFalse(auth.verify_password('', a))

    def test_malformed_or_hostile_stored_hashes_never_verify_or_raise(self):
        for stored in ('', 'plain', 'scrypt$1$1$1$AA==$AA==', 'bcrypt$a$b$c$d$e', 'scrypt$x$8$1$AA==$AA==',
                       f'scrypt${2 ** 30}$8$1$AA==$AA=='):
            self.assertFalse(auth.verify_password('pw', stored), stored)

    def test_long_unicode_passwords_are_fully_significant(self):
        base = 'é' * 60
        stored = auth.hash_password(base + 'x')
        self.assertTrue(auth.verify_password(base + 'x', stored))
        self.assertFalse(auth.verify_password(base + 'y', stored))


class Rules(unittest.TestCase):
    def test_usernames(self):
        self.assertEqual(auth.clean_username('  Coop.Fan_1  '), ('Coop.Fan_1', 'coop.fan_1'))
        for bad in ('ab', 'a' * 25, '-lead', 'has space', 'semi;colon', '<script>', '', None, 5):
            with self.assertRaises(auth.AuthError, msg=repr(bad)):
                auth.clean_username(bad)

    def test_passwords(self):
        self.assertEqual(auth.check_password('longenough', 'bob'), 'longenough')
        for bad in ('short', 'x' * 129, None, 12345678):
            with self.assertRaises(auth.AuthError, msg=repr(bad)):
                auth.check_password(bad)
        with self.assertRaises(auth.AuthError):
            auth.check_password('SameName', 'samename')


class Tokens(unittest.TestCase):
    def test_round_trip_and_expiry(self):
        token = auth.issue_token(SECRET, 'u1', 'Ann', now=1000, ttl=60)
        claims = auth.verify_token(SECRET, token, now=1059)
        self.assertEqual((claims['sub'], claims['usr'], claims['exp']), ('u1', 'Ann', 1060))
        self.assertIsNone(auth.verify_token(SECRET, token, now=1060))
        self.assertEqual(auth.TOKEN_TTL, 7 * 86400)

    def test_forged_tampered_and_alg_none_tokens_are_rejected(self):
        token = auth.issue_token(SECRET, 'u1', 'Ann')
        self.assertIsNone(auth.verify_token('another-secret-' + 'z' * 32, token))
        head, claims, sig = token.split('.')
        evil = base64.urlsafe_b64encode(json.dumps({'sub': 'admin', 'exp': 9999999999}).encode()).rstrip(b'=').decode()
        self.assertIsNone(auth.verify_token(SECRET, f'{head}.{evil}.{sig}'))
        none_head = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b'=').decode()
        self.assertIsNone(auth.verify_token(SECRET, f'{none_head}.{claims}.'))
        for junk in ('', 'a.b', 'a.b.c.d', 'not a token', None, 5):
            self.assertIsNone(auth.verify_token(SECRET, junk), junk)

    def test_signing_key_is_created_once_and_reused(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {auth.SECRET_ENV: ''}):
            path = Path(tmp) / 'sub' / 'secret'
            first = auth.load_secret(path)
            self.assertGreaterEqual(len(first), 32)
            self.assertEqual(auth.load_secret(path), first)
            with mock.patch.dict(os.environ, {auth.SECRET_ENV: 'short'}), self.assertRaises(auth.AuthError):
                auth.load_secret(path)
            with mock.patch.dict(os.environ, {auth.SECRET_ENV: 'e' * 40}):
                self.assertEqual(auth.load_secret(path), 'e' * 40)


class Throttling(unittest.TestCase):
    def test_locks_after_the_limit_and_recovers(self):
        now = [0.0]
        throttle = auth.Throttle(limit=3, window=100, lockout=60, clock=lambda: now[0])
        for _ in range(2):
            throttle.fail('ann')
        self.assertEqual(throttle.retry_after('ann'), 0)
        throttle.fail('ann')
        self.assertGreater(throttle.retry_after('ann'), 0)
        self.assertEqual(throttle.retry_after('bob'), 0)
        now[0] = 61
        self.assertEqual(throttle.retry_after('ann'), 0)

    def test_old_failures_expire_and_success_clears(self):
        now = [0.0]
        throttle = auth.Throttle(limit=3, window=100, lockout=60, clock=lambda: now[0])
        throttle.fail('a'); throttle.fail('a')
        now[0] = 200
        throttle.fail('a')
        self.assertEqual(throttle.retry_after('a'), 0)
        throttle.fail('a'); throttle.clear('a'); throttle.fail('a'); throttle.fail('a')
        self.assertEqual(throttle.retry_after('a'), 0)


class Endpoints(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TrackerStore(Path(self.tmp.name) / 't.sqlite3')
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.store.close)
        ctx = accounts.AuthContext(self.store, SECRET, {ORIGIN})
        app = FastAPI()
        app.include_router(accounts.create_router(ctx))
        self.client = TestClient(app, base_url='http://localhost')

    def post(self, path, body, client=None, headers=JSON_ORIGIN):
        return (client or self.client).post(f'/api/refresh/v1/auth/{path}', json=body, headers=headers)

    def test_register_signs_you_in_with_a_hardened_cookie(self):
        response = self.post('register', {'username': 'Coop', 'password': 'a-long-password'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['user']['username'], 'Coop')
        self.assertNotIn('password', json.dumps(response.json()))
        cookie = response.headers['set-cookie']
        for flag in ('HttpOnly', 'SameSite=strict', 'Path=/', 'Max-Age=604800'):
            self.assertIn(flag, cookie)
        me = self.client.get('/api/refresh/v1/auth/me')
        self.assertEqual(me.json()['user']['username'], 'Coop')
        # Only a hash is stored.
        stored = self.store.user_by_key('coop')['password_hash']
        self.assertTrue(stored.startswith('scrypt$') and 'a-long-password' not in stored)

    def test_usernames_are_unique_in_any_letter_case(self):
        self.assertEqual(self.post('register', {'username': 'Coop', 'password': 'a-long-password'}).status_code, 200)
        other = TestClient(self.client.app, base_url='http://localhost')
        for name in ('Coop', 'coop', 'COOP'):
            taken = self.post('register', {'username': name, 'password': 'another-password'}, other)
            self.assertEqual((taken.status_code, taken.json()['code']), (409, 'username_taken'), name)
        self.assertNotIn('set-cookie', taken.headers)

    def test_register_validates_input(self):
        for body in ({'username': 'x', 'password': 'a-long-password'}, {'username': 'okname', 'password': 'short'},
                     {'username': 'okname'}, {'password': 'a-long-password'}, {'username': 5, 'password': 'a-long-password'},
                     {'username': 'okname', 'password': 'okname'}, []):
            self.assertEqual(self.post('register', body).status_code, 400, body)
        self.assertEqual(self.client.post('/api/refresh/v1/auth/register', content=b'nope', headers=JSON_ORIGIN).status_code, 400)

    def test_login_logout_and_generic_failures(self):
        self.post('register', {'username': 'Coop', 'password': 'a-long-password'})
        fresh = TestClient(self.client.app, base_url='http://localhost')
        wrong = self.post('login', {'username': 'coop', 'password': 'wrong-password'}, fresh)
        unknown = self.post('login', {'username': 'nobody', 'password': 'wrong-password'}, fresh)
        self.assertEqual((wrong.status_code, unknown.status_code), (401, 401))
        self.assertEqual(wrong.json(), unknown.json())  # no hint whether the username exists
        self.assertEqual(fresh.get('/api/refresh/v1/auth/me').status_code, 401)
        ok = self.post('login', {'username': ' COOP ', 'password': 'a-long-password'}, fresh)
        self.assertEqual(ok.json()['user']['username'], 'Coop')
        self.assertEqual(fresh.get('/api/refresh/v1/auth/me').status_code, 200)
        self.post('logout', {}, fresh)
        self.assertEqual(fresh.get('/api/refresh/v1/auth/me').status_code, 401)

    def test_repeated_failures_lock_the_account_name_for_a_while(self):
        self.post('register', {'username': 'Coop', 'password': 'a-long-password'})
        fresh = TestClient(self.client.app, base_url='http://localhost')
        for _ in range(8):
            self.assertEqual(self.post('login', {'username': 'coop', 'password': 'nope-nope-nope'}, fresh).status_code, 401)
        locked = self.post('login', {'username': 'coop', 'password': 'a-long-password'}, fresh)
        self.assertEqual(locked.status_code, 429)
        self.assertGreater(int(locked.headers['retry-after']), 0)

    def test_deleted_or_unknown_accounts_and_tampered_cookies_are_not_signed_in(self):
        self.post('register', {'username': 'Coop', 'password': 'a-long-password'})
        ghost = TestClient(self.client.app, base_url='http://localhost')
        ghost.cookies.set(accounts.COOKIE, auth.issue_token(SECRET, 'no-such-user', 'Ghost'))
        self.assertEqual(ghost.get('/api/refresh/v1/auth/me').status_code, 401)
        ghost.cookies.set(accounts.COOKIE, 'garbage.token.value')
        self.assertEqual(ghost.get('/api/refresh/v1/auth/me').status_code, 401)

    def test_origin_and_host_guards(self):
        body = {'username': 'Coop', 'password': 'a-long-password'}
        self.assertEqual(self.post('register', body, headers={}).status_code, 403)
        self.assertEqual(self.post('register', body, headers={'Origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(self.post('login', body, headers={}).status_code, 403)
        self.assertEqual(self.post('logout', {}, headers={}).status_code, 403)
        self.assertEqual(self.client.get('/api/refresh/v1/auth/me', headers={'Host': 'evil.example'}).status_code, 403)
        self.assertIsNone(self.store.user_by_key('coop'))



if __name__ == '__main__':
    unittest.main()


if __name__ == '__main__':
    unittest.main()
