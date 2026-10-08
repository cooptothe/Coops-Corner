"""Player-prop fetch tests: no budget, no cooldown, and every outcome explained. No network, no credits."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pipelines import props_ingestion as ing
from pipelines import refresh_service as svc

EVENTS = [{'id': f'e{i}', 'home_team': 'H', 'away_team': 'A', 'commence_time': f'2030-01-0{i}T00:00:00Z'}
          for i in range(1, 5)]
ODDS = {'home_team': 'H', 'away_team': 'A', 'bookmakers': [
    {'key': 'draftkings', 'markets': [{'key': 'player_points', 'outcomes': [
        {'name': 'Over', 'description': 'P One', 'price': 1.9, 'point': 20.5},
        {'name': 'Under', 'description': 'P One', 'price': 1.9, 'point': 20.5}]}]}]}


class FakeProvider:
    """Stands in for fetch(): a free events list, then paid per-event odds that count down the quota."""

    def __init__(self, remaining=500, fail_with=None):
        self.remaining, self.fail_with, self.paid = remaining, fail_with, 0

    def __call__(self, session, url, params):
        if url.endswith('/events'):
            return 200, json.dumps(EVENTS).encode(), {'x-requests-remaining': str(self.remaining)}
        if self.fail_with:
            return self.fail_with, b'{}', {'x-requests-remaining': str(self.remaining)}
        cost = len(params['markets'].split(','))  # the provider bills one credit per market
        self.paid += 1
        self.remaining -= cost
        return 200, json.dumps({**ODDS, 'id': url.split('/')[-2]}).encode(), {
            'x-requests-remaining': str(self.remaining), 'x-requests-last': str(cost)}


class Capture(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for name, value in (('STORE', Path(tmp.name) / 'latest.json'), ('ODDS_API_KEY', 'test-key')):
            p = patch.object(ing, name, value); p.start(); self.addCleanup(p.stop)

    def run_capture(self, provider, markets=('player_points',), count=4):
        with patch.object(ing, 'fetch', provider):
            return ing.capture('basketball_nba', list(markets), count)

    def test_fetches_every_planned_game(self):
        provider = FakeProvider()
        result = self.run_capture(provider)
        self.assertEqual((result['events'], result['planned'], result['credits_used'], result['stopped']),
                         (4, 4, 4, None))
        self.assertEqual(provider.paid, 4)

    def test_a_low_balance_no_longer_blocks_a_call_it_can_pay_for(self):
        # 9 credits left used to be refused by a hard 20-credit floor.
        provider = FakeProvider(remaining=9)
        result = self.run_capture(provider, markets=('player_points', 'player_rebounds'), count=4)
        self.assertEqual((result['events'], result['stopped'], result['remaining']), (4, None, 1))

    def test_stops_only_when_the_key_cannot_afford_the_next_game(self):
        provider = FakeProvider(remaining=3)
        result = self.run_capture(provider, markets=('player_points', 'player_rebounds'), count=4)
        self.assertEqual((result['events'], result['stopped'], result['remaining']), (1, 'out_of_credits', 1))
        self.assertEqual(provider.paid, 1)

    def test_provider_rejection_is_reported(self):
        result = self.run_capture(FakeProvider(fail_with=422))
        self.assertEqual((result['events'], result['stopped']), (0, 'provider_http_422'))


class Messages(unittest.TestCase):
    def say(self, **result):
        base = {'events': 0, 'planned': 4, 'credits_used': 0, 'stopped': None, 'remaining': 500}
        return svc.props_message('NBA', ['player_points', 'player_rebounds'], {**base, **result})

    def test_success(self):
        self.assertEqual(self.say(events=4, credits_used=8), 'Fetched props for 4 games, 8 credits used.')
        self.assertEqual(self.say(events=1, planned=1, credits_used=1), 'Fetched props for 1 game, 1 credit used.')

    def test_out_of_credits_says_so_and_what_was_done(self):
        text = self.say(stopped='out_of_credits', remaining=1)
        self.assertIn('only 1 credit left on your Odds API key', text)
        self.assertIn('each game needs 2 credits', text)
        self.assertIn('Nothing was fetched.', text)
        self.assertIn('Fetched 1 game of 4, 2 credits used.', self.say(events=1, credits_used=2,
                                                                          stopped='out_of_credits', remaining=0))

    def test_says_how_many_bets_the_fetch_produced(self):
        base = {'events': 3, 'planned': 3, 'credits_used': 6, 'stopped': None, 'remaining': 100}
        text = svc.props_message('NBA', ['player_points', 'player_assists'], base, {'bets': 12, 'positive': 3})
        self.assertEqual(text, 'Fetched props for 3 games, 6 credits used. 12 NBA bets priced, 3 with positive EV.')
        none = svc.props_message('NBA', ['player_points', 'player_assists'], base, {'bets': 0, 'positive': 0})
        self.assertIn('No NBA bets can be shown', none)
        self.assertIn('two sharp books', none)

    def test_no_games_and_provider_errors(self):
        self.assertEqual(self.say(planned=0), 'No upcoming NBA games to fetch.')
        self.assertIn('HTTP 422', self.say(stopped='provider_http_422'))
        self.assertIn('rate limiting', self.say(stopped='provider_http_429'))
        self.assertIn('HTTP 401', self.say(stopped='provider_http_401'))
        self.assertIn('HTTP 503', self.say(stopped='provider_http_503'))


class Freshness(unittest.TestCase):
    NOW = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)

    def quotes(self, price='2.1'):
        return [{'book': b, 'player': 'P One', 'side': s, 'point': '20.5', 'price': price if b == 'fanduel' else '1.91',
                 'updated_at': None} for b in ('pinnacle', 'prophetx', 'fanduel') for s in (0, 1)]

    def market(self, minutes_ago):
        stamp = (self.NOW - timedelta(minutes=minutes_ago)).isoformat()
        return {'captured_at': stamp, 'quotes': self.quotes()}

    def event(self, sport='basketball_nba', **markets):
        return {'sport_key': sport, 'home_team': 'H', 'away_team': 'A', 'commence_time': '2030-01-02T00:00:00Z',
                'markets': markets}

    def test_old_fetches_stop_counting_but_stay_known(self):
        data = {'events': {'e1': self.event(player_points=self.market(5), player_assists=self.market(90))}}
        kept = ing.prune(data, self.NOW, max_age=3600)['events']['e1']['markets']
        self.assertEqual(['player_points'], list(kept))
        # Without an age limit (the "last fetched" lookup) nothing is dropped for age.
        data = {'events': {'e1': self.event(player_assists=self.market(90))}}
        self.assertIn('e1', ing.prune(data, self.NOW)['events'])
        self.assertEqual({}, ing.prune(data, self.NOW, max_age=3600)['events'])

    def test_started_games_are_dropped(self):
        late = {**self.event(player_points=self.market(1)), 'commence_time': '2029-12-31T00:00:00Z'}
        self.assertEqual({}, ing.prune({'events': {'e1': late}}, self.NOW)['events'])

    def test_bets_hide_stale_fetches(self):
        with patch.object(ing, 'load', return_value={'events': {'e1': self.event(player_points=self.market(5))}}):
            self.assertTrue(ing.bets(self.NOW))
        with patch.object(ing, 'load', return_value={'events': {'e1': self.event(player_points=self.market(120))}}):
            self.assertEqual([], ing.bets(self.NOW))

    def test_a_fetch_replaces_its_own_scope_only(self):
        data = {'events': {
            'keep': self.event(player_points=self.market(1), player_assists=self.market(1)),
            'drop': self.event(player_points=self.market(30), player_assists=self.market(30)),
            'only_points': self.event(player_points=self.market(30)),
            'other_league': self.event(sport='icehockey_nhl', player_points=self.market(30)),
        }}
        ing.replace_scope(data, 'basketball_nba', ['player_points'], {'keep'})
        events = data['events']
        self.assertEqual({'player_points', 'player_assists'}, set(events['keep']['markets']))
        # Not part of the new fetch: points go, assists (a different fetch) stay.
        self.assertEqual(['player_assists'], list(events['drop']['markets']))
        self.assertNotIn('only_points', events)
        # Another league is never touched.
        self.assertIn('player_points', events['other_league']['markets'])

    def test_capture_clears_expired_markets_from_disk(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        # Stored by a fetch long ago, relative to the real clock this test runs under.
        long_ago = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        old = {'events': {'e1': {**self.event(), 'commence_time': '2099-01-01T00:00:00Z',
                                 'markets': {'player_rebounds': {'captured_at': long_ago, 'quotes': self.quotes()}}}}}
        store = Path(tmp.name) / 'latest.json'
        store.write_text(json.dumps(old))
        with patch.object(ing, 'STORE', store), patch.object(ing, 'ODDS_API_KEY', 'k'), \
                patch.object(ing, 'fetch', FakeProvider()):
            ing.capture('basketball_nba', ['player_points'], 1)
        markets = json.loads(store.read_text())['events']['e1']['markets']
        self.assertEqual(['player_points'], list(markets))

    def test_capture_replaces_earlier_games_of_the_same_markets(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        stale = {'events': {'old': self.event(player_points=self.market(10))}}
        store = Path(tmp.name) / 'latest.json'
        store.write_text(json.dumps(stale))
        with patch.object(ing, 'STORE', store), patch.object(ing, 'ODDS_API_KEY', 'k'), \
                patch.object(ing, 'fetch', FakeProvider()):
            ing.capture('basketball_nba', ['player_points'], 2)
            kept = set(json.loads(store.read_text())['events'])
        self.assertEqual({'e1', 'e2'}, kept)


class Refresh(unittest.TestCase):
    OK = {'events': 2, 'planned': 2, 'credits_used': 2, 'stopped': None, 'remaining': 100}

    def test_no_cooldown_and_no_daily_budget(self):
        calls = []

        def capture(sport, markets, count):
            calls.append(count)
            return self.OK

        for _ in range(3):  # back to back, each far over any old 300-credit day
            code, body = svc.run_props_refresh('basketball_nba', ['player_points'], 20, capture=capture)
            self.assertEqual(code, 200)
            self.assertTrue(body['refreshed'])
        self.assertEqual(calls, [20, 20, 20])

    def test_response_reports_bets_found_for_the_league(self):
        mine = {'sport_key': 'basketball_nba', 'ev': '0.02'}
        losing = {'sport_key': 'basketball_nba', 'ev': '-0.03'}
        other = {'sport_key': 'icehockey_nhl', 'ev': '0.10'}
        with patch.object(svc.props, 'bets', return_value=[mine, losing, other]):
            _, body = svc.run_props_refresh('basketball_nba', ['player_points'], 2, capture=lambda *a: self.OK)
        self.assertEqual(body['bets_found'], 2)
        self.assertIn('2 NBA bets priced, 1 with positive EV.', body['message'])

    def test_response_carries_a_message_and_no_budget_fields(self):
        _, body = svc.run_props_refresh('basketball_nba', ['player_points'], 2, capture=lambda *a: self.OK)
        self.assertIn('Fetched props for 2 games', body['message'])
        for gone in ('credits_today', 'daily_credits', 'retry_after_seconds', 'quota', 'last_result'):
            self.assertNotIn(gone, body)

    def test_nothing_fetched_is_not_a_refresh_and_explains_itself(self):
        stopped = {'events': 0, 'planned': 3, 'credits_used': 0, 'stopped': 'out_of_credits', 'remaining': 1}
        code, body = svc.run_props_refresh('basketball_nba', ['player_points'], 3, capture=lambda *a: stopped)
        self.assertEqual(code, 200)
        self.assertFalse(body['refreshed'])
        self.assertEqual(body['stopped'], 'out_of_credits')
        self.assertIn('left on your Odds API key', body['message'])

    def test_provider_failure_and_validation(self):
        def boom(*a):
            raise ValueError('Events HTTP 500; props not requested')

        code, body = svc.run_props_refresh('basketball_nba', ['player_points'], 2, capture=boom)
        self.assertEqual(code, 502)
        self.assertIn('HTTP 500', body['error'])
        for bad in (('nope', ['player_points'], 2), ('basketball_nba', [], 2), ('basketball_nba', ['x'], 2),
                    ('basketball_nba', ['player_points'], 0), ('basketball_nba', ['player_points'], 21),
                    ('basketball_nba', ['player_points'], True)):
            self.assertEqual(svc.run_props_refresh(*bad, capture=boom)[0], 400)

    def test_status_has_no_budget_or_cooldown(self):
        status = svc.props_status()
        for gone in ('credits_today', 'daily_credits', 'retry_after_seconds', 'quota', 'last_result'):
            self.assertNotIn(gone, status)
        self.assertIn('last_success_at', status)


if __name__ == '__main__':
    unittest.main()
