"""Local tracker service: the bet ledger over HTTP, plus live game status for pending bets.

Mounted by the refresh service on loopback. Reads need no credits. Writes must come from the local UI
(Origin check) and every request must address the loopback host, which blocks DNS-rebinding pages.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
import threading
import time

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from corner import tracker_live as live
from corner.tracker_store import TrackerError, TrackerStore
from pipelines import media as media_service
from pipelines import tracker_clv

log = logging.getLogger('corner.tracker')
ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get('CORNER_TRACKER_DB') or ROOT / 'retained' / 'tracker.sqlite3')
LOCAL_HOSTS = {'127.0.0.1', 'localhost', '[::1]'}
LIVE_TTL = 20
FINAL_TTL = 600
MAX_LIVE_BETS = 120
LOOKBACK = timedelta(days=10)
LEAD = timedelta(minutes=20)
_cache = {}
_cache_lock = threading.Lock()


def host_ok(request):
    host = (request.headers.get('host') or '').lower()
    name = host.rsplit(':', 1)[0] if not host.startswith('[') else host.split(']')[0] + ']'
    return name in LOCAL_HOSTS


def fetch_cached(url, ttl):
    """Fetch JSON with a short shared cache so several open tabs cost one upstream call."""
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(url)
        if hit and now - hit[0] < hit[1]:
            return hit[2]
    data = media_service.http_json(url)
    with _cache_lock:
        if len(_cache) > 300:
            for key in sorted(_cache, key=lambda k: _cache[k][0])[:100]:
                _cache.pop(key, None)
        _cache[url] = (now, ttl, data)
    return data


def scoreboard_dates(starts_at):
    start = datetime.fromisoformat(starts_at.replace('Z', '+00:00'))
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    # ESPN files late US games under the local calendar day, which can be the day before in UTC.
    return sorted({(start - timedelta(hours=8)).strftime('%Y%m%d'), start.strftime('%Y%m%d')})


def teams_of(bet):
    ref = bet.get('ref') or {}
    if ref.get('away') and ref.get('home'):
        return ref['away'], ref['home']
    return live.split_matchup(bet['matchup']) or (None, None)


def live_view(bets, fetch=fetch_cached):
    """{bet_id: live view} for pending bets whose game has started (or is about to), grouped to few upstream calls."""
    now = datetime.now(timezone.utc)
    wanted = []
    for bet in bets:
        if bet['status'] != 'pending' or not bet['starts_at'] or not live.espn_path(bet['sport_key']):
            continue
        start = datetime.fromisoformat(bet['starts_at'])
        if start - LEAD <= now <= start + LOOKBACK:
            wanted.append(bet)
    wanted = wanted[:MAX_LIVE_BETS]
    boards = sorted({(live.espn_path(b['sport_key']), d) for b in wanted for d in scoreboard_dates(b['starts_at'])})

    def board(item):
        path, date = item
        try:
            return item, fetch(f'{live.ESPN}/{path}/scoreboard?dates={date}&limit=300', LIVE_TTL).get('events', [])
        except media_service.UpstreamError:
            return item, None

    with ThreadPoolExecutor(max_workers=4) as pool:
        loaded = dict(pool.map(board, boards))
    matched = {}
    for bet in wanted:
        away, home = teams_of(bet)
        events = []
        for date in scoreboard_dates(bet['starts_at']):
            events += loaded.get((live.espn_path(bet['sport_key']), date)) or []
        if away and home:
            event = live.find_event(events, away, home, bet['starts_at'])
            if event:
                matched[bet['id']] = event
    summaries = {}
    needs = {}
    for bet in wanted:
        event = matched.get(bet['id'])
        if event and (bet['ref'] or {}).get('prop_market') and live.status_view(event)['state'] != 'pre':
            needs[event['id']] = (live.espn_path(bet['sport_key']), live.status_view(event)['state'])

    def summary(item):
        event_id, (path, state) = item
        try:
            return event_id, fetch(f'{live.ESPN}/{path}/summary?event={event_id}', FINAL_TTL if state == 'post' else LIVE_TTL)
        except media_service.UpstreamError:
            return event_id, None

    with ThreadPoolExecutor(max_workers=4) as pool:
        summaries = dict(pool.map(summary, needs.items()))
    out = {}
    for bet in wanted:
        event = matched.get(bet['id'])
        if not event:
            out[bet['id']] = {'state': 'unknown', 'detail': '', 'score': {}, 'progress': None, 'suggest': None}
            continue
        out[bet['id']] = live.live_for_bet(bet, event, summaries.get(event['id']))
    return out


def create_router(store=None, allowed_origins=None, fetch=fetch_cached, close_fetch=None):
    router = APIRouter(prefix='/api/refresh/v1/tracker')
    holder = {'store': store}
    lock = threading.Lock()

    def db():
        with lock:
            if holder['store'] is None:
                holder['store'] = TrackerStore(DB_PATH)
            return holder['store']

    def origins():
        if allowed_origins is not None:
            return allowed_origins
        from pipelines.refresh_service import ALLOWED_ORIGINS
        return ALLOWED_ORIGINS

    def reply(code, body):
        return JSONResponse(body, status_code=code, headers={'Cache-Control': 'no-store'})

    def guard(request, write):
        if not host_ok(request):
            return reply(403, {'error': 'Host not allowed.'})
        if write and request.headers.get('origin') not in origins():
            return reply(403, {'error': 'Origin not allowed.'})
        return None

    async def body_of(request):
        try:
            return await request.json()
        except ValueError:
            raise TrackerError('The request body must be JSON') from None

    async def run(request, write, work):
        blocked = guard(request, write)
        if blocked:
            return blocked
        try:
            return reply(200, await run_in_threadpool(work))
        except TrackerError as error:
            return reply(error.status, {'error': str(error), 'code': error.code})

    @router.get('/state')
    async def state(request: Request):
        return await run(request, False, lambda: db().state())

    @router.get('/export')
    async def export(request: Request):
        return await run(request, False, lambda: db().export())

    @router.get('/live')
    async def live_state(request: Request):
        return await run(request, False, lambda: {'live': live_view(db().state()['bets'], fetch)})

    @router.post('/clv')
    async def measure_clv(request: Request):
        blocked = guard(request, True)
        if blocked:
            return blocked
        try:
            bets = await run_in_threadpool(lambda: tracker_clv.measure_pending(db(), close_fetch or tracker_clv.fetch_close))
        except Exception:
            log.exception('closing-line measurement failed')
            return reply(502, {'error': 'The odds database is unavailable, so closing lines could not be measured.'})
        return reply(200, {'bets': bets})

    @router.post('/bets')
    async def add_bets(request: Request):
        blocked = guard(request, True)
        if blocked:
            return blocked
        try:
            items = await body_of(request)
            if isinstance(items, dict):
                items = items.get('bets')
            return reply(200, {'bets': await run_in_threadpool(db().add_bets, items)})
        except TrackerError as error:
            return reply(error.status, {'error': str(error), 'code': error.code})

    @router.patch('/bets/{bet_id}')
    async def update(bet_id: str, request: Request):
        blocked = guard(request, True)
        if blocked:
            return blocked
        try:
            data = await body_of(request)
            return reply(200, {'bet': await run_in_threadpool(db().update_bet, bet_id, data)})
        except TrackerError as error:
            return reply(error.status, {'error': str(error), 'code': error.code})

    @router.post('/bets/{bet_id}/settle')
    async def settle(bet_id: str, request: Request):
        blocked = guard(request, True)
        if blocked:
            return blocked
        try:
            data = await body_of(request)
            if not isinstance(data, dict):
                raise TrackerError('The request body must be an object')
            bet = await run_in_threadpool(lambda: db().settle_bet(
                bet_id, data.get('result'), returned=data.get('returned'), settled_at=data.get('settled_at')))
            return reply(200, {'bet': bet})
        except TrackerError as error:
            return reply(error.status, {'error': str(error), 'code': error.code})

    @router.post('/bets/{bet_id}/reopen')
    async def reopen(bet_id: str, request: Request):
        return await run(request, True, lambda: {'bet': db().reopen_bet(bet_id)})

    @router.delete('/bets/{bet_id}')
    async def delete_bet(bet_id: str, request: Request):
        return await run(request, True, lambda: (db().delete_bet(bet_id), {'ok': True})[1])

    @router.post('/cash')
    async def add_cash(request: Request):
        blocked = guard(request, True)
        if blocked:
            return blocked
        try:
            data = await body_of(request)
            return reply(200, {'cash': await run_in_threadpool(db().add_cash, data)})
        except TrackerError as error:
            return reply(error.status, {'error': str(error), 'code': error.code})

    @router.delete('/cash/{cash_id}')
    async def delete_cash(cash_id: str, request: Request):
        return await run(request, True, lambda: (db().delete_cash(cash_id), {'ok': True})[1])

    return router
