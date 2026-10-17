import unittest
from tests import test_tracker_service as service
from tests.test_parlay_tracker import parlay

class ParlayHTTP(unittest.TestCase):
    setUp = service.Service.setUp
    url = service.Service.url

    def test_same_game_quote_is_preserved_through_http_and_export(self):
        item=parlay('sgp-http')
        item['legs'][1]['event_id']=item['legs'][0]['event_id']
        item['legs'][1]['matchup']=item['legs'][0]['matchup']
        item['selection']='Same-game parlay';item['odds']='3.25'
        response=self.client.post(self.url('/bets'),json=[item],headers=self.write)
        self.assertEqual(response.status_code,200)
        saved=response.json()['bets'][0]
        self.assertEqual(saved['odds'],'3.25')
        self.assertEqual(len(saved['legs']),2)
        exported=self.client.get(self.url('/export')).json()['bets'][0]
        self.assertEqual(exported['selection'],'Same-game parlay')
        self.assertEqual(exported['odds'],'3.25')

    def test_record_grade_export_and_settle_one_parent(self):
        response = self.client.post(self.url('/bets'), json=[parlay()], headers=self.write)
        self.assertEqual(200, response.status_code)
        saved = response.json()['bets'][0]
        self.assertEqual(2, len(saved['legs']))
        graded = self.client.patch(self.url(f"/bets/{saved['id']}"), json={'parlay_leg_key': 'leg-0', 'parlay_leg_result': 'lost'}, headers=self.write)
        self.assertEqual(200, graded.status_code)
        self.assertEqual('lost', graded.json()['bet']['suggested_result'])
        self.assertEqual('pending', graded.json()['bet']['status'])
        state = self.client.get(self.url('/state')).json()
        self.assertEqual(1, len(state['bets']))
        self.assertEqual(2500, state['bets'][0]['stake_cents'])
        settle = self.client.post(self.url(f"/bets/{saved['id']}/settle"), json={'result': 'lost'}, headers=self.write)
        self.assertEqual(0, settle.json()['bet']['returned_cents'])
        self.assertEqual(2, len(self.client.get(self.url('/export')).json()['bets'][0]['legs']))

    def test_grade_route_requires_signed_in_account_and_valid_origin(self):
        saved = self.client.post(self.url('/bets'), json=[parlay()], headers=self.write).json()['bets'][0]
        path = self.url(f"/bets/{saved['id']}/legs")
        body = {'key': 'leg-0', 'result': 'won'}
        self.assertEqual(401, self.anonymous().post(path, json=body, headers=self.write).status_code)
        self.assertEqual(403, self.client.post(path, json=body, headers={'Origin': 'http://evil.test'}).status_code)
        self.assertEqual(200, self.client.post(path, json=body, headers=self.write).status_code)
