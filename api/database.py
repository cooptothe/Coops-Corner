"""Database-backed catalog: retained pre-game provider quotes -> the same pure calculators.

Read-only. No provider requests, no polling; quotes are only as fresh as the last
user-triggered refresh. Anything that is not a complete, exact, comparable
contract is skipped rather than guessed.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import logging
import json
import sqlite3
from contextlib import closing
import os
import threading
import time

from api.catalog import FixtureCatalog, _verify_selections
from corner.links import clean_links
from corner.collection_readers import store_path as scheduled_store_path, main_scopes
from corner.native_ids import native_ids
from corner.book_policy import supported_book, supported_books
from corner.pricing import fee_policy, reference_eligible
from corner.reference_weights import REFERENCE_BOOKS

log = logging.getLogger('corner.api.database')

SETTLEMENT_IDENTITY = 'the-odds-api-main-lines-full-game/1'
# Main-line references; these books remain eligible betting targets too.
DEFAULT_REFERENCES = tuple(sorted(REFERENCE_BOOKS))
# Empty = every book present in the data is a bettable target; the user filters in the UI.
DEFAULT_TARGETS = ()
FALLBACK_TARGET = 'draftkings'
from corner.additional_markets import MARKET_TYPES as ADDITIONAL_TYPES, LINE_MARKETS, SPREAD_MARKETS, TOTAL_MARKETS
MARKET_KEYS = {'moneyline': 'h2h', 'spread': 'spreads', 'total': 'totals', **{v:k for k,v in ADDITIONAL_TYPES.items()}}
# Competition code -> Odds API sport key, so game filters use the same keys as the refresh picker.
from corner.ingestion import SPORT_KEY_MAPPINGS  # noqa: E402
SPORT_KEYS = {value[2]: key for key, value in SPORT_KEY_MAPPINGS.items()}
SPORT_KEYS.update(atp='tennis_atp', wta='tennis_wta')
# Short names for the league pickers (the stored display names are long).
SPORT_LABELS = {
    'americanfootball_nfl': 'NFL', 'americanfootball_ncaaf': 'NCAAF', 'basketball_nba': 'NBA',
    'basketball_ncaab': 'NCAAB (Men)', 'basketball_wncaab': 'NCAAB (Women)', 'basketball_wnba': 'WNBA',
    'baseball_mlb': 'MLB', 'icehockey_nhl': 'NHL', 'mma_mixed_martial_arts': 'MMA',
    'tennis_atp': 'Tennis (Men)', 'tennis_wta': 'Tennis (Women)', 'soccer_usa_mls': 'MLS',
    'soccer_epl': 'Premier League', 'soccer_spain_la_liga': 'La Liga', 'soccer_germany_bundesliga': 'Bundesliga',
    'soccer_italy_serie_a': 'Serie A', 'soccer_france_ligue_one': 'Ligue 1', 'soccer_uefa_champs_league': 'Champions League',
}


def _label(code, name):
    return SPORT_LABELS.get(SPORT_KEYS.get(code, code), name)

QUOTE_SQL = """
SELECT e.id AS event_id, c.code AS competition_code, c.display_name AS competition_name, e.scheduled_start,
       mt.code AS market_code, sc.code AS scope_code, os.code AS side, o.point,
       p.display_name AS selection_name, b.code AS book_code, b.display_name AS book_name,
       q.decimal_odds, q.observed_at, q.provider_updated_at, q.provider_payload_id,
       ql.event_url, ql.market_url, ql.outcome_url
FROM corner.events e
JOIN corner.competitions c ON c.id = e.competition_id
JOIN corner.markets m ON m.event_id = e.id AND m.subject_participant_id IS NULL
JOIN corner.market_types mt ON mt.id = m.market_type_id AND mt.code = ANY(%(market_codes)s)
JOIN corner.scopes sc ON sc.id = m.scope_id AND sc.code = 'full_game'
JOIN corner.outcomes o ON o.market_id = m.id
JOIN corner.outcome_sides os ON os.id = o.outcome_side_id
JOIN corner.sportsbooks b ON b.active
JOIN LATERAL corner.trusted_quote_for_stream(o.id, b.id) q ON true
JOIN corner.quote_states qs ON qs.id = q.quote_state_id AND qs.code = 'active'
LEFT JOIN corner.participants p ON p.id = o.selected_participant_id
LEFT JOIN corner.quote_links ql ON ql.outcome_id = q.outcome_id AND ql.sportsbook_id = q.sportsbook_id
WHERE e.scheduled_start > %(now)s AND q.observed_at >= %(oldest)s AND q.decimal_odds > 1
"""
# Bound PostgreSQL probes to the current scheduler's event/book/market/point
# inventory, rather than every historical line of every upcoming event.
SCOPED_QUOTE_SQL = QUOTE_SQL.replace(
    'SELECT e.id AS event_id,', 'SELECT scope.external_id AS source_event_id, e.id AS event_id,'
).replace('FROM corner.events e', """FROM jsonb_to_recordset(%(scopes)s::jsonb) AS scope(
    external_id text, book_code text, market_code text, point numeric, captured_at timestamptz)
JOIN corner.event_provider_identities epi ON epi.external_id=scope.external_id AND epi.active
  AND epi.provider_id=(SELECT id FROM corner.providers WHERE code='the_odds_api')
JOIN corner.events e ON e.id=epi.event_id""").replace(
    'JOIN corner.sportsbooks b ON b.active', 'JOIN corner.sportsbooks b ON b.active AND b.code=scope.book_code'
).replace(
    "WHERE e.scheduled_start >", "WHERE mt.code=scope.market_code AND o.point IS NOT DISTINCT FROM scope.point\n  AND q.observed_at=scope.captured_at AND e.scheduled_start >"
)


def current_quote_scopes(path, now):
    """Read only current, nonexpired line identities; never fabricate quote data."""
    stamp=now.timestamp()
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
        rows=db.execute("SELECT event_id,book,market,captured_at,payload FROM snapshots WHERE kind IN ('main','additional') AND expires_at>? AND starts_at>? AND source_at>? AND captured_at>?",(stamp,stamp,stamp-1800,stamp-1800))
        scopes={}
        reverse={value:key for key,value in MARKET_KEYS.items()}
        for event,book,market,captured,payload in rows:
            code=reverse.get(market)
            if code is None or not supported_book(book):continue
            for outcome in json.loads(payload).get('market',{}).get('outcomes',[]):
                point=outcome.get('point')
                if point is not None:
                    try:
                        point=Decimal(str(point))
                        if not point.is_finite():continue
                        point=str(point)
                    except (ValueError,ArithmeticError):continue
                key=(event,book,code,point)
                scopes[key]=dict(external_id=event,book_code=book,market_code=code,
                                 point=point,captured_at=datetime.fromtimestamp(captured,timezone.utc).isoformat())
        return list(scopes.values())


PARTICIPANT_SQL = """
SELECT ep.event_id, ep.role, p.display_name
FROM corner.event_participants ep JOIN corner.participants p ON p.id = ep.participant_id
WHERE ep.event_id = ANY(%(events)s::uuid[]) AND ep.role IN ('home', 'away')
"""


def keep_latest_capture(rows):
    """A game is priced only by its newest capture.

    The database keeps the latest observation per outcome and book, so a line a book has since pulled
    would otherwise stay "current" until it ages out and show up as a phantom bet. Each capture is the
    full board for its games, so anything absent from the newest one is gone.
    """
    if scheduled_store_path() is not None:
        # main_scopes has already checked each book/market against the current
        # scheduler snapshot. Never discard standard books after a fast-group update.
        return rows
    newest = {}
    for r in rows:
        key = (r['observed_at'], str(r.get('provider_payload_id', '')))
        # Event endpoint additions are captured separately from featured markets.
        scope = (str(r['event_id']), r['market_code'] in ADDITIONAL_TYPES.values())
        if scope not in newest or key > newest[scope]:
            newest[scope] = key
    return [r for r in rows if str(r.get('provider_payload_id', '')) == newest[(str(r['event_id']), r['market_code'] in ADDITIONAL_TYPES.values())][1]]


def _num(value):
    value = Decimal(value)
    return '0' if value == 0 else format(value.normalize(), 'f')


def _iso(value):
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def _source_time(row):
    """Display the earlier provider/capture time; rereading is not a new price."""
    return min(row['observed_at'], row.get('provider_updated_at') or row['observed_at'])


def build_raw(quote_rows, participant_rows, *, now, references=None, targets=DEFAULT_TARGETS):
    """Pure transformation of DB rows into the catalog's raw contract shape."""
    explicit_references = references is not None
    references, targets = supported_books(references or ()), supported_books(targets)
    people = {}
    for event_id, role, name in participant_rows:
        people.setdefault(str(event_id), {})[role] = name
    games, books, grouped = {}, {}, {}
    for r in quote_rows:
        if not supported_book(r['book_code']):
            continue
        event = str(r['event_id'])
        if set(people.get(event, {})) != {'home', 'away'} or r['market_code'] not in MARKET_KEYS:
            continue
        key = MARKET_KEYS[r['market_code']]
        side, point = r['side'], r['point']
        subject = r.get('selection_name') if key in {'team_totals', 'alternate_team_totals'} else ''
        if key in {'team_totals', 'alternate_team_totals'} and subject not in people[event].values():
            continue
        if key in {'h2h', 'draw_no_bet', 'btts'}:
            allowed_sides = {'yes','no'} if key == 'btts' else {'home','away'} if key == 'draw_no_bet' else {'home','away','draw'}
            if side not in allowed_sides or point is not None:
                continue
            line = ''
        elif key in SPREAD_MARKETS:
            if side not in {'home', 'away'} or point is None:
                continue
            line = _num(point if side == 'home' else -point)
        else:
            if side not in {'over', 'under'} or point is None:
                continue
            line = _num(point)
        games.setdefault(event, r)
        books[r['book_code']] = r['book_name']
        cell = grouped.setdefault((event, key, line, subject), {}).setdefault(r['book_code'], {})
        cell[side] = r
    contracts, used_games, observed = [], set(), []
    for (event, key, line, subject), by_book in sorted(grouped.items()):
        home, away = people[event]['home'], people[event]['away']
        # Three-way only when every contributing book prices the draw; otherwise a 2-way book would not be comparable.
        sides = ('home', 'away', 'draw') if key == 'h2h' and any('draw' in c for c in by_book.values()) else \
            ('yes','no') if key == 'btts' else ('over','under') if key in TOTAL_MARKETS else ('home','away')
        complete = {b: c for b, c in by_book.items() if set(c) == set(sides)}
        if not complete:
            continue
        names = {'home': home, 'away': away, 'draw': 'Draw', 'over': 'Over', 'under': 'Under', 'yes':'Yes', 'no':'No'}
        if key in {'team_totals', 'alternate_team_totals'}:
            names.update(over=f'{subject} Over', under=f'{subject} Under')
        points = {'home': line, 'away': _num(-Decimal(line)) if key in SPREAD_MARKETS else line, 'over': line, 'under': line,
                  'draw': None}
        contract_id = f'{event}:{key}:{line}' if line else f'{event}:{key}'
        if subject:
            from hashlib import sha256
            contract_id += ':' + sha256(subject.encode()).hexdigest()[:16]
        contract = dict(id=contract_id, game_id=event, market_key=key,
                        subject=subject, refund_possible=key == 'draw_no_bet' or key in LINE_MARKETS and Decimal(line) == Decimal(line).to_integral_value(),
                        selections=[dict(id=s, name=names[s], side=s, point=points[s] if key in LINE_MARKETS else None) for s in sides],
                        prices={b: [format(Decimal(c[s]['decimal_odds']), 'f') for s in sides] for b, c in sorted(complete.items())},
                        lay_prices={},
                        # One entry per selection, in the same order as the prices; None where a book gave no usable link.
                        links={b: [clean_links(b, c[s].get('event_url'), c[s].get('market_url'), c[s].get('outcome_url')) for s in sides]
                               for b, c in sorted(complete.items())},
                        source_ids={b: [native_ids(b, link=c[s].get('outcome_url')) for s in sides]
                                    for b, c in sorted(complete.items())},
                        observed={b: _iso(min(_source_time(c[s]) for s in sides)) for b, c in complete.items()})
        game = dict(id=event, sport_key=SPORT_KEYS.get(games[event]['competition_code'], games[event]['competition_code']),
                    competition=_label(games[event]['competition_code'], games[event]['competition_name']), name=f'{away} at {home}',
                    starts_at=_iso(games[event]['scheduled_start']), scope='full_game', participants=sorted([home, away]))
        try:
            _verify_selections(contract, game)
        except ValueError:
            continue
        contracts.append(contract)
        used_games.add(event)
        observed.extend(c[s]['observed_at'] for c in complete.values() for s in sides)
    game_list = []
    for event in sorted(used_games):
        r, home, away = games[event], people[event]['home'], people[event]['away']
        game_list.append(dict(id=event, sport_key=SPORT_KEYS.get(r['competition_code'], r['competition_code']),
                              competition=_label(r['competition_code'], r['competition_name']), name=f'{away} at {home}', starts_at=_iso(r['scheduled_start']),
                              scope='full_game', participants=sorted([home, away])))
    captured = max(observed) if observed else now
    if not explicit_references:
        references=tuple(sorted(b for b in books if reference_eligible(b)))
    targets = tuple(targets) if targets else tuple(sorted(books)) or (FALLBACK_TARGET,)
    book_ids = sorted(set(books) | set(references) | set(targets))
    return dict(format='corner.product_fixture/1', data_mode='database', captured_at=_iso(captured), observed_at=_iso(captured),
                refund_possible=True, settlement_identity=SETTLEMENT_IDENTITY,
                required_reference_books=list(references), target_books=list(targets),
                books=[dict(id=b, name=books.get(b, b), commission=None if fee_policy(b).commission is None else str(fee_policy(b).commission),
                            fee_status=fee_policy(b).status) for b in book_ids],
                games=game_list, contracts=contracts)


FINGERPRINT_SQL = (
    'SELECT count(*), max(created_at) FROM corner.odds_observations',
    'SELECT count(*) FROM corner.observation_dispositions',
    'SELECT count(*), max(captured_at) FROM corner.quote_links',
    'SELECT count(*), max(updated_at) FROM corner.events',
)
# Even with an unchanged fingerprint, re-read the database at least this often.
SOURCE_MAX_AGE_SECONDS = 600


def fingerprint(conn):
    """A cheap summary of everything QUOTE_SQL reads that can change: the ledger only grows, and links, decisions and events are counted.

    None when it cannot be read (for example a role without access), which just means no caching.
    """
    try:
        with conn.cursor() as cur:
            parts = []
            for statement in FINGERPRINT_SQL:
                cur.execute(statement)
                parts.append(tuple(cur.fetchone()))
        return tuple(parts)
    except Exception:
        conn.rollback()
        return None


def publication_revision(path):
    """Tiny durable invalidation key; advances atomically with publication ACK."""
    if path is None:return None
    import sqlite3
    from contextlib import closing
    from pathlib import Path
    try:
        with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
            row=db.execute('SELECT revision FROM publication_revision WHERE id=1').fetchone()
        return ('scheduled-publication',str(path),row[0]) if row else None
    except (sqlite3.Error,OSError):
        return None  # Older workers keep the original PostgreSQL fingerprint.


def _scope_key(row):
    point=row.get('point')
    return (row.get('external_id',row.get('source_event_id')),row['book_code'],
            row['market_code'],None if point is None else _num(point))


def read_source(conn, *, now, max_age, cache=None):
    """Refresh changed scheduler scopes; revalidate time and withdrawals on reuse."""
    import psycopg2.extras
    oldest=now-max_age
    path=scheduled_store_path()
    mark=publication_revision(path) if cache is not None else None
    if mark is None and cache is not None:mark=fingerprint(conn)
    tick=time.monotonic()
    full_at=min(cache.get('full_at',cache.get('at',0)),cache.get('at',0)) if cache else 0
    full_due=not cache or tick-full_at>=SOURCE_MAX_AGE_SECONDS
    if not full_due and mark is not None and cache.get('mark')==mark:
        rows=[r for r in cache['rows'] if r['scheduled_start']>now and r['observed_at']>=oldest]
        cache['queried_scopes']=0
        cache['reused_quotes']=len(rows)
        return rows,cache['participants']

    scopes=current_quote_scopes(path,now) if path is not None else None
    retained=[]
    if scopes is not None and cache is not None and not full_due:
        signatures=cache.get('scope_signatures',{})
        current={_scope_key(row):row['captured_at'] for row in scopes}
        retained=[row for row in cache.get('rows',[]) if
                  signatures.get(_scope_key(row))==current.get(_scope_key(row))
                  and _scope_key(row) in current and row['scheduled_start']>now
                  and row['observed_at']>=oldest]
        scopes=[row for row in scopes if signatures.get(_scope_key(row))!=row['captured_at']]

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        rows=[]
        if scopes is None or scopes:
            parameters=dict(market_codes=list(MARKET_KEYS),now=now,oldest=oldest)
            if scopes is not None:parameters['scopes']=json.dumps(scopes,separators=(',',':'))
            cur.execute(SCOPED_QUOTE_SQL if scopes is not None else QUOTE_SQL,parameters)
            rows=cur.fetchall()
        rows=retained+rows
        events=sorted({row['event_id'] for row in rows})
        participants=[]
        if events:
            cur.execute(PARTICIPANT_SQL,dict(events=[str(e) for e in events]))
            participants=cur.fetchall()
    if cache is not None:
        # Only successful quote rows certify a scope. A capture awaiting SQL
        # publication must be retried after ACK even if its scope is unchanged.
        signatures={_scope_key(row):row['observed_at'].astimezone(timezone.utc).isoformat() for row in rows
                    if row.get('source_event_id') is not None}
        cache.clear()
        if mark is not None:
            cache.update(mark=mark,at=tick,full_at=tick if full_due else full_at,
                         rows=rows,participants=participants,scope_signatures=signatures,
                         queried_scopes=len(scopes) if scopes is not None else None,
                         reused_quotes=len(retained))
    return rows,participants


def load_raw(conn, *, now, max_age, references, targets, cache=None):
    rows, participants = read_source(conn, now=now, max_age=max_age, cache=cache)
    path=scheduled_store_path()
    if path is not None:
        rows=main_scopes(rows,path,now)
    rows = keep_latest_capture(rows)
    return build_raw(rows, [(p['event_id'], p['role'], p['display_name']) for p in participants],
                     now=now, references=references, targets=targets)


def _env_books(name, default):
    value = os.environ.get(name)
    return tuple(b.strip() for b in value.split(',') if b.strip()) if value else default


class LiveCatalog:
    """Proxy that rebuilds the immutable catalog from the database only on reload() (after a user-triggered refresh), or per TTL if one is given.

    A failed rebuild keeps serving the last good snapshot (quote ages stay visible)
    but the very first build must succeed.
    """

    # Static deployment metadata must not enter the rebuilding proxy. ASGI
    # response headers read this on the event loop, outside worker threads.
    data_mode = 'database'


    def __init__(self, connect, *, ttl_seconds=None, max_age_seconds=None, references=None, targets=None, clock=None):
        self._connect = connect
        self._ttl = ttl_seconds if ttl_seconds is not None else 15
        self._max_age = timedelta(seconds=max_age_seconds if max_age_seconds is not None
                                  else int(os.environ.get('CORNER_TOOLS_MAX_AGE_SECONDS', '1800')))
        self._references = tuple(references) if references is not None else None  # Production: all available eligible books; legacy env lists cannot narrow it.
        self._targets = tuple(targets) if targets else _env_books('CORNER_TOOLS_TARGET_BOOKS', DEFAULT_TARGETS)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()
        self._inner, self._built = None, 0.0
        self._raw, self._source = None, {}
        self._rebuild()

    def _rebuild(self):
        conn = self._connect()
        try:
            conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
            raw = load_raw(conn, now=self._clock(), max_age=self._max_age, references=self._references, targets=self._targets,
                           cache=self._source)
        finally:
            conn.close()
        from corner.prop_tools import merge_props
        raw = merge_props(raw, now=self._clock())
        # The catalog is a pure function of this input, so identical input means the identical catalog: keep it.
        if self._inner is None or raw != self._raw:
            self._inner = FixtureCatalog(raw=raw)
            self._raw = raw
        self._built = time.monotonic()

    def reload(self):
        """Rebuild now (after a user-triggered refresh); a failure keeps the last good snapshot."""
        with self._lock:
            self._rebuild()
        return self._inner

    def _current(self):
        if self._ttl is not None and time.monotonic() - self._built > self._ttl:
            with self._lock:
                if time.monotonic() - self._built > self._ttl:
                    try:
                        self._rebuild()
                    except Exception:
                        if scheduled_store_path() is not None:
                            raise  # fail closed rather than serve stale actionable bets
                        log.exception('catalog rebuild failed; serving last good snapshot')
                        self._built = time.monotonic()
        return self._inner

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return getattr(self._current(), name)
