"""Optional API dependencies: run with .venv-api or requirements-api.txt installed."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.request import urlopen

API_AVAILABLE = all(importlib.util.find_spec(name) is not None for name in ('fastapi', 'httpx', 'uvicorn'))
if API_AVAILABLE:
    from fastapi.testclient import TestClient
    from api.app import create_app
    from api.catalog import FixtureCatalog, FIXTURE, wire


@unittest.skipUnless(API_AVAILABLE, 'optional requirements-api.txt dependencies not installed')
class ProductAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = FixtureCatalog()
        cls.app = create_app(catalog=cls.catalog)
        cls.client = TestClient(cls.app, base_url='http://127.0.0.1', raise_server_exceptions=False)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def get(self, path, **params):
        response = self.client.get('/api/v1/' + path, params=params)
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def command(self):
        quotes = self.get('games/demo-nba/odds', limit=100)['data']['items']
        back = next(q for q in quotes if q['contract_id'] == 'nba-h2h' and q['sportsbook_id'] == 'demo_target' and q['selection_id'] == 'home')
        lay = next(q for q in quotes if q['contract_id'] == 'nba-h2h' and q['market_key'] == 'h2h_lay' and q['selection_id'] == 'home')
        return dict(snapshot_id=self.catalog.snapshot_id, contract_id='nba-h2h', promo_quote_id=back['id'], hedge_quote_id=lay['id'], hedge_type='lay',
                    terms=dict(terms_id='fixture:user-terms/1', kind='bonus_stake_not_returned', face_value='100', eligible_stake_cap='100',
                               minimum_decimal_odds='1.5', loss_refund_cap='0', eligibility_evidence_id='fixture:eligibility', bonus_restored_on_void=True))

    def post(self, data):
        return self.client.post('/api/v1/calculators/promo', json=data)

    def assert_error(self, response, status, code=None):
        self.assertEqual(status, response.status_code, response.text)
        body = response.json()
        self.assertIn('error', body)
        self.assertNotIn('data', body)
        self.assertEqual('fixture', body['meta']['data_mode'])
        if code:
            self.assertEqual(code, body['error']['code'])

    def test_every_data_route_has_honest_fixture_metadata(self):
        for path in ('health', 'capabilities', 'games', 'games/demo-nba', 'games/demo-nba/odds',
                     'tools/positive_ev', 'tools/arbitrage', 'tools/low_hold', 'tools/middle'):
            with self.subTest(path=path):
                body = self.get(path)
                self.assertFalse(body['meta']['production_authorized'])
                self.assertFalse(body['meta']['availability_verified'])
                self.assertEqual('2030-01-01T19:00:00Z', body['meta']['reference_clock_at'])
                self.assertIn('fixture_clock_not_live_time', body['meta']['warnings'])

    def test_health_does_not_claim_database_readiness(self):
        health = self.get('health')['data']
        self.assertTrue(health['fixture_loaded'])
        self.assertFalse(health['database_connected'])
        self.assertFalse(health['live_mode_supported'])

    def test_exact_market_allowlist_and_no_insiders(self):
        caps = self.get('capabilities')['data']
        self.assertEqual(['h2h', 'spreads', 'totals', 'outrights', 'h2h_lay', 'outrights_lay', 'alternate_spreads', 'alternate_totals', 'btts', 'draw_no_bet', 'team_totals', 'alternate_team_totals'], caps['market_keys'])
        self.assertIn('insiders', caps['unsupported'])
        self.assertNotIn('insiders', caps['tools'])

    def test_games_have_unknown_phase_not_inferred_from_future_start(self):
        games = self.get('games')['data']['items']
        self.assertEqual(3, len(games))
        self.assertTrue(all(g['phase'] == 'unknown' for g in games))
        self.assertEqual('competition', next(g for g in games if g['id'] == 'demo-tournament')['scope'])

    def test_game_search_and_sport_market_filters(self):
        self.assertEqual(1, self.get('games', sport_key='basketball_nba')['data']['total'])
        self.assertEqual(1, self.get('games', search='HAWKS')['data']['total'])
        self.assertEqual(1, self.get('games', market_key='outrights_lay')['data']['total'])
        self.assertEqual(0, self.get('games', sport_key='not_available')['data']['total'])

    def test_pagination_stable_without_overlap(self):
        all_rows = self.get('tools/low_hold', limit=100, sort='minimum_profit', descending=True)['data']['items']
        found, offset = [], 0
        while offset is not None:
            page = self.get('tools/low_hold', limit=3, offset=offset, sort='minimum_profit', descending=True,
                            snapshot_id=self.catalog.snapshot_id)['data']
            found.extend(page['items'])
            offset = page['next_offset']
        self.assertEqual(all_rows, found)
        self.assertEqual(len(found), len({r['id'] for r in found}))

    def test_empty_page_has_total_and_no_next_page(self):
        data = self.get('games', offset=999)['data']
        self.assertEqual([], data['items'])
        self.assertEqual(3, data['total'])
        self.assertIsNone(data['next_offset'])

    def test_stale_page_snapshot_is_conflict_not_silent_restart(self):
        self.assert_error(self.client.get('/api/v1/games', params={'snapshot_id': 'old'}), 409, 'snapshot_changed')

    def test_quote_filters_and_exact_numeric_sort(self):
        rows = self.get('games/demo-nba/odds', limit=100, market_key='h2h', sort='decimal_odds', descending=True)['data']['items']
        self.assertTrue(all(r['market_key'] == 'h2h' for r in rows))
        values = [Decimal(r['decimal_odds']) for r in rows]
        self.assertEqual(sorted(values, reverse=True), values)
        rows = self.get('games/demo-nba/odds', sportsbook_id='demo_target', contract_id='nba-total-210-5')['data']['items']
        self.assertEqual(2, len(rows))
        self.assertEqual({'210.5'}, {r['point'] for r in rows})

    def test_quote_timestamps_are_not_fabricated_on_each_request(self):
        a = self.get('games/demo-nba/odds')['data']
        b = self.get('games/demo-nba/odds')['data']
        self.assertEqual(a, b)
        self.assertTrue(all(q['provider_updated_at'] is None and q['current_availability'] == 'unverified' for q in a['items']))

    def test_tool_rows_link_to_real_fixture_quotes_and_game(self):
        for kind in ('positive_ev', 'arbitrage', 'low_hold', 'middle'):
            rows = self.get('tools/' + kind, limit=100)['data']['items']
            self.assertTrue(rows)
            for row in rows:
                self.assertIn(row['game_id'], self.catalog.game_map)
                self.assertTrue(all(q in self.catalog.quote_map for q in row['quote_ids']))
                self.assertTrue(all(self.catalog.quote_map[q].game_id == row['game_id'] for q in row['quote_ids']))
                self.assertEqual(kind, row['kind'])
                self.assertFalse(row['calculation']['availability_verified'])

    def test_ev_response_stays_conditional_and_positive(self):
        for row in self.get('tools/positive_ev', limit=100)['data']['items']:
            self.assertGreater(Decimal(row['conditional_ev_ratio']), 0)
            self.assertEqual('decisive_settlement_conditional', row['calculation']['calculation_basis'])
            self.assertIsNone(row['calculation']['unconditional_ev_ratio'])
        self.assertEqual(0, self.get('tools/positive_ev', minimum_ev_ratio='100')['data']['total'])

    def test_tool_filters_compose_and_sort(self):
        rows = self.get('tools/positive_ev', game_id='demo-nba', market_key='totals', sportsbook_id='demo_target',
                        sort='conditional_ev_ratio', descending=True)['data']['items']
        self.assertTrue(rows)
        self.assertTrue(all(r['game_id'] == 'demo-nba' and r['market_key'] == 'totals' and 'demo_target' in r['sportsbook_ids'] for r in rows))
        values = [Decimal(r['conditional_ev_ratio']) for r in rows]
        self.assertEqual(sorted(values, reverse=True), values)

    def test_middles_have_no_invented_ev(self):
        for row in self.get('tools/middle', limit=100)['data']['items']:
            self.assertIsNone(row['conditional_ev_ratio'])
            self.assertIsNone(row['calculation']['payoff']['expected_profit'])
            self.assertTrue(row['calculation']['double_win_ranges'])

    def test_low_hold_filter_uses_loss_over_capital(self):
        strict = self.get('tools/low_hold', maximum_loss_ratio='0', limit=100)['data']
        loose = self.get('tools/low_hold', maximum_loss_ratio='1', limit=100)['data']
        self.assertLess(strict['total'], loose['total'])
        self.assertTrue(all(Decimal(r['minimum_profit']) >= 0 for r in strict['items']))

    def test_no_float_in_any_response_tree(self):
        def visit(value):
            self.assertNotIsInstance(value, float)
            if isinstance(value, dict):
                for v in value.values(): visit(v)
            if isinstance(value, list):
                for v in value: visit(v)
        for path in ('games', 'games/demo-nba/odds', 'tools/positive_ev', 'tools/arbitrage', 'tools/middle'):
            visit(self.get(path, limit=100))
        visit(self.post(self.command()).json())

    def test_promo_delegates_to_existing_calculator(self):
        from api.models import PromoRequest
        request = self.command()
        response = self.post(request)
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(wire(self.catalog.promo(PromoRequest.model_validate(request))), response.json()['data'])
        result = response.json()['data']['calculation']
        self.assertFalse(result['eligibility_verified'])
        self.assertEqual('0', result['minimum_modeled_cash_profit'])

    def test_opposite_back_promo(self):
        request = self.command()
        request['hedge_type'] = 'opposite_back'
        request['hedge_quote_id'] = 'nba-h2h:demo_reference_b:h2h:away'
        result = self.post(request)
        self.assertEqual(200, result.status_code, result.text)
        self.assertIn('hedge_stake', result.json()['data']['calculation'])

    def test_token_refund_never_becomes_cash(self):
        request = self.command()
        request['terms'].update(kind='loss_refund_bonus', loss_refund_cap='100', bonus_restored_on_void=False)
        response = self.post(request)
        self.assertEqual(200, response.status_code)
        result = response.json()['data']['calculation']
        self.assertIsNone(result['noncash_valuation'])
        self.assertEqual('100', result['outcomes'][1]['noncash_bonus_face_returned'])

    def test_promo_snapshot_and_quote_integrity(self):
        for patch_values, status in (({'snapshot_id': 'stale'}, 409), ({'promo_quote_id': 'missing'}, 404),
                                     ({'contract_id': 'soccer-h2h'}, 422), ({'hedge_quote_id': 'nba-h2h:demo_exchange:h2h_lay:away'}, 422)):
            request = self.command() | patch_values
            self.assert_error(self.post(request), status)

    def test_decimal_inputs_strict_strings_and_bounded(self):
        for invalid in (100, 100.0, 'NaN', 'Infinity', '1e2', '-1', '0.0000000000001', '9' * 90, '0'):
            request = self.command()
            request['terms']['face_value'] = invalid
            self.assert_error(self.post(request), 422)

    def test_extra_prices_or_authorization_flags_rejected(self):
        for patch_values in ({'decimal_odds': '10'}, {'production_authorized': True}, {'mode': 'live'}):
            self.assert_error(self.post(self.command() | patch_values), 422)

    def test_promo_terms_eligibility_and_lay_cap_failures(self):
        for values in ({'eligible_stake_cap': '1'}, {'minimum_decimal_odds': '20'}, {'bonus_restored_on_void': 'true'}):
            command = self.command()
            command['terms'].update(values)
            self.assert_error(self.post(command), 422)
        command = self.command()
        command.update(hedge_type='opposite_back', maximum_lay_liability='100')
        self.assert_error(self.post(command), 422)

    def test_repeat_and_concurrent_calculation_no_mutations(self):
        command = self.command()
        before = wire(self.catalog.rows)
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(lambda _: self.post(command), range(8)))
        self.assertTrue(all(r.status_code == 200 for r in responses))
        self.assertEqual(1, len({json.dumps(r.json()['data'], sort_keys=True) for r in responses}))
        self.assertEqual(before, wire(self.catalog.rows))

    def test_unknown_routes_and_games_are_errors(self):
        self.assert_error(self.client.get('/api/v1/games/missing'), 404, 'game_not_found')
        self.assert_error(self.client.get('/api/v1/games/missing/odds'), 404)
        self.assert_error(self.client.get('/api/v1/nothing'), 404)
        self.assert_error(self.client.delete('/api/v1/games/demo-nba'), 405)

    def test_bad_queries_never_silently_default(self):
        for query in ('limit=0', 'limit=101', 'offset=-1', 'offset=10001', 'market_key=player_unknown_stat',
                      'sort=unknown', 'production=true', 'limit=1&limit=2'):
            self.assert_error(self.client.get('/api/v1/games?' + query), 422)
        self.assert_error(self.client.get('/api/v1/tools/middle?sort=conditional_ev_ratio'), 422)
        self.assert_error(self.client.get('/api/v1/tools/positive_ev?maximum_loss_ratio=1'), 422)
        self.assert_error(self.client.get('/api/v1/tools/low_hold?maximum_loss_ratio=2'), 422)

    def test_bad_json_and_body_limits(self):
        endpoint = '/api/v1/calculators/promo'
        for payload in ('{', '{"snapshot_id":"a","snapshot_id":"b"}', '{"x":NaN}'):
            self.assert_error(self.client.post(endpoint, content=payload, headers={'Content-Type': 'application/json'}), 400, 'invalid_json')
        self.assert_error(self.client.post(endpoint, content='{}'), 415)
        self.assert_error(self.client.post(endpoint, content=' ' * 16385, headers={'Content-Type': 'application/json'}), 413)
        self.assert_error(self.client.get('/api/v1/games?' + 'x' * 2050), 414)

    def test_unknown_exception_is_error_not_empty_success(self):
        with patch.object(self.catalog, 'game', side_effect=RuntimeError('private-internal-value')):
            response = self.client.get('/api/v1/games/demo-nba')
        self.assert_error(response, 500, 'internal_error')
        self.assertNotIn('private-internal-value', response.text)

    def test_cors_explicit_local_frontend_only(self):
        headers = {'Origin': 'http://localhost:5173', 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'content-type'}
        allowed = self.client.options('/api/v1/calculators/promo', headers=headers)
        self.assertEqual(200, allowed.status_code)
        self.assertEqual('http://localhost:5173', allowed.headers['access-control-allow-origin'])
        denied = self.client.options('/api/v1/calculators/promo', headers=headers | {'Origin': 'https://evil.example'})
        self.assertEqual(400, denied.status_code)
        self.assertNotIn('access-control-allow-origin', denied.headers)

    def test_local_host_protection_and_no_store(self):
        self.assert_error(self.client.get('/api/v1/health', headers={'Host': 'evil.example'}), 400, 'invalid_host')
        response = self.client.get('/api/v1/health')
        self.assertIn('no-store', response.headers['cache-control'])
        self.assertEqual('fixture', response.headers['x-corner-data-mode'])

    def test_factory_cannot_enable_live_or_external_cors(self):
        with self.assertRaises(ValueError): create_app(data_mode='live')
        with self.assertRaises(ValueError): create_app(cors_origins=('*',))
        with self.assertRaises(ValueError): create_app(cors_origins=('https://remote.example',))

    def test_snapshot_identity_stable_and_changes_with_data(self):
        self.assertEqual(self.catalog.snapshot_id, FixtureCatalog().snapshot_id)
        raw = json.loads(FIXTURE.read_text())
        raw['contracts'][0]['prices']['demo_target'][0] = '2.13'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.json'
            path.write_text(json.dumps(raw), encoding='utf-8')
            self.assertNotEqual(self.catalog.snapshot_id, FixtureCatalog(path).snapshot_id)

    def test_corrupt_fixture_fails_startup(self):
        raw = json.loads(FIXTURE.read_text())
        raw['contracts'][0]['prices']['demo_reference_a'] = ['2']
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.json'
            path.write_text(json.dumps(raw), encoding='utf-8')
            with self.assertRaises(ValueError): FixtureCatalog(path)

    def test_inconsistent_fixture_lines_fail_startup(self):
        raw = json.loads(FIXTURE.read_text())
        raw['contracts'][1]['selections'][1]['point'] = '6.5'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.json'
            path.write_text(json.dumps(raw), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'exact opposite'):
                FixtureCatalog(path)

    def test_openapi_documents_decimal_strings_and_discriminated_results(self):
        schema = self.client.get('/openapi.json').json()
        self.assertIn('/api/v1/calculators/promo', schema['paths'])
        self.assertEqual('string', schema['components']['schemas']['TermsInput']['properties']['face_value']['type'])
        self.assertEqual('string', schema['components']['schemas']['Quote']['properties']['decimal_odds']['type'])
        self.assertEqual('string', schema['components']['schemas']['FeaturedEV']['properties']['conditional_ev_ratio_on_capital']['type'])
        self.assertEqual(200, self.client.get('/docs').status_code)

    def test_frontend_is_served_without_exposing_repository(self):
        page = self.client.get('/')
        self.assertEqual(200, page.status_code)
        self.assertIn('The Corner', page.text)
        self.assertIn('Synthetic prices', page.text)
        for path in ('/app.js', '/styles.css', '/betting.css', '/format.mjs', '/presentation.mjs', '/client.mjs', '/mark.svg'):
            self.assertEqual(200, self.client.get(path).status_code)
        for path in ('/.env', '/config.py', '/api/app.py', '/fixtures/product_api/v1/catalog.json'):
            self.assertEqual(404, self.client.get(path).status_code)

    def test_no_config_or_database_import_in_fresh_api_process(self):
        check = 'import sys; import api.app; assert "config" not in sys.modules; assert "psycopg2" not in sys.modules; print("isolated")'
        result = subprocess.run([sys.executable, '-c', check], capture_output=True, text=True, timeout=20)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('isolated', result.stdout.strip())

    def test_actual_loopback_server_start_request_and_stop(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        process = subprocess.Popen([sys.executable, '-m', 'api', '--port', str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 15
            while True:
                try:
                    with urlopen(f'http://127.0.0.1:{port}/api/v1/health', timeout=1) as response:
                        data = json.load(response)
                    break
                except OSError:
                    if process.poll() is not None or time.monotonic() > deadline:
                        self.fail('fixture API failed to start')
                    time.sleep(.05)
            self.assertEqual('fixture', data['meta']['data_mode'])
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            process.stderr.close()
        self.assertIsNotNone(process.returncode)


if __name__ == '__main__':
    unittest.main()
