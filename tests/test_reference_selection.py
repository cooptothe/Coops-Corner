import unittest
from fastapi.testclient import TestClient
from api.app import create_app
from api.catalog import FixtureCatalog
from corner.prop_markets import build_bets
from tests.test_one_sided_props import event


class FixedReferences(unittest.TestCase):
    def test_props_target_never_references_itself(self):
        data={'e':event({'pinnacle':{0:2,1:2},'fanduel':{0:1.8,1:2.2},'novig':{0:2.2,1:1.8},'draftkings':{0:3}})}
        rows=build_bets(data)
        self.assertTrue(rows)
        self.assertTrue(all(r['book'] not in r['sharps'] for r in rows))
        with self.assertRaises(TypeError):
            build_bets(data,reference_books=['fanduel'])

    def test_main_does_not_accept_reference_overrides(self):
        client=TestClient(create_app(catalog=FixtureCatalog()),base_url='http://127.0.0.1')
        before=client.get('/api/v1/tools/positive_ev').json()['data']
        for value in ('none','pinnacle','not_allowed'):
            response=client.get('/api/v1/tools/positive_ev?reference_books='+value)
            self.assertEqual(response.status_code,422)
        self.assertEqual(client.get('/api/v1/tools/positive_ev').json()['data'],before)
