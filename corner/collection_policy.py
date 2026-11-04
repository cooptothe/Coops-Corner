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
CADENCE_VERSION = 'nov20-deadline-countdown-v4'
PROP_STANDARD = BASE_STANDARD + ('williamhill_us','fanatics','betonlineag','bovada')
SPORTS = ('americanfootball_nfl','americanfootball_ncaaf','basketball_nba','basketball_ncaab',
          'baseball_mlb','icehockey_nhl','soccer_usa_mls','soccer_epl','soccer_spain_la_liga',
          'soccer_germany_bundesliga','soccer_italy_serie_a','soccer_france_ligue_one',
          'soccer_uefa_champs_league','basketball_wnba','basketball_wncaab',
          'tennis_atp','tennis_wta','mma_mixed_martial_arts')
BUDGET_VERSION = 'nov20-shared-quota-v3'
POOLS = {'main':5_500_000, 'props':9_500_000, 'metadata':0, 'history':0}
TOTAL = 15_000_000
PROTECTED = 0
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
    now=aware(now)
    from corner.deadline_pacing import START,END
    if START<=now<END:return True  # Free discovery stays available overnight.
    if now>=END:return False  # No implicit spending beyond the owner's deadline.
    return 6 <= now.astimezone(CENTRAL).hour < 22


def job_allowed(job,now):
    now=aware(now)
    if not open_now(now):return False
    from corner.deadline_pacing import active
    if not active(now) or now.astimezone(CENTRAL).hour>=6:return True
    if not job.sport.startswith(('tennis_','soccer_')):return False
    if job.kind=='live':return True
    return bool(job.starts_at and now<parse(job.starts_at)<=now+timedelta(hours=2))


def supported(sport):
    return sport in SPORTS or sport.startswith(('tennis_atp_','tennis_wta_'))


# Upper seconds until start, then minimum seconds between requests.
COUNTDOWN_BANDS = {
    'main': ((7200, 60), (10800, 90), (14400, 120), (21600, 180), (28800, 300), (43200, 600), (86400, 900)),
    'props': ((14400, 60), (21600, 90), (28800, 180), (43200, 300), (86400, 600)),
    'additional': ((600, 60), (1200, 90), (1800, 120), (2700, 180), (3600, 240), (5400, 480), (7200, 600)),
}
# Exchanges have their own provider update cycle. Additional-market admission
# keeps its reviewed shared bands and daily credit ceiling.
EXCHANGE_COUNTDOWN_BANDS = {
    'main': ((21600,20),(28800,60),(43200,120),(86400,300)),
    'props': ((1800,20),(3600,40),(14400,60),(21600,90),(28800,180),(43200,300),(86400,600)),
}


def provider_floor(kind, group):
    if kind == 'live': return 10 if group == 'exchange' else 40
    return 20 if group == 'exchange' else 60


# Upper bound includes a possible immediate poll at every band transition.
ADDITIONAL_POLLS_PER_GROUP = sum(
    math.ceil((upper-(COUNTDOWN_BANDS['additional'][i-1][0] if i else 0))/period)+1
    for i,(upper,period) in enumerate(COUNTDOWN_BANDS['additional']))


def interval(kind, group, now, starts=None):
    """Provider-aligned bands; unknown main starts use a quiet 15-minute board poll."""
    remaining = (aware(starts)-aware(now)).total_seconds() if starts is not None else None
    if kind == 'live': return provider_floor(kind, group)
    if remaining is None:
        if kind == 'main': return 900
        if kind == 'additional': return 60
        raise ValueError('Upcoming event start required')
    if kind == 'props' and remaining <= 0:
        raise ValueError('Upcoming event start required')
    bands = EXCHANGE_COUNTDOWN_BANDS.get(kind, COUNTDOWN_BANDS[kind]) if group == 'exchange' else COUNTDOWN_BANDS[kind]
    return max(provider_floor(kind, group), next((period for upper,period in bands if remaining <= upper), bands[-1][1]))


def additional_limits(cycle_start, cycle_end):
    """Daily alternate subcap; main/live/alternate share the hard main pool.

    No assumed sport-key count can override the global or per-pool reservation
    checks. Faster countdown bands reserve transition overhead per admission.
    """
    daily_credits = 30000
    # Keep every admitted game inside the daily credit ceiling at all new bands.
    events = min(75, daily_credits // (2 * ADDITIONAL_POLLS_PER_GROUP * len(ADDITIONAL_MARKETS)))
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
    from corner.deadline_pacing import active as deadline_active
    for sport in active:
        if deadline_active(now) and sport not in league_starts:continue
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
    return [job for job in jobs if job_allowed(job,now)]


def snapshot_max_age(kind, group):
    """Retain quotes for at most 30 minutes of source age, never re-date them."""
    return 1800
