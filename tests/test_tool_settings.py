"""Saved tool settings and presets: validation, per-account isolation and the HTTP routes."""
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from corner import auth, tool_settings
from corner.tracker_store import TrackerError, TrackerStore
from pipelines import accounts, settings_service

ORIGIN = 'http://localhost:3000'
SECRET = 'settings-test-secret-' + 's' * 32
WRITE = {'Origin': ORIGIN}


class Validation(unittest.TestCase):
    def test_settings_must_be_small_plain_objects(self):
        self.assertEqual(tool_settings.clean_settings({'a': [1, 'x', None, True, 2.5], 'b': {'c': 'd'}}), {'a': [1, 'x', None, True, 2.5], 'b': {'c': 'd'}})
        too_deep = {'a': {'b': {'c': {'d': {'e': 1}}}}}
        for bad in ([], 'text', None, {1: 2}, {'': 1}, {'a': object()}, {'a': float('nan')}, {'a': 'x' * 301},
                    {'a': list(range(301))}, {'k' + str(i): 1 for i in range(61)}, too_deep, {'a': 'y' * 200, 'b': ['z' * 200] * 60}):
            with self.assertRaises(tool_settings.SettingsError, msg=repr(bad)[:60]):
                tool_settings.clean_settings(bad)

    def test_names_and_tools(self):
        self.assertEqual(tool_settings.clean_name('  My   Setup '), ('My Setup', 'my setup'))
        for bad in ('', '   ', 'x' * 41, 'bell\x07name', None, 5):
            with self.assertRaises(tool_settings.SettingsError, msg=repr(bad)):
                tool_settings.clean_name(bad)
        self.assertEqual(tool_settings.clean_tool('props'), 'props')
        with self.assertRaises(tool_settings.SettingsError):
            tool_settings.clean_tool('../etc')


class Store(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = TrackerStore(Path(self.tmp.name) / 't.sqlite3')
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.db.close)
        self.ann = self.db.ledger(self.db.create_user('Ann', 'ann', 'h')['id'])
        self.bob = self.db.ledger(self.db.create_user('Bob', 'bob', 'h')['id'])

    def test_settings_are_saved_replaced_and_private(self):
        self.assertEqual(self.ann.settings(), {'tools': {}, 'presets': {}})
        self.ann.put_settings('props', {'minEv': '2'})
        self.ann.put_settings('props', {'minEv': '3', 'offBooks': ['fanduel']})
        self.assertEqual(self.ann.settings()['tools'], {'props': {'minEv': '3', 'offBooks': ['fanduel']}})
        self.assertEqual(self.bob.settings(), {'tools': {}, 'presets': {}})
        with self.assertRaises(TrackerError):
            self.ann.put_settings('nope', {})
        with self.assertRaises(TrackerError):
            self.ann.put_settings('props', {'a': object()})

    def test_presets_upsert_by_name_list_and_delete_privately(self):
        first = self.ann.save_preset('props', 'Sharp only', {'minEv': '3'})
        again = self.ann.save_preset('props', 'sharp ONLY', {'minEv': '5'})
        self.assertEqual(first['id'], again['id'])
        self.assertEqual(again['name'], 'sharp ONLY')
        self.ann.save_preset('props', 'Another', {})
        self.ann.save_preset('promo', 'Sharp only', {'type': 'credit'})
        listed = self.ann.settings()['presets']
        self.assertEqual([p['name'] for p in listed['props']], ['Another', 'sharp ONLY'])
        self.assertEqual(listed['props'][1]['settings'], {'minEv': '5'})
        self.assertEqual(len(listed['promo']), 1)
        self.assertEqual(self.bob.settings()['presets'], {})
        with self.assertRaises(TrackerError) as raised:
            self.bob.delete_preset(first['id'])
        self.assertEqual(raised.exception.status, 404)
        self.ann.delete_preset(first['id'])
        self.assertEqual([p['name'] for p in self.ann.settings()['presets']['props']], ['Another'])

    def test_preset_cap_per_tool(self):
        for n in range(tool_settings.MAX_PRESETS):
            self.ann.save_preset('games', f'p{n}', {})
        with self.assertRaises(TrackerError) as raised:
            self.ann.save_preset('games', 'one too many', {})
        self.assertEqual(raised.exception.status, 409)
        self.ann.save_preset('games', 'p0', {'x': 1})  # replacing an existing name is still allowed
        self.ann.save_preset('props', 'other tool is separate', {})


class Http(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TrackerStore(Path(self.tmp.name) / 't.sqlite3')
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.store.close)
        app = FastAPI()
        app.include_router(settings_service.create_router(accounts.AuthContext(self.store, SECRET, {ORIGIN})))
        self.app = app

    def client(self, name=None):
        client = TestClient(self.app, base_url='http://localhost')
        if name:
            user = self.store.create_user(name, name.lower(), 'h')
            client.cookies.set(accounts.COOKIE, auth.issue_token(SECRET, user['id'], name))
        return client

    def test_round_trip(self):
        ann = self.client('Ann')
        self.assertEqual(ann.get('/api/refresh/v1/settings').json(), {'tools': {}, 'presets': {}})
        self.assertEqual(ann.put('/api/refresh/v1/settings/props', json={'settings': {'minEv': '2'}}, headers=WRITE).status_code, 200)
        saved = ann.post('/api/refresh/v1/settings/props/presets', json={'name': 'Mine', 'settings': {'minEv': '4'}}, headers=WRITE)
        self.assertEqual(saved.status_code, 200)
        everything = ann.get('/api/refresh/v1/settings').json()
        self.assertEqual(everything['tools']['props'], {'minEv': '2'})
        self.assertEqual(everything['presets']['props'][0]['name'], 'Mine')
        gone = ann.delete(f"/api/refresh/v1/settings/presets/{saved.json()['preset']['id']}", headers=WRITE)
        self.assertEqual(gone.status_code, 200)
        self.assertEqual(ann.get('/api/refresh/v1/settings').json()['presets'], {})

    def test_accounts_never_see_each_others_settings(self):
        ann, bob = self.client('Ann'), self.client('Bob')
        ann.put('/api/refresh/v1/settings/promo', json={'settings': {'type': 'credit'}}, headers=WRITE)
        ann.post('/api/refresh/v1/settings/promo/presets', json={'name': 'A', 'settings': {}}, headers=WRITE)
        self.assertEqual(bob.get('/api/refresh/v1/settings').json(), {'tools': {}, 'presets': {}})
        preset_id = ann.get('/api/refresh/v1/settings').json()['presets']['promo'][0]['id']
        self.assertEqual(bob.delete(f'/api/refresh/v1/settings/presets/{preset_id}', headers=WRITE).status_code, 404)

    def test_guards_and_validation(self):
        guest = self.client()
        self.assertEqual(guest.get('/api/refresh/v1/settings').status_code, 401)
        self.assertEqual(guest.put('/api/refresh/v1/settings/props', json={'settings': {}}, headers=WRITE).status_code, 401)
        ann = self.client('Ann')
        self.assertEqual(ann.put('/api/refresh/v1/settings/props', json={'settings': {}}).status_code, 403)
        self.assertEqual(ann.put('/api/refresh/v1/settings/nope', json={'settings': {}}, headers=WRITE).status_code, 404)
        self.assertEqual(ann.put('/api/refresh/v1/settings/props', json={'settings': 'x'}, headers=WRITE).status_code, 400)
        self.assertEqual(ann.put('/api/refresh/v1/settings/props', json=[1], headers=WRITE).status_code, 400)
        self.assertEqual(ann.put('/api/refresh/v1/settings/props', content=b'nope', headers=WRITE).status_code, 400)
        self.assertEqual(ann.post('/api/refresh/v1/settings/props/presets', json={'name': '', 'settings': {}}, headers=WRITE).status_code, 400)
        self.assertEqual(ann.get('/api/refresh/v1/settings', headers={'Host': 'evil.example'}).status_code, 403)


if __name__ == '__main__':
    unittest.main()
