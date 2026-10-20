"""Pure collection policy. All clock inputs are timezone aware; no provider calls."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import pytz

from corner.prop_markets import SCHEDULED_FAMILIES as FAMILIES, family
from corner.additional_markets import SCHEDULED_ADDITIONAL_MARKETS as ADDITIONAL_MARKETS

CENTRAL = pytz.timezone('America/Chicago')
STANDARD = ('draftkings','fanduel','espnbet','betmgm','betrivers','pinnacle')
# Proposed fast classifications require measured provider validation before live use.
EXCHANGE = ('novig','betfair_ex_uk','prophetx','kalshi','betopenly','polymarket')
PROP_STANDARD = STANDARD + ('williamhill_us','fanatics')
SPORTS = ('americanfootball_nfl','americanfootball_ncaaf','basketball_nba','basketball_ncaab',
          'baseball_mlb','icehockey_nhl','soccer_usa_mls','soccer_epl','soccer_spain_la_liga',
          'soccer_germany_bundesliga','soccer_italy_serie_a','soccer_france_ligue_one',
          'soccer_uefa_champs_league','basketball_wnba','basketball_wncaab',
          'tennis_atp','tennis_wta','mma_mixed_martial_arts')
BUDGET_VERSION = 'pregame-lab-history-100k-v1'
POOLS = {'main':7_900_000, 'props':5_000_000, 'metadata':500_000, 'history':100_000}
TOTAL = 15_000_000
PROTECTED = 1_500_000


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
    floor = 20 if group == 'exchange' else 60
    if kind in ('main','additional'):
        return floor
    remaining = (aware(starts)-aware(now)).total_seconds()
    if remaining <= 0:
        raise ValueError('Started event')
    if remaining <= 900:
        return floor
    if remaining <= 7200:
        return 300
    if remaining <= 21600:
        return 900
    return 3600


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
        return 'main' if self.kind == 'additional' else self.kind

    @property
    def cost(self):
        return len(self.markets) * ((len(self.books)+9)//10)

    def validate(self):
        if self.kind not in ('main','props','additional') or not supported(self.sport):
            raise ValueError('Unsupported job scope')
        allowed = EXCHANGE if self.group == 'exchange' else PROP_STANDARD if self.kind == 'props' else STANDARD
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
    for sport in active:
        for group,books in (('standard',STANDARD),('exchange',EXCHANGE)):
            jobs.append(Job('main',sport,group,books,('h2h','spreads','totals')))
    seen=set()
    for event in sorted(events,key=lambda e:(e['commence_time'],e['id'])):
        sport=event['sport_key'];start=parse(event['commence_time'])
        if sport not in active or not now < start <= now+timedelta(hours=24):
            continue
        identity=(sport,event['id'])
        if identity in seen:
            continue
        seen.add(identity)
        if additional and start <= now + timedelta(minutes=30):
            for group,books in (('standard',STANDARD),('exchange',EXCHANGE)):
                jobs.append(Job('additional',sport,group,books,ADDITIONAL_MARKETS,event['id'],event['commence_time']))
        if not family(sport):
            continue
        keys=tuple(m.key for m in FAMILIES[family(sport)])
        for group,books in (('standard',PROP_STANDARD),('exchange',EXCHANGE)):
            jobs.append(Job('props',sport,group,books,keys,event['id'],event['commence_time']))
    return jobs
