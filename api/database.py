"""Database-backed catalog: retained pre-game provider quotes -> the same pure calculators.

Read-only. No provider requests, no polling; quotes are only as fresh as the last
user-triggered refresh. Anything that is not a complete, exact, comparable
contract is skipped rather than guessed.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import logging
import os
import threading
import time

from api.catalog import FixtureCatalog, _verify_selections
from corner.links import clean_links

log = logging.getLogger('corner.api.database')

SETTLEMENT_IDENTITY = 'the-odds-api-main-lines-full-game/1'
# Sharp books (Odds API keys): Pinnacle, Betfair exchange UK, ProphetX, Kalshi.
DEFAULT_REFERENCES = ('pinnacle', 'betfair_ex_uk', 'prophetx', 'kalshi')
# Empty = every non-sharp book present in the data is a bettable target; the user filters in the UI.
DEFAULT_TARGETS = ()
FALLBACK_TARGET = 'draftkings'
MARKET_KEYS = {'moneyline': 'h2h', 'spread': 'spreads', 'total': 'totals'}
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
FROM corner.trusted_current_quotes q
JOIN corner.quote_states qs ON qs.id = q.quote_state_id AND qs.code = 'active'
JOIN corner.sportsbooks b ON b.id = q.sportsbook_id AND b.active
JOIN corner.outcomes o ON o.id = q.outcome_id
JOIN corner.outcome_sides os ON os.id = o.outcome_side_id
JOIN corner.markets m ON m.id = o.market_id AND m.subject_participant_id IS NULL
JOIN corner.market_types mt ON mt.id = m.market_type_id AND mt.code = ANY(%(market_codes)s)
JOIN corner.scopes sc ON sc.id = m.scope_id AND sc.code = 'full_game'
JOIN corner.events e ON e.id = m.event_id
JOIN corner.competitions c ON c.id = e.competition_id
LEFT JOIN corner.participants p ON p.id = o.selected_participant_id
LEFT JOIN corner.quote_links ql ON ql.outcome_id = q.outcome_id AND ql.sportsbook_id = q.sportsbook_id
WHERE e.scheduled_start > %(now)s AND q.observed_at >= %(oldest)s AND q.decimal_odds > 1
"""
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
    newest = {}
    for r in rows:
        key = (r['observed_at'], str(r.get('provider_payload_id', '')))
        event = str(r['event_id'])
        if event not in newest or key > newest[event]:
            newest[event] = key
    return [r for r in rows if str(r.get('provider_payload_id', '')) == newest[str(r['event_id'])][1]]


def _num(value):
    value = Decimal(value)
    return '0' if value == 0 else format(value.normalize(), 'f')


def _iso(value):
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def build_raw(quote_rows, participant_rows, *, now, references=DEFAULT_REFERENCES, targets=DEFAULT_TARGETS):
    """Pure transformation of DB rows into the catalog's raw contract shape."""
    people = {}
    for event_id, role, name in participant_rows:
        people.setdefault(str(event_id), {})[role] = name
    games, books, grouped = {}, {}, {}
    for r in quote_rows:
        event = str(r['event_id'])
        if set(people.get(event, {})) != {'home', 'away'} or r['market_code'] not in MARKET_KEYS:
            continue
        key = MARKET_KEYS[r['market_code']]
        side, point = r['side'], r['point']
        if key == 'h2h':
            if side not in {'home', 'away', 'draw'} or point is not None:
                continue
            line = ''
        elif key == 'spreads':
            if side not in {'home', 'away'} or point is None:
                continue
            line = _num(point if side == 'home' else -point)
        else:
            if side not in {'over', 'under'} or point is None:
                continue
            line = _num(point)
        games.setdefault(event, r)
        books[r['book_code']] = r['book_name']
        cell = grouped.setdefault((event, key, line), {}).setdefault(r['book_code'], {})
        cell[side] = r
    contracts, used_games, observed = [], set(), []
    for (event, key, line), by_book in sorted(grouped.items()):
        home, away = people[event]['home'], people[event]['away']
        # Three-way only when every contributing book prices the draw; otherwise a 2-way book would not be comparable.
        sides = ('home', 'away', 'draw') if key == 'h2h' and any('draw' in c for c in by_book.values()) else \
            ('home', 'away') if key != 'totals' else ('over', 'under')
        complete = {b: c for b, c in by_book.items() if set(c) == set(sides)}
        if not complete:
            continue
        names = {'home': home, 'away': away, 'draw': 'Draw', 'over': 'Over', 'under': 'Under'}
        points = {'home': line, 'away': _num(-Decimal(line)) if key == 'spreads' else line, 'over': line, 'under': line,
                  'draw': None}
        contract_id = f'{event}:{key}:{line}' if line else f'{event}:{key}'
        contract = dict(id=contract_id, game_id=event, market_key=key,
                        refund_possible=key in ('spreads', 'totals') and Decimal(line) == Decimal(line).to_integral_value(),
                        selections=[dict(id=s, name=names[s], side=s, point=None if key == 'h2h' else points[s]) for s in sides],
                        prices={b: [format(Decimal(c[s]['decimal_odds']), 'f') for s in sides] for b, c in sorted(complete.items())},
                        lay_prices={},
                        # One entry per selection, in the same order as the prices; None where a book gave no usable link.
                        links={b: [clean_links(b, c[s].get('event_url'), c[s].get('market_url'), c[s].get('outcome_url')) for s in sides]
                               for b, c in sorted(complete.items())},
                        observed={b: _iso(min(c[s]['observed_at'] for s in sides)) for b, c in complete.items()})
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
    targets = tuple(targets) if targets else tuple(sorted(set(books) - set(references))) or (FALLBACK_TARGET,)
    book_ids = sorted(set(books) | set(references) | set(targets))
    return dict(format='corner.product_fixture/1', data_mode='database', captured_at=_iso(captured), observed_at=_iso(captured),
                refund_possible=True, settlement_identity=SETTLEMENT_IDENTITY,
                required_reference_books=list(references), target_books=list(targets),
                books=[dict(id=b, name=books.get(b, b), commission='0') for b in book_ids],
                games=game_list, contracts=contracts)


def load_raw(conn, *, now, max_age, references, targets):
    import psycopg2.extras
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(QUOTE_SQL, dict(market_codes=list(MARKET_KEYS), now=now, oldest=now - max_age))
        rows = cur.fetchall()
        events = sorted({r['event_id'] for r in rows})
        participants = []
        if events:
            cur.execute(PARTICIPANT_SQL, dict(events=[str(e) for e in events]))
            participants = cur.fetchall()
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

    def __init__(self, connect, *, ttl_seconds=None, max_age_seconds=None, references=None, targets=None, clock=None):
        self._connect = connect
        self._ttl = ttl_seconds
        self._max_age = timedelta(seconds=max_age_seconds if max_age_seconds is not None
                                  else int(os.environ.get('CORNER_TOOLS_MAX_AGE_SECONDS', '7200')))
        self._references = tuple(references) if references else _env_books('CORNER_TOOLS_REFERENCE_BOOKS', DEFAULT_REFERENCES)
        self._targets = tuple(targets) if targets else _env_books('CORNER_TOOLS_TARGET_BOOKS', DEFAULT_TARGETS)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()
        self._inner, self._built = None, 0.0
        self._rebuild()

    def _rebuild(self):
        conn = self._connect()
        try:
            conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
            raw = load_raw(conn, now=self._clock(), max_age=self._max_age, references=self._references, targets=self._targets)
        finally:
            conn.close()
        self._inner = FixtureCatalog(raw=raw)
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
                        log.exception('catalog rebuild failed; serving last good snapshot')
                        self._built = time.monotonic()
        return self._inner

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return getattr(self._current(), name)
