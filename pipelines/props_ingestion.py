"""Player-prop capture: free events list, then one paid per-event odds call per event.

Cost is about one credit per market returned per event (all ten books fit in one region).
Nothing runs on a timer and nothing retries. Normalized quotes are merged into
retained/props/latest.json.
"""
from datetime import datetime, timezone
import json
from pathlib import Path

import requests

from config import ODDS_API_KEY
from corner.prop_markets import build_bets, market_meta, normalize_event
from pipelines.odds_ingestion import BASE, PARAMS, fetch

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / 'retained' / 'props' / 'latest.json'
BOOKS = PARAMS['bookmakers']
CREDIT_FLOOR = 20


def _when(text):
    return datetime.fromisoformat(text.replace('Z', '+00:00'))


def load():
    try:
        return json.loads(STORE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'events': {}}


def _save(data):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, separators=(',', ':')), encoding='utf-8')
    tmp.replace(STORE)


def prune(data, now=None):
    now = now or datetime.now(timezone.utc)
    data['events'] = {k: v for k, v in data.get('events', {}).items() if _when(v['commence_time']) > now}
    return data


def bets():
    return build_bets(prune(load())['events'])


def plan(sport, max_events, session, now=None):
    """Upcoming events from the free events endpoint, soonest first, capped."""
    status, body, headers = fetch(session, f'{BASE}/{sport}/events', {'dateFormat': 'iso'})
    if status != 200:
        raise ValueError(f'Events HTTP {status}; props not requested')
    now = now or datetime.now(timezone.utc)
    events = sorted((e for e in json.loads(body) if _when(e['commence_time']) > now),
                    key=lambda e: e['commence_time'])
    return events[:max_events], headers


def capture(sport, markets, max_events):
    """Fetch the chosen markets for the soonest events and merge them into the store."""
    if not ODDS_API_KEY:
        raise ValueError('ODDS_API_KEY is not configured')
    if not markets or any(not market_meta(sport, m) for m in markets):
        raise ValueError('Choose valid prop markets for this league.')
    used, stopped, done = 0, None, 0
    with requests.Session() as session:
        session.trust_env = False
        events, quota = plan(sport, max_events, session)
        data = prune(load())
        for event in events:
            if int((quota or {}).get('x-requests-remaining', '999')) < max(CREDIT_FLOOR, len(markets)):
                stopped = 'credit_floor'
                break
            status, body, headers = fetch(session, f"{BASE}/{sport}/events/{event['id']}/odds", {
                'bookmakers': BOOKS, 'markets': ','.join(markets), 'oddsFormat': 'decimal', 'dateFormat': 'iso'})
            quota = headers or quota
            if status != 200:
                stopped = f'provider_http_{status}'
                break
            used += int(headers.get('x-requests-last', '0') or 0)
            payload = json.loads(body)
            at = datetime.now(timezone.utc).isoformat()
            slot = data['events'].setdefault(event['id'], {
                'sport_key': sport, 'home_team': payload.get('home_team', event.get('home_team')),
                'away_team': payload.get('away_team', event.get('away_team')),
                'commence_time': payload.get('commence_time', event['commence_time']), 'markets': {}})
            for key in markets:
                quotes = normalize_event(payload, key, market_meta(sport, key))
                if quotes:
                    slot['markets'][key] = {'captured_at': at, 'quotes': quotes}
                else:
                    slot['markets'].pop(key, None)
            done += 1
            _save(data)
    return {'events': done, 'credits_used': used, 'quota': quota, 'stopped': stopped}
