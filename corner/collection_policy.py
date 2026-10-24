"""Pure collection policy. All clock inputs are timezone aware; no provider calls."""
from dataclasses import dataclass
import math
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import pytz

from corner.prop_markets import SCHEDULED_FAMILIES as FAMILIES, family
from corner.additional_markets import SCHEDULED_ADDITIONAL_MARKETS as ADDITIONAL_MARKETS

CENTRAL = pytz.timezone('America/Chicago')
BASE_STANDARD = ('draftkings','fanduel','espnbet','betmgm','betrivers','pinnacle')
LEGACY_STANDARD = BASE_STANDARD + ('betonlineag','williamhill_us','bovada')
STANDARD = LEGACY_STANDARD + ('fanatics',)
# Separate acquisition groups, each within the provider's ten-book billing block.
LEGACY_EXCHANGE = ('novig','betfair_ex_uk','prophetx','kalshi','betopenly','polymarket')
EXCHANGE = ('novig','betfair_ex_uk','prophetx','kalshi','betopenly','polymarket_us')
PROP_EXCHANGE = tuple(book for book in EXCHANGE if not book.startswith('betfair_ex_'))
ALL_BOOKS = STANDARD + EXCHANGE
ALL_BOOKS_PROFILE = 'all-books-pregame-v1'
CADENCE_VERSION = 'all-books-countdown-60s-floor-v1'
PROP_STANDARD = BASE_STANDARD + ('williamhill_us','fanatics','betonlineag','bovada')
SPORTS = ('americanfootball_nfl','americanfootball_ncaaf','basketball_nba','basketball_ncaab',
          'baseball_mlb','icehockey_nhl','soccer_usa_mls','soccer_epl','soccer_spain_la_liga',
          'soccer_germany_bundesliga','soccer_italy_serie_a','soccer_france_ligue_one',
          'soccer_uefa_champs_league','basketball_wnba','basketball_wncaab',
          'tennis_atp','tennis_wta','mma_mixed_martial_arts')
BUDGET_VERSION = 'pregame-lab-history-100k-v1'
POOLS = {'main':7_900_000, 'props':5_000_000, 'metadata':500_000, 'history':100_000}
TOTAL = 15_000_000
PROTECTED = 1_500_000
TRANSIENT_HTTP_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
# NCAA keeps main/additional markets; no scheduled college player-prop purchases.
NO_SCHEDULED_PROPS = frozenset({'americanfootball_ncaaf', 'basketball_ncaab', 'basketball_wncaab'})


def aware(value):
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Timezone-aware timestamps required')
    return value.astimezone(timezone.utc)


def parse(value):
    return aware(datetime.fromisoformat(value.replace('Z','+00:00')))


def open_now(now):
    return aware(now).astimezone(CENTRAL).hour >= 8


def supported(sport):
    return sport in SPORTS or sport.startswith(('tennis_atp_','tennis_wta_'))


def interval(kind, group, now, starts=None):
    """Budgeted countdown bands; exchanges never get a sub-minute exception."""
    remaining = (aware(starts)-aware(now)).total_seconds() if starts is not None else None
    if kind == 'live': return 60
    if kind == 'main':
        if remaining is None or remaining <= 3600: return 120
        if remaining <= 7200: return 180
        if remaining <= 21600: return 300
        if remaining <= 43200: return 600
        return 900
    if kind == 'additional':
        if remaining is None or remaining <= 900: return 60
        if remaining <= 1800: return 120
        if remaining <= 3600: return 300
        return 600
    if remaining is None or remaining <= 0:
        raise ValueError('Upcoming event start required')
    if remaining <= 7200: return 60
    if remaining <= 14400: return 120
    if remaining <= 21600: return 180
    if remaining <= 43200: return 300
    return 600


def additional_limits(cycle_start, cycle_end):
    """Keep daily alternate spend inside main allocation after an 82-key ceiling.

    82 is a conservative planning assumption, not provider coverage or a sport
    cap. Durable monthly pool and global reserve checks remain authoritative.
    Only the existing cycle dates are read; no policy or accounting migration.
    """
    days = max(1, math.ceil((aware(cycle_end)-aware(cycle_start)).total_seconds()/86400))
    # Two groups at two minutes: same maximum credit rate as one at one minute.
    main_ceiling = 82 * 16 * 30 * 3 * 2 * days
    # UTC quota cycles touch an extra Central calendar date at both edges.
    # Budget that partial date too; a busy short day can still hit its cap.
    daily_credits = min(30000, max(0, (POOLS['main']-main_ceiling)//(days+1)))
    # Two groups: at most 36 polls each across the four alternate countdown bands.
    events = min(75, daily_credits // (72 * len(ADDITIONAL_MARKETS)))
    return events, daily_credits


@dataclass(frozen=True)
class Job:
    kind: str
    sport: str
    group: str
    books: tuple
    markets: tuple
    event_id: str = ''
    starts_at: str = ''

    @property
    def key(self):
        # Stable across market-set changes, preventing cadence bypass on restart.
        return sha256(f'{self.kind}:{self.sport}:{self.event_id}:{self.group}'.encode()).hexdigest()

    @property
    def pool(self):
        return 'main' if self.kind in ('additional','live') else self.kind

    @property
    def response_markets(self):
        # v4 automatically returns lay quotes with an exchange h2h request.
        # This expands accepted response scope, never requested/billed markets.
        return self.markets + (('h2h_lay',) if self.kind == 'main' and
                              self.group == 'exchange' and 'h2h' in self.markets else ())

    @property
    def cost(self):
        return len(self.markets) * ((len(self.books)+9)//10)

    def validate(self):
        if self.kind not in ('main','props','additional','live') or not supported(self.sport):
            raise ValueError('Unsupported job scope')
        if self.kind == 'props' and self.sport in NO_SCHEDULED_PROPS:
            raise ValueError('NCAA player props are excluded from scheduled collection')
        allowed = (PROP_EXCHANGE if self.kind == 'props' else EXCHANGE) if self.group == 'exchange' else PROP_STANDARD if self.kind == 'props' else STANDARD
        if self.group not in ('standard','exchange') or self.books != allowed:
            raise ValueError('Book groups must match the reviewed catalog')
        keys = tuple(m.key for m in FAMILIES.get(family(self.sport), ())) if self.kind == 'props' else ADDITIONAL_MARKETS if self.kind == 'additional' else ('h2h','spreads','totals')
        if not keys or self.markets != keys:
            raise ValueError('Job must request every configured market for its scope')
        if self.kind in ('props','additional') and (not self.event_id or not self.starts_at):
            raise ValueError('Props require event identity and start')


def plan(now, active_keys, events, *, additional=False):
    """active_keys must contain expanded tournament keys, not ATP/WTA picker aliases.

    No arbitrary event cap. Live discovery remains a separate adapter gate.
    """
    now = aware(now)
    if not open_now(now):
        return []
    active = sorted(set(active_keys))
    if any(not supported(s) or s in ('tennis_atp','tennis_wta') for s in active):
        raise ValueError('Supply actual configured/expanded sport keys')
    jobs=[]
    league_starts = {}
    for event in events:
        start = parse(event['commence_time'])
        if now < start <= now + timedelta(hours=24):
            sport = event['sport_key']
            league_starts[sport] = min(start, league_starts.get(sport, start))
    for sport in active:
        for group,books in (('standard',STANDARD),('exchange',EXCHANGE)):
            jobs.append(Job('main',sport,group,books,('h2h','spreads','totals'),
                            starts_at=league_starts[sport].isoformat() if sport in league_starts else ''))
    seen=set()
    for event in sorted(events,key=lambda e:(e['commence_time'],e['id'])):
        sport=event['sport_key'];start=parse(event['commence_time'])
        if sport not in active or not now < start <= now+timedelta(hours=24):
            continue
        identity=(sport,event['id'])
        if identity in seen:
            continue
        seen.add(identity)
        if additional and start <= now + timedelta(hours=2):
            for group,books in (('standard',STANDARD),('exchange',EXCHANGE)):
                jobs.append(Job('additional',sport,group,books,ADDITIONAL_MARKETS,event['id'],event['commence_time']))
        if sport in NO_SCHEDULED_PROPS or not family(sport):
            continue
        keys=tuple(m.key for m in FAMILIES[family(sport)])
        for group,books in (('standard',PROP_STANDARD),('exchange',PROP_EXCHANGE)):
            jobs.append(Job('props',sport,group,books,keys,event['id'],event['commence_time']))
    return jobs


def snapshot_max_age(kind, group):
    """Retain quotes for at most 30 minutes of source age, never re-date them."""
    return 1800
