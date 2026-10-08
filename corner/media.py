"""Team-logo and player-headshot resolution: pure matching, URL building and the image allowlist.

No network and no disk here, so every rule is unit-testable. The pipeline module fetches and caches.
Images come from ESPN's public CDN (primary) and TheSportsDB (fallback). Only allowlisted https
URLs are ever handed to the browser, and always through the local image proxy, so the browser
stays same-origin.
"""
import re
import unicodedata
from urllib.parse import parse_qs, quote, urlsplit

IMG_PROXY = '/api/refresh/v1/media/img'
ESPN_HOST = 'a.espncdn.com'
TSDB_HOST = 'r2.thesportsdb.com'
LOGO_PX = 64
HEADSHOT_SIZE = (96, 70)

# sport key -> ESPN (sport, league) pairs whose team index is merged (soccer clubs play in several competitions).
_SOCCER = tuple(('soccer', lg) for lg in ('eng.1', 'esp.1', 'ger.1', 'ita.1', 'fra.1', 'usa.1',
                                          'uefa.champions', 'uefa.europa', 'uefa.europa.conf'))
TEAM_SOURCES = {
    'americanfootball_nfl': (('football', 'nfl'),),
    'americanfootball_ncaaf': (('football', 'college-football'),),
    'basketball_nba': (('basketball', 'nba'),),
    'basketball_ncaab': (('basketball', 'mens-college-basketball'),),
    'basketball_wncaab': (('basketball', 'womens-college-basketball'),),
    'basketball_wnba': (('basketball', 'wnba'),),
    'baseball_mlb': (('baseball', 'mlb'),),
    'icehockey_nhl': (('hockey', 'nhl'),),
}
# ESPN sport + league (None = any) used to pick the right "Josh Allen"; and TheSportsDB's sport label.
PLAYER_SPORTS = {
    'americanfootball_nfl': ('football', 'nfl'), 'americanfootball_ncaaf': ('football', 'college-football'),
    'basketball_nba': ('basketball', 'nba'), 'basketball_ncaab': ('basketball', 'mens-college-basketball'),
    'basketball_wncaab': ('basketball', 'womens-college-basketball'), 'basketball_wnba': ('basketball', 'wnba'),
    'baseball_mlb': ('baseball', 'mlb'), 'icehockey_nhl': ('hockey', 'nhl'),
}
TSDB_SPORT = {'football': 'American Football', 'basketball': 'Basketball', 'baseball': 'Baseball',
              'hockey': 'Ice Hockey', 'soccer': 'Soccer', 'tennis': 'Tennis', 'mma': 'Fighting'}
SUFFIXES = {'jr', 'sr', 'ii', 'iii', 'iv', 'v'}
# Club-form words that providers add or drop ("RC Lens" / "Lens", "Atalanta BC" / "Atalanta").
NOISE = {'fc', 'cf', 'sc', 'ac', 'bc', 'afc', 'sk', 'fk', 'ssc', 'as', 'cd', 'ud', 'rc', 'ca', 'sd', 'sv',
         'fsv', 'tsg', 'vfb', 'vfl', 'rb', 'ssv', 'sg', 'us', 'og', 'gnk', 'cp'}
# The Odds API name -> ESPN name, for spellings no rule can bridge. Both sides are normalized.
ALIASES = {
    'Los Angeles Clippers': 'LA Clippers', 'Appalachian State Mountaineers': 'App State Mountaineers',
    'UMass Minutemen': 'Massachusetts Minutemen', 'Athletic Bilbao': 'Athletic Club',
    'Sporting Lisbon': 'Sporting CP', 'New York Red Bulls': 'Red Bull New York', 'Los Angeles FC': 'LAFC',
    'Slavia Praha': 'Slavia Prague', 'Hamburger SV': 'Hamburg SV', 'FSV Mainz 05': 'Mainz',
    'LASK': 'LASK Linz',
}
_TRANSLIT = str.maketrans({'ø': 'o', 'Ø': 'O', 'æ': 'ae', 'Æ': 'AE', 'œ': 'oe', 'ł': 'l', 'Ł': 'L', 'đ': 'd',
                           'Đ': 'D', 'ß': 'ss', 'ı': 'i', 'þ': 'th'})


def sport_family(sport_key):
    """(espn_sport, espn_league_or_None) for a provider sport key, or None when unsupported."""
    if sport_key in PLAYER_SPORTS:
        return PLAYER_SPORTS[sport_key]
    for prefix, sport in (('soccer_', 'soccer'), ('tennis_', 'tennis'), ('mma_', 'mma')):
        if sport_key.startswith(prefix):
            return (sport, None)
    return None


def team_sources(sport_key):
    if sport_key in TEAM_SOURCES:
        return TEAM_SOURCES[sport_key]
    return _SOCCER if sport_key.startswith('soccer_') else ()


def is_individual_sport(sport_key):
    return sport_key.startswith(('tennis_', 'mma_'))


def norm(text, *, drop_suffix=False):
    """Accent-, case- and punctuation-insensitive key: "St. Louis" and "Saint Louis" agree."""
    text = unicodedata.normalize('NFKD', str(text).translate(_TRANSLIT)).encode('ascii', 'ignore').decode()
    text = re.sub(r"['\u2019\u02bc]", '', text.lower()).replace('&', ' and ')
    tokens = re.sub(r'[^a-z0-9]+', ' ', text).split()
    tokens = ['state' if t in ('st', 'saint') else t for t in tokens]
    if drop_suffix:
        tokens = [t for t in tokens if t not in SUFFIXES]
    return ' '.join(tokens)


def core(key):
    """A normalized key without club-form words and year suffixes, or '' if nothing is left."""
    return ' '.join(t for t in key.split() if t not in NOISE and not t.isdigit())


_ALIASES = {}


def _alias(key):
    if not _ALIASES:
        _ALIASES.update({norm(a): norm(b) for a, b in ALIASES.items()})
    return _ALIASES.get(key, key)


def _logo_path(team):
    """Pick the dark-background logo (readable on this UI), falling back to the standard one."""
    hrefs = [l.get('href', '') for l in team.get('logos', [])]
    for want in ('/500-dark/', '/500/'):
        for href in hrefs:
            if want in href and 'scoreboard' not in href and urlsplit(href).hostname == ESPN_HOST:
                return urlsplit(href).path
    return None


def build_team_index(payloads):
    """payloads: parsed ESPN /teams responses. -> {norm_key: {'name', 'path'}} (first writer wins)."""
    index = {}
    for payload in payloads:
        for sport in payload.get('sports', []):
            for league in sport.get('leagues', []):
                for entry in league.get('teams', []):
                    team = entry.get('team', {})
                    path = _logo_path(team)
                    if not path:
                        continue
                    record = {'name': team.get('displayName', ''), 'path': path}
                    for key in {team.get('displayName'), team.get('shortDisplayName'),
                                f"{team.get('location', '')} {team.get('name', '')}"}:
                        if key and norm(key):
                            index.setdefault(norm(key), record)
                        if key and core(norm(key)):
                            # '~' never appears in a normalized key. A core shared by two teams is ambiguous.
                            held = index.setdefault('~' + core(norm(key)), record)
                            if held['name'] != record['name']:
                                index['~' + core(norm(key))] = {**held, 'ambiguous': True}
    return index


def match_team(index, name):
    """Exact normalized match, else a conservative one: same nickname and nested place words."""
    key = _alias(norm(name))
    if not key:
        return None
    if key in index:
        return index[key]
    held = index.get('~' + core(key)) if core(key) else None
    if held and not held.get('ambiguous'):
        return held
    tokens = key.split()
    nick, place = tokens[-1], set(tokens[:-1])
    found = {}
    for other, record in index.items():
        if other.startswith('~'):
            continue
        other_tokens = other.split()
        if other_tokens[-1] != nick:
            continue
        other_place = set(other_tokens[:-1])
        if place and other_place and (place <= other_place or other_place <= place):
            found[record['name']] = record
    # An ambiguous nickname ("Bulldogs") must not guess.
    return next(iter(found.values())) if len(found) == 1 else None


def espn_image(path, width, height):
    return f'https://{ESPN_HOST}/combiner/i?img={path}&w={width}&h={height}'


def proxied(url):
    return f'{IMG_PROXY}?u={quote(url, safe="")}'


def team_logo_url(record):
    return proxied(espn_image(record['path'], LOGO_PX, LOGO_PX))


def same_person(a, b, sport_key):
    """Name equality. Tennis and MMA providers disagree on given/family order, so compare as a set there."""
    a, b = norm(a, drop_suffix=True), norm(b, drop_suffix=True)
    return sorted(a.split()) == sorted(b.split()) if is_individual_sport(sport_key) else a == b


def pick_player(items, name, sport_key):
    """First search hit whose name, sport and league all agree. Returns the proxied URL or None.

    Name equality is required: a wrong face is worse than initials.
    """
    family = sport_family(sport_key)
    for item in items or []:
        if item.get('type', 'player') != 'player' or not item.get('headshot', {}).get('href'):
            continue
        if not same_person(item.get('displayName', ''), name, sport_key):
            continue
        if family and (item.get('sport') != family[0] or (family[1] and item.get('league') != family[1])):
            continue
        href = urlsplit(item['headshot']['href'])
        if href.hostname == ESPN_HOST and href.path.startswith('/i/headshots/'):
            return proxied(espn_image(href.path, *HEADSHOT_SIZE))
    return None


def pick_tsdb_player(players, name, sport_key):
    family = sport_family(sport_key)
    for p in players or []:
        if not same_person(p.get('strPlayer', ''), name, sport_key):
            continue
        if family and p.get('strSport') != TSDB_SPORT.get(family[0]):
            continue
        url = p.get('strCutout') or p.get('strThumb')
        if url and allowed_image(f'{url}/small'):
            return proxied(f'{url}/small')
    return None


def pick_tsdb_team(teams, name, sport_key):
    family = sport_family(sport_key)
    want = norm(name)
    for t in teams or []:
        if norm(t.get('strTeam', '')) != want:
            continue
        if family and t.get('strSport') != TSDB_SPORT.get(family[0]):
            continue
        url = t.get('strBadge') or t.get('strLogo')
        if url and allowed_image(f'{url}/small'):
            return proxied(f'{url}/small')
    return None


_COMBINER_QUERY = re.compile(r'^/i/[A-Za-z0-9_/.\-]+$')
_TSDB_PATH = re.compile(r'^/images/[A-Za-z0-9_/.\-]+\.(png|jpg|jpeg|webp)(/(tiny|small|medium))?$')
_ESPN_PATH = re.compile(r'^/(i|guid)/[A-Za-z0-9_/.\-]+\.(png|jpg|jpeg|webp)$')


def allowed_image(url):
    """True only for the exact shapes of image URL this module builds. Everything else is refused."""
    try:
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.username or parts.password or parts.port or parts.fragment:
            return False
        if parts.hostname == TSDB_HOST:
            return not parts.query and bool(_TSDB_PATH.match(parts.path))
        if parts.hostname != ESPN_HOST:
            return False
        if parts.path == '/combiner/i':
            query = parse_qs(parts.query, keep_blank_values=True)
            return (set(query) == {'img', 'w', 'h'} and all(len(v) == 1 for v in query.values())
                    and bool(_COMBINER_QUERY.match(query['img'][0])) and '..' not in query['img'][0]
                    and query['w'][0].isdigit() and query['h'][0].isdigit()
                    and 1 <= int(query['w'][0]) <= 512 and 1 <= int(query['h'][0]) <= 512)
        return not parts.query and bool(_ESPN_PATH.match(parts.path)) and '..' not in parts.path
    except ValueError:
        return False
