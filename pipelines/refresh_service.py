"""Loopback-only, user-triggered pre-game odds refresh (python -m pipelines.refresh_service).

One POST captures and ingests h2h/spreads/totals for each configured league (3 credits per
in-season league, ceiling 39). Nothing runs on a timer. Guards: single flight, cooldown, daily cap, and the
capture's own credit floor. Guard state persists in retained/refresh_state.json.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import time

from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from corner import prop_markets
from pipelines import accounts
from pipelines import media as media_service
from pipelines import settings_service
from pipelines import tracker_service
from pipelines import odds_ingestion as board
from pipelines import props_ingestion as props

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / 'retained' / 'refresh_state.json'
ALLOWED_ORIGINS = {f'http://{h}:{p}' for h in ('127.0.0.1', 'localhost') for p in (3000,)}
COOLDOWN = int(os.getenv('CORNER_REFRESH_COOLDOWN_SECONDS', '30'))
DAILY_CAP = int(os.getenv('CORNER_REFRESH_DAILY_CAP', '50'))
SPORTS = ('americanfootball_nfl', 'americanfootball_ncaaf', 'basketball_nba', 'basketball_ncaab',
          'baseball_mlb', 'icehockey_nhl', 'soccer_usa_mls', 'soccer_epl', 'soccer_spain_la_liga',
          'soccer_germany_bundesliga', 'soccer_italy_serie_a', 'soccer_france_ligue_one',
          'soccer_uefa_champs_league', 'basketball_wnba', 'basketball_wncaab', 'tennis_atp', 'tennis_wta',
          'mma_mixed_martial_arts')
GROUPS = {'tennis_atp': 'tennis_atp_', 'tennis_wta': 'tennis_wta_'}  # picker entry -> active tournament keys
LABELS = {'americanfootball_nfl': 'NFL', 'americanfootball_ncaaf': 'NCAAF', 'basketball_nba': 'NBA',
          'basketball_ncaab': 'NCAAB (Men)', 'basketball_wncaab': 'NCAAB (Women)', 'basketball_wnba': 'WNBA',
          'tennis_atp': 'Tennis (Men)', 'tennis_wta': 'Tennis (Women)', 'mma_mixed_martial_arts': 'MMA', 'baseball_mlb': 'MLB', 'icehockey_nhl': 'NHL', 'soccer_usa_mls': 'MLS',
          'soccer_epl': 'Premier League', 'soccer_spain_la_liga': 'La Liga',
          'soccer_germany_bundesliga': 'Bundesliga', 'soccer_italy_serie_a': 'Serie A',
          'soccer_france_ligue_one': 'Ligue 1', 'soccer_uefa_champs_league': 'Champions League'}
CREDITS_PER_SPORT = 3
CREDITS_PER_REFRESH = CREDITS_PER_SPORT * len(SPORTS)  # ceiling; out-of-season leagues cost nothing
_lock = threading.Lock()


def _load():
    try:
        return json.loads(STATE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _save(state):
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2) + '\n', encoding='utf-8')


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def status_view(state=None, now=None):
    state = _load() if state is None else state
    now = time.time() if now is None else now
    attempts = state.get('attempts_today', 0) if state.get('day') == _today() else 0
    wait = max(0, int(state.get('last_attempt_epoch', 0) + COOLDOWN - now))
    return {'last_attempt_at': state.get('last_attempt_at'), 'last_success_at': state.get('last_success_at'),
            'last_error': state.get('last_error'), 'last_results': state.get('last_results'),
            'sports': [{'key': k, 'label': LABELS[k]} for k in SPORTS], 'quota': state.get('quota'),
            'cooldown_seconds': COOLDOWN, 'retry_after_seconds': wait,
            'attempts_today': attempts, 'daily_cap': DAILY_CAP, 'credits_per_refresh': CREDITS_PER_REFRESH,
            'can_refresh': wait == 0 and attempts < DAILY_CAP}


def _quota(destination):
    try:
        return json.loads((destination / 'manifest.json').read_text(encoding='utf-8')).get('response_headers')
    except (OSError, ValueError):
        return None


def expand_groups(sport):
    """Tennis tournaments rotate: expand a picker entry to the tournaments the free catalog lists as active."""
    return board.active_sport_keys(GROUPS[sport]) if sport in GROUPS else [sport]


def run_refresh(capture=board.capture, ingest=board.ingest, now=None, sports=SPORTS, expand=None):
    """Returns (http_status, body). Attempts are counted before the paid calls, never refunded.

    Each league is captured and ingested independently so one failure keeps the others.
    A failed capture stops the run so a systemic provider fault cannot burn more credits.
    """
    sports = tuple(dict.fromkeys(sports))
    if not sports or any(s not in SPORTS for s in sports):
        return 400, {'error': 'Choose one or more supported leagues.'}
    if not _lock.acquire(blocking=False):
        return 409, {'error': 'A refresh is already running.'}
    try:
        state = _load()
        now = time.time() if now is None else now
        view = status_view(state, now)
        if view['retry_after_seconds']:
            return 429, {'error': 'Refresh is cooling down.', **view}
        if view['attempts_today'] >= DAILY_CAP:
            return 429, {'error': 'Daily refresh limit reached.', **view}
        stamp = datetime.now(timezone.utc)
        if state.get('day') != _today():
            state['attempts_today'] = 0
        state.update(day=_today(), attempts_today=state.get('attempts_today', 0) + 1,
                     last_attempt_epoch=now, last_attempt_at=stamp.isoformat(), last_error=None)
        _save(state)
        base = ROOT / 'retained' / f"board-refresh-{stamp.strftime('%Y%m%dT%H%M%S%fZ')}"
        results = {}
        params = {'commenceTimeFrom': stamp.strftime('%Y-%m-%dT%H:%M:%SZ')}  # pre-game only
        try:
            plan = [k for s in sports for k in (expand(s) if expand else [s])]
            for sport in plan:
                destination = base / sport
                try:
                    capture(destination, params, sport=sport)
                except board.InactiveSport:
                    results[sport] = 'not_in_season'
                    continue
                except Exception as error:
                    state['quota'] = _quota(destination) or state.get('quota')
                    results[sport] = f'capture_failed ({type(error).__name__})'
                    break
                quota = _quota(destination)
                if quota:
                    state['quota'] = quota
                try:
                    if (destination / 'response.body').read_bytes().strip() in (b'', b'[]'):
                        results[sport] = 'no_upcoming_games'
                        continue
                    ingest(destination)
                    results[sport] = 'ok'
                    state['last_success_at'] = datetime.now(timezone.utc).isoformat()
                except Exception as error:
                    results[sport] = f'ingest_failed ({type(error).__name__})'
                if int((quota or {}).get('x-requests-remaining', '999')) < CREDITS_PER_SPORT:
                    results['stopped'] = 'credit_floor'
                    break
        finally:
            state['last_results'] = results
            failed = [s for s, r in results.items() if 'failed' in r]
            state['last_error'] = f"Problems: {', '.join(failed)}." if failed else None
            _save(state)
        code = 200 if any(r == 'ok' for r in results.values()) or not failed else 502
        return code, {'refreshed': code == 200, **status_view(state, now)}
    finally:
        _lock.release()

PROP_MAX_EVENTS = 20
PROP_DEFAULT_EVENTS = 8
PROP_SPORTS = tuple(s for s in SPORTS if prop_markets.family(s))


def props_status():
    return {'sports': [{'key': k, 'label': LABELS[k]} for k in PROP_SPORTS],
            'markets': prop_markets.catalog_view(PROP_SPORTS),
            'default_events': PROP_DEFAULT_EVENTS, 'max_events': PROP_MAX_EVENTS,
            'max_age_seconds': props.MAX_AGE, 'last_success_at': props.last_captured()}


def props_found(sport):
    """How many bets the stored fetches currently give this league, and how many are +EV."""
    mine = [b for b in props.bets() if b['sport_key'] == sport]
    return {'bets': len(mine), 'positive': sum(1 for b in mine if float(b['ev']) >= 0)}


def props_message(label, markets, result, found=None):
    """What happened, in words, so a fetch that bought nothing never looks like a click that did nothing."""
    done, planned, used = result['events'], result.get('planned', 0), result['credits_used']
    stopped, remaining = result.get('stopped'), result.get('remaining')
    games = lambda n: f"{n} game{'s' if n != 1 else ''}"
    credits = lambda n: f"{n} credit{'s' if n != 1 else ''}"
    progress = f"Fetched {games(done)} of {planned}, {credits(used)} used." if done else 'Nothing was fetched.'
    if stopped == 'out_of_credits':
        left = (f'only {credits(remaining)} left' if remaining is not None else 'too few credits are left')
        return f'Stopped: {left} on your Odds API key, and each game needs {credits(len(markets))}. {progress}'
    if stopped:
        code = stopped.rsplit('_', 1)[-1]
        reason = {'401': 'The Odds API rejected the key or says it is out of credits (HTTP 401).',
                  '422': 'The Odds API rejected one of the selected markets (HTTP 422). Try fewer or different markets.',
                  '429': 'The Odds API is rate limiting requests (HTTP 429). Wait a moment and try again.'
                  }.get(code, f'The Odds API returned HTTP {code}.')
        return f'{reason} {progress}'
    if not planned:
        return f'No upcoming {label} games to fetch.'
    base = f'Fetched props for {games(done)}, {credits(used)} used.'
    if found is None:
        return base
    if not found['bets']:
        return (f'{base} No {label} bets can be shown: none of these lines had two sharp books pricing both '
                'sides, which a bet needs to be priced.')
    return f"{base} {found['bets']} {label} bets priced, {found['positive']} with positive EV."

def run_props_refresh(sport, markets, max_events, capture=props.capture):
    """Returns (http_status, body). Credits are spent only as the user asks: no budget, no cooldown."""
    if sport not in PROP_SPORTS or not isinstance(markets, list) or not markets \
            or not all(isinstance(m, str) and prop_markets.market_meta(sport, m) for m in markets) \
            or len(set(markets)) != len(markets) \
            or not isinstance(max_events, int) or isinstance(max_events, bool) or not 1 <= max_events <= PROP_MAX_EVENTS:
        return 400, {'error': 'Choose a league, valid prop markets, and 1-20 events.'}
    if not _lock.acquire(blocking=False):
        return 409, {'error': 'A refresh is already running.'}
    try:
        try:
            result = capture(sport, markets, max_events)
        except Exception as error:
            return 502, {'error': f'Prop refresh failed: {error}'}
        found = props_found(sport)
        return 200, {'refreshed': result['events'] > 0, 'stopped': result.get('stopped'),
                     'bets_found': found['bets'],
                     'message': props_message(LABELS[sport], markets, result, found), **props_status()}
    finally:
        _lock.release()

def create_app():
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    ctx = accounts.AuthContext()
    app.include_router(media_service.create_router(guard=lambda request: ctx.require(request, write=False)[1]))
    app.include_router(accounts.create_router(ctx))
    app.include_router(tracker_service.create_router(ctx))
    app.include_router(settings_service.create_router(ctx))

    def reply(code, body):
        return JSONResponse(body, status_code=code, headers={'Cache-Control': 'no-store'})

    # Every route here needs a signed-in account; reads cost no credits but are not public.
    @app.get('/api/refresh/v1/props/status')
    async def props_state(request: Request):
        _, denied = ctx.require(request, write=False)
        return denied or reply(200, props_status())

    @app.get('/api/refresh/v1/props')
    async def props_bets(request: Request):
        _, denied = ctx.require(request, write=False)
        if denied:
            return denied
        return reply(200, {'bets': await run_in_threadpool(props.bets), **props_status()})

    @app.post('/api/refresh/v1/props')
    async def props_refresh(request: Request):
        # Spends provider credits, so it needs the local UI origin and a signed-in account.
        _, denied = ctx.require(request, write=True)
        if denied:
            return denied
        try:
            body = await request.json()
            sport, markets, count = body['sport'], body['markets'], body.get('max_events', PROP_DEFAULT_EVENTS)
        except (ValueError, KeyError, TypeError):
            return reply(400, {'error': 'Choose a league, valid prop markets, and 1-20 events.'})
        return reply(*await run_in_threadpool(run_props_refresh, sport, markets, count))

    @app.get('/api/refresh/v1/status')
    async def status(request: Request):
        _, denied = ctx.require(request, write=False)
        return denied or reply(200, status_view())

    @app.post('/api/refresh/v1/odds')
    async def refresh(request: Request):
        # Browsers always send Origin on cross-origin POST; reject anything but the local UI, and anyone not signed in.
        _, denied = ctx.require(request, write=True)
        if denied:
            return denied
        try:
            body = await request.json()
            chosen = body['sports']
            if not isinstance(chosen, list) or not all(isinstance(s, str) for s in chosen):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            return reply(400, {'error': 'Choose one or more supported leagues.'})
        return reply(*await run_in_threadpool(run_refresh, sports=tuple(chosen), expand=expand_groups))

    return app


app = create_app()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    import uvicorn
    uvicorn.run('pipelines.refresh_service:app', host='127.0.0.1', port=args.port, access_log=False,
                timeout_graceful_shutdown=5)


if __name__ == '__main__':
    main()
