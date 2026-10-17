"""Independent arithmetic and boundary checks for explicit one-sided models."""
import unittest
from decimal import Decimal as D
from corner.prop_markets import build_bets
from tests.test_one_sided_props import event


class AssumedMargin(unittest.TestCase):
    def data(self):
        return {'e': event({'pinnacle': {0: 2}, 'fanduel': {0: 2}, 'draftkings': {0: 3}})}

    def test_explicit_model_and_no_shared_default(self):
        data = self.data()
        self.assertEqual(build_bets(data), [])
        rows = build_bets(data, one_sided_margin='0.10')
        target = next(b for b in rows if b['book'] == 'draftkings')
        self.assertEqual(target['fair_probability'], '0.454545')
        self.assertEqual(target['ev'], '0.363636')
        self.assertEqual(target['assumed_margin'], '0.10')
        self.assertEqual(target['probability_basis'], 'assumed_proportional_margin')
        self.assertIsNone(target['market_width_cents'])
        self.assertEqual(build_bets(data), [])
        self.assertTrue(all(b['book'] not in b['sharps'] and len(b['sharps']) >= 2 for b in rows))

    def test_fee_adjusted_target(self):
        data = self.data()
        quotes = data['e']['markets']['player_shots']['quotes']
        quotes[-1]['book'] = 'prophetx'
        target = next(b for b in build_bets(data, one_sided_margin='0.10') if b['book'] == 'prophetx')
        self.assertEqual(D(target['net_decimal_odds']), D('2.96'))
        self.assertEqual(target['ev'], '0.345455')
        quotes[-1]['price'] = '2'
        target = next(b for b in build_bets(data, one_sided_margin='0.10') if b['book'] == 'prophetx')
        self.assertLess(D(target['ev']), 0)

    def test_two_matching_non_dfs_references_required(self):
        for field, value in [('point', '3.5'), ('book', 'prizepicks'), ('side', 1)]:
            data = self.data()
            data['e']['markets']['player_shots']['quotes'][0][field] = value
            self.assertEqual(build_bets(data, one_sided_margin='0.10'), [])

    def test_yes_only_model(self):
        data = {'e': event({'pinnacle': {0: 4}, 'fanduel': {0: 4}, 'draftkings': {0: 6}}, 'player_goal_scorer_anytime')}
        target = next(b for b in build_bets(data, one_sided_margin='0.10') if b['book'] == 'draftkings')
        self.assertEqual(target['fair_probability'], '0.227273')
        self.assertEqual(target['ev'], '0.363636')

    def test_paired_model_unchanged(self):
        data = {'e': event({'pinnacle': {0: 2, 1: 2}, 'fanduel': {0: 2, 1: 2}, 'draftkings': {0: 3, 1: 2}})}
        self.assertEqual(build_bets(data), build_bets(data, one_sided_margin='0.50'))

    def test_invalid_margin_and_explicit_zero(self):
        for margin in ('NaN', 'Infinity', '-0.01', '0.501', 'no', True, 1):
            with self.subTest(margin=margin), self.assertRaises(ValueError):
                build_bets(self.data(), one_sided_margin=margin)
        self.assertTrue(build_bets(self.data(), one_sided_margin='0'))


class MarginEndpoint(unittest.TestCase):
    def test_authenticated_read_is_free_and_request_scoped(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from corner.tracker_store import TrackerStore
        from pipelines import accounts, refresh_service as svc
        with tempfile.TemporaryDirectory() as directory:
            store = TrackerStore(Path(directory) / 'accounts.sqlite3')
            try:
                ctx = accounts.AuthContext(store, 's'*48, {'http://localhost'})
                with patch.object(accounts, 'AuthContext', return_value=ctx):
                    client = TestClient(svc.create_app(), base_url='http://localhost')
                with patch.object(svc.props, 'bets', return_value=[]) as read, patch.object(svc, 'props_status', return_value={}), patch.object(svc, 'run_props_refresh') as paid:
                    self.assertEqual(client.get('/api/refresh/v1/props?one_sided_margin=.08').status_code, 401)
                    response = client.post('/api/refresh/v1/auth/register', json={'username':'modeltest','password':'a-long-password'}, headers={'Origin':'http://localhost'})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(client.get('/api/refresh/v1/props?one_sided_margin=.08').status_code, 200)
                    read.assert_called_once_with(one_sided_margin=D('.08'))
                    read.reset_mock()
                    self.assertEqual(client.get('/api/refresh/v1/props').status_code, 200)
                    read.assert_called_once_with()
                    read.reset_mock()
                    for value in ('NaN', '-1', '0.51', 'bad'):
                        self.assertEqual(client.get('/api/refresh/v1/props', params={'one_sided_margin':value}).status_code, 422)
                    read.assert_not_called()
                    paid.assert_not_called()
            finally:
                store.close()
