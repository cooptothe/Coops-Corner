"""Measures closing-line value for tracked bets from the odds ledger (read-only), and stores the result."""
from datetime import datetime, timedelta, timezone
import os
import uuid

from corner import clv
from corner.prop_markets import SHARP_BOOKS
from corner.tracker_store import now_iso

MARKET_CODES = {'h2h': 'moneyline', 'spreads': 'spread', 'totals': 'total'}
WINDOW = timedelta(seconds=int(os.environ.get('CORNER_CLV_WINDOW_SECONDS', '10800')))
SETTLE_DELAY = timedelta(minutes=5)

# The latest eligible, active observation per sharp book and outcome in the window before the start. Eligibility
# and the "newest wins" rule are the same as corner.trusted_current_quotes, applied as of the start time.
CLOSE_SQL = """
SELECT e.scheduled_start, b.code AS book, os.code AS side, o.point, q.decimal_odds, q.observed_at
FROM corner.events e
JOIN corner.markets m ON m.event_id = e.id AND m.subject_participant_id IS NULL
JOIN corner.market_types mt ON mt.id = m.market_type_id AND mt.code = %(market)s
JOIN corner.scopes sc ON sc.id = m.scope_id AND sc.code = 'full_game'
JOIN corner.outcomes o ON o.market_id = m.id
JOIN corner.outcome_sides os ON os.id = o.outcome_side_id
CROSS JOIN corner.sportsbooks b
JOIN LATERAL (
    SELECT ob.decimal_odds, ob.observed_at, ob.quote_state_id
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
WHERE e.id = %(event)s::uuid AND b.code = ANY(%(books)s) AND q.decimal_odds > 1
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
    rows = [{'book': r[1], 'side': r[2], 'point': r[3], 'decimal_odds': r[4]} for r in found]
    return (start[0] if start else None), rows


def _valid_uuid(value):
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


def eligible(bet, now):
    """Bets whose game has started and that came from a tool with a main-market line."""
    ref = bet.get('ref') or {}
    if bet.get('clv') is not None or ref.get('lay') or ref.get('market_key') not in MARKET_CODES:
        return False
    if not _valid_uuid(ref.get('game_id')) or not bet.get('starts_at'):
        return False
    return datetime.fromisoformat(bet['starts_at']) + SETTLE_DELAY <= now


def measure_pending(store, fetch=fetch_close, now=None, sharps=SHARP_BOOKS):
    """Measures and stores CLV for every eligible bet; returns the updated bets. Raises on a database failure."""
    now = now or datetime.now(timezone.utc)
    todo = [b for b in store.state()['bets'] if eligible(b, now)]
    cache, updated = {}, []
    for bet in todo:
        ref = bet['ref']
        key = (ref['game_id'], ref['market_key'])
        if key not in cache:
            cache[key] = fetch(*key)
        start, rows = cache[key]
        if start is None:
            continue  # the game is not in the ledger; try again later rather than recording a false "no close"
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if start + SETTLE_DELAY > now:
            continue  # the close is not final until the game has started
        store.set_clv(bet['id'], clv.measure(ref, bet['odds'], rows, sharps, at=now_iso()))
        updated.append(store.bet(bet['id']))
    return updated
