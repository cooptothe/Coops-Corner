"""Measures closing-line value for tracked bets from the odds ledger (read-only), and stores the result."""
from datetime import datetime, timedelta, timezone
import os
import uuid

from corner import clv
from corner.prop_markets import SHARP_BOOKS
from corner.tracker_store import now_iso

MARKET_CODES = {'h2h': 'moneyline', 'spreads': 'spread', 'totals': 'total',
 'alternate_spreads': 'alternate_spread', 'alternate_totals': 'alternate_total',
 'btts': 'btts', 'draw_no_bet': 'draw_no_bet', 'team_totals': 'team_total'}
WINDOW = timedelta(seconds=int(os.environ.get('CORNER_CLV_WINDOW_SECONDS', '180')))
SETTLE_DELAY = timedelta(minutes=5)

# The latest eligible, active observation per sharp book and outcome in the window before the start. Eligibility
# and the "newest wins" rule are the same as corner.trusted_current_quotes, applied as of the start time.
CLOSE_SQL = """
SELECT e.scheduled_start, b.code AS book, os.code AS side, o.point, q.decimal_odds, q.observed_at, p.display_name
FROM corner.events e
JOIN corner.markets m ON m.event_id = e.id AND m.subject_participant_id IS NULL
JOIN corner.market_types mt ON mt.id = m.market_type_id AND mt.code = %(market)s
JOIN corner.scopes sc ON sc.id = m.scope_id AND sc.code = 'full_game'
JOIN corner.outcomes o ON o.market_id = m.id
JOIN corner.outcome_sides os ON os.id = o.outcome_side_id
LEFT JOIN corner.participants p ON p.id = o.selected_participant_id
CROSS JOIN corner.sportsbooks b
JOIN LATERAL (
    SELECT ob.decimal_odds, ob.observed_at, ob.quote_state_id, ob.provider_updated_at
    FROM corner.odds_observations ob
    WHERE ob.outcome_id = o.id AND ob.sportsbook_id = b.id
      AND ob.observed_at <= e.scheduled_start AND ob.observed_at >= e.scheduled_start - %(window)s
      AND (
        NOT EXISTS (SELECT 1 FROM corner.observation_dispositions d WHERE d.observation_id = ob.id)
        OR (SELECT dt.code FROM corner.observation_dispositions d
            JOIN corner.disposition_types dt ON dt.id = d.disposition_type_id
            WHERE d.observation_id = ob.id ORDER BY d.decided_at DESC, d.id DESC LIMIT 1) = 'reinstated')
    ORDER BY ob.observed_at DESC, ob.id DESC
    LIMIT 1
) q ON TRUE
JOIN corner.quote_states qs ON qs.id = q.quote_state_id AND qs.code = 'active'
WHERE e.id = %(event)s::uuid AND b.code = ANY(%(books)s) AND q.decimal_odds > 1 AND q.provider_updated_at <= e.scheduled_start
 AND q.provider_updated_at >= e.scheduled_start - %(window)s
"""


def connect():
    import psycopg2
    from config import DB_CONFIG
    return psycopg2.connect(**DB_CONFIG)


def fetch_close(game_id, market_key):
    """(scheduled start, closing rows) for one game and market, from a read-only session."""
    conn = connect()
    try:
        conn.set_session(readonly=True)
        with conn.cursor() as cur:
            cur.execute(CLOSE_SQL, {'event': game_id, 'market': MARKET_CODES[market_key],
                                    'window': WINDOW, 'books': sorted(SHARP_BOOKS)})
            found = cur.fetchall()
            cur.execute('SELECT scheduled_start FROM corner.events WHERE id = %s::uuid', (game_id,))
            start = cur.fetchone()
    finally:
        conn.close()
    rows = [{'book': r[1], 'side': r[2], 'point': r[3], 'decimal_odds': r[4], 'subject': r[6]} for r in found]
    return (start[0] if start else None), rows


def _valid_uuid(value):
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


def eligible(bet, now):
    """Every unmeasured tracked bet is assessed after its start, regardless of result."""
    if bet.get('clv') is not None:
        return False
    if bet.get('legs'):
        return all(_started(leg.get('starts_at'), now) for leg in bet['legs'])
    return not bet.get('starts_at') or _started(bet['starts_at'], now)


def _started(stamp, now):
    if not stamp:
        return False
    value = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    return value.replace(tzinfo=value.tzinfo or timezone.utc) + SETTLE_DELAY <= now


def unavailable(reason, at):
    return {'status': 'unavailable', 'pct': None, 'reason': reason, 'at': at}


def retain_local_props(data, path):
    """Retain last per-book scopes inside the existing local props store; no network."""
    import json
    history = data.setdefault('_clv_history', {})
    if path.exists():
        old = json.loads(path.read_text(encoding='utf-8'))
        history.update(old.get('_clv_history', {}))
    for event_id, event in data.get('events', {}).items():
        for market, cell in event.get('markets', {}).items():
            captured = cell.get('captured_at')
            if not captured:
                continue
            from pipelines.props_ingestion import BOOKS
            for book in set(BOOKS.split(',')) | {q['book'] for q in cell.get('quotes', [])}:
                key = json.dumps([event_id, market, book], separators=(',', ':'))
                previous = history.get(key)
                if previous and previous['captured_at'] > captured:
                    continue
                history[key] = {'start': event['commence_time'], 'sport': event['sport_key'],
                    'captured_at': captured, 'quotes': [q for q in cell['quotes'] if q['book'] == book]}


def fetch_props_close(ref, starts_at):
    """Latest retained scope per book before kickoff, never a live or historical provider request."""
    import json
    import sqlite3
    from pathlib import Path
    from corner.collection_readers import store_path
    from corner.prop_markets import market_meta, normalize_event
    from corner.collection_policy import parse
    start = parse(starts_at)
    scopes = []
    path = store_path()
    if path is not None:
        if not Path(path).exists():
            return start, []
        db = sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True)
        try:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            table = 'clv_scopes' if 'clv_scopes' in tables else 'snapshots'
            values = db.execute(f"SELECT sport,book,captured_at,payload FROM {table} WHERE kind='props' AND event_id=? AND market=? AND captured_at<=? ORDER BY captured_at",
                (ref.get('game_id'), ref.get('prop_market'), start.timestamp())).fetchall()
            latest = {}
            for sport, book, captured, payload in values:
                latest[book] = (sport, captured, json.loads(payload))
            for book, (sport, captured, part) in latest.items():
                meta = market_meta(sport, ref.get('prop_market'))
                if meta:
                    quotes = normalize_event({**part['event'], 'bookmakers': [{**part['book'], 'markets': [part['market']]}]}, ref['prop_market'], meta)
                    scopes.append((captured, quotes, meta.sides))
        finally:
            db.close()
    else:
        from pipelines.props_ingestion import STORE
        if not STORE.exists():
            return start, []
        data = json.loads(STORE.read_text(encoding='utf-8'))
        for key, cell in data.get('_clv_history', {}).items():
            event, market, book = json.loads(key)
            if event != ref.get('game_id') or market != ref.get('prop_market'):
                continue
            meta = market_meta(cell['sport'], market)
            if meta:
                scopes.append((parse(cell['captured_at']).timestamp(), cell['quotes'], meta.sides))
    rows = []
    for captured, quotes, sides in scopes:
        if not 0 <= start.timestamp()-captured <= 180:
            continue
        for q in quotes:
            if q['player'] != ref.get('player'):
                continue
            updated = q.get('updated_at')
            if not updated or not 0 <= start.timestamp()-parse(updated).timestamp() <= 180:
                continue
            rows.append({'book': q['book'], 'side': sides[q['side']].lower(), 'point': q['point'], 'decimal_odds': q['price']})
    return start, rows


def measure_pending(store, fetch=fetch_close, now=None, sharps=SHARP_BOOKS):
    """Assess every bet and every parlay leg. Closing prices are retained data only."""
    from decimal import Decimal
    from corner.prop_markets import PROP_SHARP_BOOKS
    now = now or datetime.now(timezone.utc)
    at = now.isoformat()
    cache, updated = {}, []
    def single(bet):
        ref = bet.get('ref') or {}
        if not bet.get('starts_at'):
            return unavailable('Start time and exact selection are required to match a closing line.', at)
        if ref.get('lay'):
            return unavailable('Lay CLV requires a matched liability and closing commission basis.', at)
        if ref.get('market_key') == 'prop':
            if not ref.get('player') or not ref.get('prop_market'):
                return unavailable('Exact player and prop market were not recorded.', at)
            key = ('prop', ref.get('game_id'), ref['prop_market'], ref['player'], bet['starts_at'])
            if key not in cache:
                cache[key] = fetch_props_close(ref, bet['starts_at'])
            start, rows = cache[key]
            return clv.measure({**ref, 'market_key': 'prop_pair'}, bet['odds'], rows, PROP_SHARP_BOOKS, at=at)
        if ref.get('market_key') not in MARKET_CODES or not _valid_uuid(ref.get('game_id')):
            return unavailable('No exact retained market identifier was recorded for this bet.', at)
        key = (ref['game_id'], ref['market_key'])
        if key not in cache:
            cache[key] = fetch(*key)
        start, rows = cache[key]
        if start is None:
            return unavailable('The event has no retained closing record.', at)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if start + SETTLE_DELAY > now:
            return None
        if abs((start-datetime.fromisoformat(bet['starts_at'].replace('Z', '+00:00'))).total_seconds()) > 60:
            return unavailable('Event start changed; the original closing cutoff cannot be verified.', at)
        if ref['market_key'] == 'team_totals':
            from hashlib import sha256
            contract = ref.get('contract_id', '')
            rows = [r for r in rows if r.get('subject') and contract.endswith(':'+sha256(r['subject'].encode()).hexdigest()[:16])]
            if not rows:
                return unavailable('No exact team-total closing contract was retained.', at)
        return clv.measure(ref, bet['odds'], rows, sharps, at=at)
    for bet in store.state()['bets']:
        if not eligible(bet, now):
            continue
        if bet.get('legs'):
            legs = [{'key': l['key'], 'selection': l['selection'], **(single(l) or {'status': 'pending', 'pct': None, 'at': at})} for l in bet['legs']]
            if any(l['status'] == 'pending' for l in legs):
                continue
            # Do not manufacture a joint probability, even for different-game combinations.
            result = unavailable('Parlay CLV needs an actual matching combined closing quote; individual leg CLV is shown below.', at)
            result['legs'] = legs
        else:
            result = single(bet)
        if result is not None:
            store.set_clv(bet['id'], result)
            updated.append(store.bet(bet['id']))
    return updated
