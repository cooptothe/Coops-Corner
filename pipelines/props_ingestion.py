"""Player-prop capture: free events list, then one paid per-event odds call per event.

Cost is about two credits per market returned per event (sixteen books count as two regions).
Nothing runs on a timer and nothing retries. Normalized quotes are merged into
retained/props/latest.json.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path

import requests
from collections import OrderedDict
from copy import deepcopy
import hashlib
import threading

from config import ODDS_API_KEY
from corner.prop_markets import build_bets, market_meta, normalize_event
from pipelines.odds_ingestion import BASE, PARAMS, fetch

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / 'retained' / 'props' / 'latest.json'
# Keep props acquisition independent of main/alternate bookmaker expansion.
from corner.collection_policy import PROP_STANDARD, PROP_EXCHANGE
BOOKS = ','.join(PROP_STANDARD + PROP_EXCHANGE)
BOOKMAKER_REGIONS = 2
# Prop prices move fast, so a fetch older than this stops counting (the main tools use two hours).
MAX_AGE = int(os.environ.get('CORNER_PROPS_MAX_AGE_SECONDS', '1800'))


def _when(text):
    return datetime.fromisoformat(text.replace('Z', '+00:00'))


def load():
    from corner.collection_readers import store_path
    path=store_path()
    if path is not None:
        from pipelines.collection_publication import read_props
        return read_props(path)
    try:
        return json.loads(STORE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'events': {}}


def _save(data):
    from pipelines.tracker_clv import retain_local_props
    retain_local_props(data, STORE)
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, separators=(',', ':')), encoding='utf-8')
    tmp.replace(STORE)


def prune(data, now=None, max_age=None):
    """Drop games that have started, and (with max_age, in seconds) markets fetched longer ago than that."""
    now = now or datetime.now(timezone.utc)
    oldest = None if max_age is None else now - timedelta(seconds=max_age)
    kept = {}
    for key, event in data.get('events', {}).items():
        if _when(event['commence_time']) <= now:
            continue
        markets = {name: m for name, m in event.get('markets', {}).items()
                   if oldest is None or (m.get('captured_at') and _when(m['captured_at']) >= oldest)}
        if markets:
            kept[key] = {**event, 'markets': markets}
    data['events'] = kept
    return data


_pricing_cache = OrderedDict()
_pricing_lock = threading.Lock()
_pricing_stats = {'hits':0,'misses':0}

def feed_candidate(bet):
    """A compact superset of every supported positive-EV devig selection."""
    if not set(bet.get('sharps',())) & {'novig','fanduel','pinnacle'}:return False
    return Decimal(bet['ev'])>0 or any(Decimal(row['ev'])>0 for row in bet.get('devig_comparisons',()))

def bets(now=None, *, one_sided_margin=None, feed_only=False):
    """Cache exact pricing inputs per standard/alternate market pair.

    Scope pruning always runs first. Quote times, links and native IDs are
    refreshed from the current target quote even when its math is unchanged.
    """
    events = prune(load(), now, MAX_AGE)['events']
    result=[]
    with _pricing_lock:
        for eid,event in events.items():
            groups={}
            targets={}
            for market,stored in event['markets'].items():
                groups.setdefault(market.removesuffix('_alternate'),{})[market]=stored
                for quote in stored['quotes']:
                    point=None if quote['point'] is None else format(Decimal(quote['point']).normalize(),'f')
                    ident=f"{eid}:{market}:{quote['player']}:{point or ''}:{quote['book']}:{quote['side']}"
                    targets[ident]=(quote,stored.get('captured_at'))
            by_market={}
            for pair in groups.values():
                header={k:v for k,v in event.items() if k!='markets'}
                semantic={m:[{k:q.get(k) for k in ('player','point','book','side','price')} for q in stored['quotes']] for m,stored in pair.items()}
                encoded=json.dumps([eid,header,semantic],sort_keys=True,separators=(',',':')).encode()
                key=(hashlib.sha256(encoded).digest(),str(one_sided_margin))
                if key not in _pricing_cache:
                    _pricing_stats['misses']+=1
                    _pricing_cache[key]=build_bets({eid:{**header,'markets':pair}},one_sided_margin=one_sided_margin,fallback_margin='0.10',include_dfs=False)
                    while len(_pricing_cache)>256 or (len(_pricing_cache)>1 and sum(len(v) for v in _pricing_cache.values())>50000):
                        _pricing_cache.popitem(last=False)
                else:_pricing_stats['hits']+=1
                _pricing_cache.move_to_end(key)
                for bet in _pricing_cache[key]:by_market.setdefault(bet.get('market_key',''),[]).append(bet)
            for market in event['markets']:
                for cached in by_market.get(market,[]):
                    if feed_only and not feed_candidate(cached):continue
                    bet=dict(cached)
                    quote,captured=targets[bet['id']]
                    bet.update(observed_at=quote.get('updated_at') or captured,links=quote.get('links'),source_ids=quote.get('source_ids'))
                    result.append(bet)
    return deepcopy(result)


def last_captured():
    """When prop odds were last fetched (newest stored market, however old), or None."""
    stamps = [m.get('captured_at') for e in prune(load())['events'].values() for m in e.get('markets', {}).values()]
    return max((s for s in stamps if s), default=None)


def replace_scope(data, sport, markets, planned_ids):
    """A fetch replaces what it covers: for these markets in this league, games outside the new
    fetch are dropped, so earlier fetches cannot pile up beside the new one."""
    for event_id, event in list(data['events'].items()):
        if event.get('sport_key') != sport or event_id in planned_ids:
            continue
        for key in markets:
            event['markets'].pop(key, None)
        if not event['markets']:
            del data['events'][event_id]


def plan(sport, max_events, session, now=None):
    """Upcoming events from the free events endpoint, soonest first, capped."""
    status, body, headers = fetch(session, f'{BASE}/{sport}/events', {'dateFormat': 'iso'})
    if status != 200:
        raise ValueError(f'Events HTTP {status}; props not requested')
    now = now or datetime.now(timezone.utc)
    events = sorted((e for e in json.loads(body) if _when(e['commence_time']) > now),
                    key=lambda e: e['commence_time'])
    return events[:max_events], headers


def capture(sport, markets, max_events, *, now=None):
    """Fetch the chosen markets for the soonest events and merge them into the store."""
    if not ODDS_API_KEY:
        raise ValueError('ODDS_API_KEY is not configured')
    if not markets or any(not market_meta(sport, m) for m in markets):
        raise ValueError('Choose valid prop markets for this league.')
    from corner.manual_markets import markets_for_event
    now = now or datetime.now(timezone.utc)
    used, stopped, done = 0, None, 0
    next_cost = 0
    with requests.Session() as session:
        session.trust_env = False
        events, quota = plan(sport, max_events, session)
        selected = [(event, markets_for_event(markets, event['commence_time'], now)) for event in events]
        planned = sum(bool(keys) for _,keys in selected)
        skipped = sum(not keys for _,keys in selected)
        data = prune(load(), now=now, max_age=MAX_AGE)  # expired markets are hidden anyway; do not keep them on disk
        replace_scope(data, sport, markets, {e['id'] for e in events})
        # Drop previously retained alternates that this local request no longer covers.
        for event,keys in selected:
            old = data['events'].get(event['id'])
            if old:
                for key in set(markets) - set(keys):old['markets'].pop(key, None)
        _save(data)
        for event,event_markets in selected:
            if not event_markets:continue
            # The only guard: a call the key cannot pay for would just be rejected.
            next_cost = len(event_markets) * BOOKMAKER_REGIONS
            if int((quota or {}).get('x-requests-remaining', '999')) < next_cost:
                stopped = 'out_of_credits'
                break
            status, body, headers = fetch(session, f"{BASE}/{sport}/events/{event['id']}/odds", {
                'bookmakers': BOOKS, 'markets': ','.join(event_markets), 'oddsFormat': 'decimal', 'dateFormat': 'iso',
                'includeLinks': 'true', 'includeSids': 'true'})
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
            for key in event_markets:
                quotes = normalize_event(payload, key, market_meta(sport, key))
                slot['markets'][key] = {'captured_at': at, 'quotes': quotes}
            done += 1
            _save(data)
    remaining = (quota or {}).get('x-requests-remaining')
    return {'events': done, 'planned': planned, 'day_of_skipped': skipped, 'next_event_credits': next_cost, 'credits_used': used, 'stopped': stopped,
            'remaining': int(remaining) if remaining and remaining.isdigit() else None}
