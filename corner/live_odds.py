"""Owner-only live main-line availability. No network or key access here."""
from __future__ import annotations
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any

from corner.collection_policy import CENTRAL, STANDARD, EXCHANGE, Job, aware, open_now, parse, supported

CONFIG = Path('/srv/corner/config/live-odds.json')
REQUEST = Path('/srv/corner/config/live-queue/request.json')
MONTHLY_CAP = 3_000_000  # Sub-limit WITHIN the existing main pool; never additional credits.
DAILY_CAP = 150_000
FRESH_SECONDS = 90
MARKETS = ('h2h', 'spreads', 'totals')

def premium(user: dict[str, Any] | None) -> bool:
    """Read from the authenticated DB-backed identity, never a request field."""
    return bool(user and (str(user.get('username', '')).casefold() == 'wonya'
                         or user.get('cohort') == 'friend'))

def config() -> dict[str, Any]:
    try:
        value = json.loads(CONFIG.read_text(encoding='utf-8'))
        if value.get('enabled') is not True or value.get('premium_username') != 'wonya': return {}
        token = value.get('cron_token')
        if not isinstance(token, str) or len(token) < 40: return {}
        return value
    except (OSError, ValueError, AttributeError): return {}

def request_refresh(at: datetime) -> None:
    from pipelines.collection_publication import MainPublisher
    MainPublisher._atomic(REQUEST, json.dumps({'requested_at': aware(at).isoformat()}).encode())

def enabled(now: datetime) -> bool:
    if not config() or not open_now(now): return False
    try:
        at = parse(json.loads(REQUEST.read_text(encoding='utf-8'))['requested_at'])
        return 0 <= (aware(now) - at).total_seconds() <= 125
    except (OSError, ValueError, KeyError, TypeError): return False

def jobs(now: datetime, inventory: dict[str, Any]) -> list[Job]:
    if not enabled(now): return []
    # /events includes in-play events. Time alone is a candidate, NOT proof of play.
    sports = {e['sport_key'] for e in [*inventory.get('events', []), *inventory.get('live_events', [])]
              if supported(e['sport_key']) and now-timedelta(hours=12) <= parse(e['commence_time']) <= now}
    return [Job('live', sport, group, books, MARKETS)
            for sport in sorted(sports)
            for group, books in (('standard', STANDARD), ('exchange', EXCHANGE))]

def store(db: sqlite3.Connection, job: Job, payload: Any, now: datetime) -> None:
    """Called inside the existing quota settlement transaction, no pregame writes."""
    if not isinstance(payload, list): raise ValueError('Expected event list')
    seen: set[str] = set()
    for event in payload:
        if not isinstance(event, dict) or event.get('sport_key') != job.sport or not isinstance(event.get('id'), str):
            raise ValueError('Mismatched event')
        if event['id'] in seen: raise ValueError('Duplicate live event')
        seen.add(event['id'])
        parse(event['commence_time'])
        if not event['id'] or any(not isinstance(event.get(k),str) or not event[k].strip() for k in ('home_team','away_team')) or event['home_team']==event['away_team']: raise ValueError('Invalid event teams')
        if not isinstance(event.get('bookmakers', []), list): raise ValueError('Invalid bookmakers')
        book_ids: set[str] = set()
        for book in event.get('bookmakers', []):
            if book.get('key') not in job.books or book['key'] in book_ids: raise ValueError('Unexpected bookmaker')
            book_ids.add(book['key'])
            if not isinstance(book.get('markets', []), list): raise ValueError('Invalid markets')
    db.execute('DELETE FROM live_captures WHERE captured<?',(now.timestamp()-86400,))
    # Exact request scope replaces the prior group, including empty responses.
    db.execute('INSERT INTO live_captures VALUES(?,?,?,?) ON CONFLICT(sport,book_group) DO UPDATE SET captured=excluded.captured,payload=excluded.payload',
               (job.sport, job.group, now.timestamp(), json.dumps(payload, separators=(',', ':'))))

def active_market(market: dict[str, Any], event: dict[str, Any], now: datetime) -> bool:
    from decimal import Decimal
    try:
        key = market['key']
        if key not in MARKETS or market.get('suspended') is True or market.get('status', 'open') not in ('open', 'active'): return False
        # Market source time only; do not re-date from the fetch or deprecated book time.
        if not -5 <= (now-parse(market['last_update'])).total_seconds() <= FRESH_SECONDS: return False
        outcomes = market['outcomes']
        if not isinstance(outcomes, list) or not outcomes: return False
        sides = [o['name'] for o in outcomes]
        expected = {'Over','Under'} if key == 'totals' else {event['home_team'],event['away_team']}
        if key == 'h2h' and event['sport_key'].startswith('soccer_'): expected.add('Draw')
        if set(sides) != expected or len(sides) != len(expected): return False
        for outcome in outcomes:
            price = outcome.get('price')
            if isinstance(price, bool) or price is None: return False
            price = Decimal(str(price))
            if not price.is_finite() or price.as_tuple().exponent < -12 or not 1 < price <= 1_000_000: return False
        if key != 'h2h':
            lines = [Decimal(str(o['point'])) for o in outcomes]
            if any(not p.is_finite() or abs(p)>1_000_000 for p in lines): return False
            if key == 'spreads' and sum(lines) != 0: return False
            if key == 'totals' and (len(set(lines)) != 1 or lines[0] < 0): return False
        return True
    except (ValueError, KeyError, TypeError, ArithmeticError): return False

def feed(path: Path, now: datetime | None = None, devig_method: str = 'current') -> dict[str, Any]:
    now = aware(now or datetime.now(timezone.utc))
    base: dict[str, Any] = {'format': 'corner.live_odds/1', 'as_of': now.isoformat(),
        'devig_method':devig_method, 'premium': True, 'enabled': bool(config()), 'state': 'waiting', 'events': [],
        'source': 'the-odds-api', 'refresh_seconds': 60, 'freshness_seconds': FRESH_SECONDS,
        'monthly_subcap': MONTHLY_CAP, 'daily_subcap': DAILY_CAP,
        'budget_basis': 'within_existing_main_pool', 'game_stoppage_confirmed': False}
    if not path.is_file(): return base
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=3)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='live_captures'").fetchone(): return base
        rows = db.execute('SELECT sport,book_group,captured,payload FROM live_captures').fetchall()
        # Reuse the worker's zero-credit discovered event inventory for vanished events.
        inventory_row = db.execute('SELECT payload,captured FROM runner_inventory WHERE id=1').fetchone() if db.execute("SELECT 1 FROM sqlite_master WHERE name='runner_inventory'").fetchone() else None
        inventory = json.loads(inventory_row[0]) if inventory_row and inventory_row[0] and now.timestamp()-inventory_row[1] < 600 else {}
        paused = db.execute('SELECT paused FROM controls WHERE id=1').fetchone()[0]
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='live_pacing_state'").fetchone():
            pace=db.execute('SELECT payload FROM live_pacing_state WHERE id=1').fetchone()
            if pace:
                pacing=json.loads(pace[0])
                if 0<=now.timestamp()-pacing.get('checked_at',0)<=60:
                    base['collection_intervals_seconds']=pacing['interval_seconds']
                    base['live_pacing']=pacing
                    base['refresh_seconds']=min(pacing['interval_seconds'].values())
        cycle = db.execute('SELECT id FROM cycles WHERE starts<=? AND ends>?', (now.timestamp(),now.timestamp())).fetchone()
        if cycle:
            base['live_daily_credits_accounted'] = db.execute('SELECT coalesce(sum(coalesce(a.actual,a.reserved)),0) FROM attempts a JOIN live_attempts l ON l.token=a.token WHERE a.cycle_id=? AND l.day=?',(cycle[0],now.astimezone(CENTRAL).date().isoformat())).fetchone()[0]
            base['live_credits_accounted'] = db.execute('SELECT coalesce(sum(coalesce(a.actual,a.reserved)),0) FROM attempts a JOIN live_attempts l ON l.token=a.token WHERE a.cycle_id=?',(cycle[0],)).fetchone()[0]
    groups = {(sport, group): (captured, json.loads(raw)) for sport, group, captured, raw in rows}
    events = {(e['sport_key'],e['id']): e for e in inventory.get('live_events', [])}
    for _, _, _, raw in rows:
        for event in json.loads(raw): events[(event['sport_key'],event['id'])] = event
    for identity, event in sorted(events.items()):
        if not now-timedelta(hours=12) <= parse(event['commence_time']) <= now: continue
        sport, event_id = identity
        books, all_fresh, selected = [], True, []
        for group, book_keys in (('standard', STANDARD), ('exchange', EXCHANGE)):
            capture_at, payload = groups.get((sport,group),(0,[]))
            fresh = not paused and 0 <= now.timestamp()-capture_at <= FRESH_SECONDS
            all_fresh &= fresh
            found = next((e for e in payload if e['id'] == event_id), {})
            by_key = {b['key']: b for b in found.get('bookmakers', [])}
            for book_key in book_keys:
                book = by_key.get(book_key, {})
                market_blocks = book.get('markets', [])
                counts = {key:sum(isinstance(m,dict) and m.get('key')==key for m in market_blocks) for key in MARKETS}
                active = [m for m in market_blocks if fresh and isinstance(m,dict) and isinstance(m.get('key'),str) and counts.get(m.get('key'))==1 and book.get('suspended') is not True and book.get('status','open') in ('open','active') and active_market(m,event,now)]
                books.append({'book':book_key, 'active_market_count':len(active),
                              'active_markets':[m['key'] for m in active],
                              'markets':[{'key':m['key'],'last_update':m['last_update'],'outcomes':[{'name':o['name'],'price':o['price'],**({'point':o['point']} if 'point' in o else {})} for o in m['outcomes']]} for m in active], 'capture_fresh':bool(fresh),
                              'status':'active' if active else 'no_active_lines' if fresh else 'unknown'})
                if active: selected.append({'key':book_key, 'link':book.get('link'), 'markets':active})
        count = sum(b['active_market_count'] for b in books)
        suspended: bool | None = False if count else True if all_fresh else None
        candidates = []
        if count:
            from corner.live_tools import opportunities
            candidates = opportunities({**event,'bookmakers':selected},devig_method)
        base['events'].append({'id':event_id,'sport_key':sport,'home_team':event.get('home_team',''),
            'away_team':event.get('away_team',''), 'commence_time':event['commence_time'],
            'is_live_inferred':True, 'game_stoppage_confirmed':False,
            'is_suspended':suspended, 'status':'active' if count else 'no_active_lines' if all_fresh else 'unknown',
            'reason':'fresh_complete_markets' if count else 'no_usable_prices_in_fresh_capture' if all_fresh else 'capture_stale_missing_or_collector_paused',
            'active_market_count':count, 'books':books,
            'tool_rows':[c['tool_row'] for c in candidates],
            'quotes':list({q['id']:q for c in candidates for q in c['quotes']}.values()),
            'opportunities':[{**{k:v for k,v in c.items() if k not in ('tool_row','quotes')},'row_id':c['tool_row']['id']} for c in candidates]})
    base['state'] = 'paused' if paused else 'after_hours' if not open_now(now) else 'ready' if base['events'] else 'no_live_events'
    if not paused and open_now(now) and (base.get('live_credits_accounted',0)+3>MONTHLY_CAP or base.get('live_daily_credits_accounted',0)+3>DAILY_CAP): base['state']='live_budget_limit'
    if base['state']=='ready' and base.get('live_pacing',{}).get('remaining_today_paced',3)<3:
        base['state']='live_budget_pacing'
    return base

_cache_lock = threading.Lock()
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def cached_feed(path: Path, devig_method: str = 'current') -> dict[str, Any]:
    """One analysis per two seconds per method; six bounded cache entries."""
    global _cache
    key = str(path.resolve())+'|'+devig_method
    with _cache_lock:
        now = time.monotonic()
        hit = _cache.get(key) if isinstance(_cache,dict) else None
        if hit and now-hit[0]<2:return hit[1]
        result=feed(path,devig_method=devig_method)
        if not isinstance(_cache,dict):_cache={}
        _cache[key]=(time.monotonic(),result)
        while len(_cache)>6:
            oldest=min(_cache,key=lambda k:_cache[k][0])
            del _cache[oldest]
        return result
