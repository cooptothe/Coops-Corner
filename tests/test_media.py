"""Media resolution tests: pure matching, the image allowlist, caching and failure handling. No network."""
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from corner import media
from pipelines import media as service


def team(display, abbr, location, name, rel='500-dark'):
    return {'team': {'displayName': display, 'shortDisplayName': name, 'location': location, 'name': name,
                     'abbreviation': abbr, 'logos': [
                         {'href': f'https://a.espncdn.com/i/teamlogos/x/500/{abbr}.png'},
                         {'href': f'https://a.espncdn.com/i/teamlogos/x/{rel}/{abbr}.png'},
                         {'href': f'https://a.espncdn.com/i/teamlogos/x/{rel}/scoreboard/{abbr}.png'}]}}


def payload(*teams):
    return {'sports': [{'leagues': [{'teams': list(teams)}]}]}


INDEX = media.build_team_index([payload(
    team('Sam Houston Bearkats', 'shsu', 'Sam Houston', 'Bearkats'),
    team('Texas State Bobcats', 'txst', 'Texas State', 'Bobcats'),
    team('Montana State Bobcats', 'mtst', 'Montana State', 'Bobcats'),
    team('Georgia Bulldogs', 'uga', 'Georgia', 'Bulldogs'),
    team('Fresno State Bulldogs', 'fres', 'Fresno State', 'Bulldogs'),
    team('Brighton & Hove Albion', 'bha', 'Brighton & Hove Albion', 'Brighton & Hove Albion'),
    team('Paris Saint-Germain', 'psg', 'Paris Saint-Germain', 'Paris Saint-Germain'),
    team('St. Louis Blues', 'stl', 'St. Louis', 'Blues'),
    team('Hawai\u0027i Rainbow Warriors', 'haw', 'Hawai\u0027i', 'Rainbow Warriors'),
    team('LA Clippers', 'lac', 'LA', 'Clippers'), team('Athletic Club', 'ath', 'Athletic Club', 'Athletic Club'),
    team('Lens', 'rcl', 'Lens', 'Lens'), team('Chicago Fire FC', 'chi', 'Chicago', 'Fire FC'),
    team('SC Paderborn 07', 'pad', 'SC Paderborn 07', 'SC Paderborn 07'),
    team('Bodo/Glimt', 'bod', 'Bodo/Glimt', 'Bodo/Glimt'))])


class Matching(unittest.TestCase):
    def test_norm_is_accent_case_punctuation_insensitive(self):
        self.assertEqual(media.norm('Luka Dončić'), media.norm('luka doncic'))
        self.assertEqual(media.norm('St. Louis Blues'), media.norm('Saint Louis Blues'))
        self.assertEqual(media.norm('Texas A&M Aggies'), media.norm('Texas A & M Aggies'))
        self.assertEqual(media.norm('Marvin Harrison Jr.', drop_suffix=True), media.norm('Marvin Harrison'))

    def test_exact_and_odds_api_spelling_variants(self):
        self.assertEqual(media.match_team(INDEX, 'Georgia Bulldogs')['name'], 'Georgia Bulldogs')
        self.assertEqual(media.match_team(INDEX, 'Brighton and Hove Albion')['name'], 'Brighton & Hove Albion')
        self.assertEqual(media.match_team(INDEX, 'Paris Saint Germain')['name'], 'Paris Saint-Germain')
        self.assertEqual(media.match_team(INDEX, 'Saint Louis Blues')['name'], 'St. Louis Blues')

    def test_apostrophes_translit_aliases_and_club_forms(self):
        for query, expect in (('Hawaii Rainbow Warriors', 'Hawai\u0027i Rainbow Warriors'),
                              ('Los Angeles Clippers', 'LA Clippers'), ('Athletic Bilbao', 'Athletic Club'),
                              ('RC Lens', 'Lens'), ('Chicago Fire', 'Chicago Fire FC'),
                              ('SC Paderborn', 'SC Paderborn 07'), ('Bod\u00f8/Glimt', 'Bodo/Glimt')):
            self.assertEqual(media.match_team(INDEX, query)['name'], expect, query)

    def test_extra_place_word_still_matches_when_unique(self):
        self.assertEqual(media.match_team(INDEX, 'Sam Houston State Bearkats')['name'], 'Sam Houston Bearkats')

    def test_ambiguous_or_unknown_never_guesses(self):
        self.assertIsNone(media.match_team(INDEX, 'State Bobcats'))
        self.assertIsNone(media.match_team(INDEX, 'Viking FK'))
        self.assertIsNone(media.match_team(INDEX, ''))
        self.assertIsNone(media.match_team(INDEX, 'Miami Bulldogs'))

    def test_logo_uses_dark_variant_not_scoreboard(self):
        self.assertTrue(media.match_team(INDEX, 'Georgia Bulldogs')['path'].endswith('/500-dark/uga.png'))
        url = media.team_logo_url(media.match_team(INDEX, 'Georgia Bulldogs'))
        self.assertTrue(url.startswith('/api/refresh/v1/media/img?u='))
        self.assertIn('w%3D64', url)


class Players(unittest.TestCase):
    HIT = {'type': 'player', 'displayName': 'Tyler Warren', 'sport': 'football', 'league': 'nfl',
           'headshot': {'href': 'https://a.espncdn.com/i/headshots/nfl/players/full/4431459.png'}}

    def test_requires_name_sport_and_league_to_agree(self):
        self.assertIn('4431459', media.pick_player([self.HIT], 'Tyler Warren', 'americanfootball_nfl'))
        self.assertIsNone(media.pick_player([self.HIT], 'Tyler Warrens', 'americanfootball_nfl'))
        self.assertIsNone(media.pick_player([self.HIT], 'Tyler Warren', 'basketball_nba'))
        self.assertIsNone(media.pick_player([self.HIT], 'Tyler Warren', 'americanfootball_ncaaf'))

    def test_suffix_and_accents_are_ignored(self):
        hit = {**self.HIT, 'displayName': 'Luka Doncic', 'sport': 'basketball', 'league': 'nba'}
        self.assertTrue(media.pick_player([hit], 'Luka Dončić', 'basketball_nba'))
        hit = {**self.HIT, 'displayName': 'Marvin Harrison Jr.'}
        self.assertTrue(media.pick_player([hit], 'Marvin Harrison', 'americanfootball_nfl'))

    def test_individual_sports_accept_any_league(self):
        hit = {'type': 'player', 'displayName': 'Jannik Sinner', 'sport': 'tennis', 'league': 'atp',
               'headshot': {'href': 'https://a.espncdn.com/i/headshots/tennis/players/full/1.png'}}
        self.assertTrue(media.pick_player([hit], 'Jannik Sinner', 'tennis_atp'))

    def test_tennis_and_mma_names_match_in_either_order(self):
        hit = {'type': 'player', 'displayName': 'Zheng Qinwen', 'sport': 'tennis', 'league': 'wta',
               'headshot': {'href': 'https://a.espncdn.com/i/headshots/tennis/players/full/2.png'}}
        self.assertTrue(media.pick_player([hit], 'Qinwen Zheng', 'tennis_wta'))
        hit = {**self.HIT, 'displayName': 'Warren Tyler'}
        self.assertIsNone(media.pick_player([hit], 'Tyler Warren', 'americanfootball_nfl'))

    def test_fallback_player_needs_matching_sport(self):
        p = {'strPlayer': 'Tyler Warren', 'strSport': 'American Football',
             'strCutout': 'https://r2.thesportsdb.com/images/media/player/cutout/abc.png'}
        self.assertTrue(media.pick_tsdb_player([p], 'Tyler Warren', 'americanfootball_nfl'))
        self.assertIsNone(media.pick_tsdb_player([p], 'Tyler Warren', 'basketball_nba'))


class Allowlist(unittest.TestCase):
    OK = [
        'https://a.espncdn.com/combiner/i?img=/i/teamlogos/nfl/500-dark/pit.png&w=64&h=64',
        'https://a.espncdn.com/i/teamlogos/nfl/500/pit.png',
        'https://r2.thesportsdb.com/images/media/player/cutout/5b5iub1787592292.png/small',
    ]
    BAD = [
        'http://a.espncdn.com/i/teamlogos/nfl/500/pit.png',
        'https://evil.example/i/teamlogos/nfl/500/pit.png',
        'https://a.espncdn.com@evil.example/i/x.png',
        'https://user:pw@a.espncdn.com/i/x.png',
        'https://a.espncdn.com:8443/i/x.png',
        'https://a.espncdn.com/i/../secret.png',
        'https://a.espncdn.com/i/logo.svg',
        'https://a.espncdn.com/combiner/i?img=https://evil.example/x.png&w=64&h=64',
        'https://a.espncdn.com/combiner/i?img=/i/x.png&w=64&h=64&extra=1',
        'https://a.espncdn.com/combiner/i?img=/i/x.png&w=9999&h=64',
        'https://a.espncdn.com/combiner/i?img=/i/../x.png&w=64&h=64',
        'https://r2.thesportsdb.com/images/media/player/cutout/x.svg',
        'https://r2.thesportsdb.com/api/v1/json/3/searchteams.php',
        'https://r2.thesportsdb.com/images/x.png?cache=1',
        'file:///etc/passwd', '', 'not a url',
    ]

    def test_allows_only_the_shapes_we_build(self):
        for url in self.OK:
            self.assertTrue(media.allowed_image(url), url)
        for url in self.BAD:
            self.assertFalse(media.allowed_image(url), url)


class Store(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.now = 1_000_000.0
        self.calls = []
        self.fail = False

    def store(self, search=None):
        def fetch_json(url, params=None):
            self.calls.append((url, params))
            if self.fail:
                raise service.UpstreamError('down')
            if url.endswith('/teams'):
                return payload(team('Georgia Bulldogs', 'uga', 'Georgia', 'Bulldogs'))
            if 'search' in url and 'espn' in url:
                return search if search is not None else {'items': []}
            return {'teams': None, 'player': None}
        return service.MediaStore(cache=self.dir, fetch_json=fetch_json, fetch_image=lambda u: (b'PNG', 'image/png'),
                                  clock=lambda: self.now)

    def test_players_are_cached_and_failures_are_not(self):
        hit = {'items': [Players.HIT]}
        s = self.store(hit)
        self.fail = True
        results, retry = s.resolve('player', 'americanfootball_nfl', ['Tyler Warren'])
        self.assertIsNone(results['Tyler Warren'])
        self.assertEqual(retry, ['Tyler Warren'])  # a failure is retried, not remembered as a miss
        self.fail = False
        self.now += 120  # past the backoff
        url = s.resolve('player', 'americanfootball_nfl', ['Tyler Warren'])[0]['Tyler Warren']
        self.assertIn('4431459', url)
        before = len(self.calls)
        self.assertEqual(s.resolve('player', 'americanfootball_nfl', ['Tyler Warren'])[0]['Tyler Warren'], url)
        self.assertEqual(len(self.calls), before)
        # A fresh process reads the persisted cache.
        again = self.store(hit)
        self.assertEqual(again.resolve('player', 'americanfootball_nfl', ['Tyler Warren'])[0]['Tyler Warren'], url)
        self.assertEqual(len(self.calls), before)

    def test_clean_miss_is_cached_for_a_day_then_retried(self):
        s = self.store({'items': []})
        s.resolve('player', 'americanfootball_nfl', ['Nobody Atall'])
        n = len(self.calls)
        s.resolve('player', 'americanfootball_nfl', ['Nobody Atall'])
        self.assertEqual(len(self.calls), n)
        self.now += service.MISS_TTL + 1
        s.resolve('player', 'americanfootball_nfl', ['Nobody Atall'])
        self.assertGreater(len(self.calls), n)

    def test_unreachable_espn_never_caches_a_false_miss(self):
        s = self.store()
        self.fail = True
        results, retry = s.resolve('team', 'americanfootball_ncaaf', ['Georgia Bulldogs'])
        self.assertEqual((results['Georgia Bulldogs'], retry), (None, ['Georgia Bulldogs']))
        self.fail = False
        self.now += 120
        out, retry = s.resolve('team', 'americanfootball_ncaaf', ['Georgia Bulldogs'])
        self.assertIn('uga.png', out['Georgia Bulldogs'])
        self.assertEqual(retry, [])

    def test_teams_use_one_index_fetch(self):
        s = self.store()
        out, _ = s.resolve('team', 'americanfootball_ncaaf', ['Georgia Bulldogs', 'Georgia Bulldogs'])
        self.assertIn('uga.png', out['Georgia Bulldogs'])
        self.assertEqual(sum(u.endswith('/teams') for u, _ in self.calls), 1)

    def test_image_proxy_refuses_unlisted_urls_without_fetching(self):
        fetched = []
        s = service.MediaStore(cache=self.dir, fetch_json=None,
                               fetch_image=lambda u: fetched.append(u) or (b'x', 'image/png'))
        self.assertIsNone(s.image('https://evil.example/a.png'))
        self.assertEqual(fetched, [])
        ok = Allowlist.OK[1]
        self.assertEqual(s.image(ok), (b'x', 'image/png'))
        self.assertEqual(s.image(ok), (b'x', 'image/png'))
        self.assertEqual(fetched, [ok])


class Routes(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = service.MediaStore(cache=tmp.name, fetch_json=lambda u, p=None: {'items': [], 'teams': [], 'sports': []},
                                   fetch_image=lambda u: (b'\x89PNG', 'image/png'))
        app = FastAPI()
        app.include_router(service.create_router(store))
        self.client = TestClient(app)

    def test_resolve_validates_input(self):
        base = '/api/refresh/v1/media/resolve'
        self.assertEqual(self.client.get(base, params={'kind': 'x', 'sport': 'basketball_nba', 'n': 'A'}).status_code, 400)
        self.assertEqual(self.client.get(base, params={'kind': 'team', 'sport': '../etc', 'n': 'A'}).status_code, 400)
        self.assertEqual(self.client.get(base, params={'kind': 'team', 'sport': 'cricket_ipl', 'n': 'A'}).status_code, 400)
        self.assertEqual(self.client.get(base, params={'kind': 'team', 'sport': 'basketball_nba'}).status_code, 400)
        self.assertEqual(self.client.get(base, params={'kind': 'team', 'sport': 'basketball_nba', 'n': 'x' * 81}).status_code, 400)
        self.assertEqual(self.client.get(base, params={'kind': 'team', 'sport': 'basketball_nba', 'n': ['a'] * 41}).status_code, 400)
        ok = self.client.get(base, params={'kind': 'player', 'sport': 'basketball_nba', 'n': 'Luka Doncic'})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json(), {'results': {'Luka Doncic': None}, 'retry': []})

    def test_image_route_headers_and_refusal(self):
        img = '/api/refresh/v1/media/img'
        self.assertEqual(self.client.get(img, params={'u': 'https://evil.example/a.png'}).status_code, 404)
        res = self.client.get(img, params={'u': Allowlist.OK[1]})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers['content-type'], 'image/png')
        self.assertEqual(res.headers['x-content-type-options'], 'nosniff')
        self.assertIn('immutable', res.headers['cache-control'])


if __name__ == '__main__':
    unittest.main()
