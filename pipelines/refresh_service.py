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

from pipelines import odds_ingestion as board

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

def create_app():
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def reply(code, body):
        return JSONResponse(body, status_code=code, headers={'Cache-Control': 'no-store'})

    @app.get('/api/refresh/v1/status')
    def status():
        return reply(200, status_view())

    @app.post('/api/refresh/v1/odds')
    async def refresh(request: Request):
        # Browsers always send Origin on cross-origin POST; reject anything but the local UI.
        if request.headers.get('origin') not in ALLOWED_ORIGINS:
            return reply(403, {'error': 'Origin not allowed.'})
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
