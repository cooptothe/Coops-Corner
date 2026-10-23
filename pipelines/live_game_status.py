"""Free ESPN game-state enrichment. Background cache; never blocks odds reads."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import re
import threading
import time
import httpx
from corner.collection_policy import CENTRAL, parse
from corner.tracker_live import ESPN, espn_path, find_event

REFRESH = 15
FRESH = 30
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='game-status')
_lock = threading.Lock()
_cache = {}
_sizes = {}
_pending = set()

def unknown():
    return dict(game_status='unknown', game_status_detail='Game status unavailable',
                game_status_source=None, game_status_updated_at=None, game_status_expires_at=0,
                game_stoppage_confirmed=False)

def classify(event, now, checked, plays=None):
    result = unknown()
    if not 0 <= now-checked <= FRESH: return result
    competition = (event.get('competitions') or [{}])[0]
    status = competition.get('status') or event.get('status') or {}
    kind = status.get('type') or {}
    name = str(kind.get('name','')).upper()
    detail = str(kind.get('shortDetail') or kind.get('detail') or kind.get('description') or '')[:160]
    text = (name+' '+detail).lower().replace('_',' ')
    expiry = checked+FRESH
    if kind.get('completed') is True or name in ('STATUS_FINAL','STATUS_FULL_TIME'):
        state = 'finished'
    elif any(word in text for word in ('halftime','half time','intermission','end period','end of period','end quarter','end of quarter','timeout','time out','delayed','suspended','rain delay')):
        state = 'paused'
    elif kind.get('state') == 'pre': state = 'not_started'
    elif kind.get('state') == 'in':
        state = 'in_play'
        # Only the latest play can identify a timeout. A subsequent play clears it.
        # Missing wallclock is never sufficient evidence of a current timeout.
        if plays:
            last = plays[-1]
            play_type = str((last.get('type') or {}).get('text','')).lower()
            if 'timeout' in play_type or 'time out' in play_type:
                try: at = parse(last['wallclock']).timestamp()
                except (KeyError,ValueError,TypeError): at = 0
                if 0 <= now-at <= 45:
                    state = 'paused'
                    detail = 'Timeout'
                    expiry = min(expiry,at+45)
    else: return result
    result.update(game_status=state,game_status_detail=detail or state.replace('_',' ').title(),
        game_status_source='espn',game_status_updated_at=datetime.fromtimestamp(checked,timezone.utc).isoformat(),
        game_status_expires_at=expiry,game_stoppage_confirmed=state=='paused')
    return result

def _fetch(url):
    with httpx.Client(trust_env=False,follow_redirects=False,timeout=httpx.Timeout(5,connect=2)) as client:
        with client.stream('GET',url,headers={'User-Agent':'CoopsCorner/GameStatus'}) as response:
            response.raise_for_status()
            raw = bytearray()
            for part in response.iter_bytes():
                raw.extend(part)
                if len(raw)>4_000_000: raise ValueError('Game status response too large')
            body=json.loads(raw)
            if not isinstance(body,dict): raise ValueError('Invalid game status')
            return body

def _load(url):
    try: payload = _fetch(url)
    except Exception: payload = None
    size = len(json.dumps(payload,separators=(',',':')).encode())
    with _lock:
        _cache[url]=(time.time(),payload)
        _sizes[url]=size
        # Cached payloads are parsed objects: keep the serialized basis under 16MB.
        while len(_cache)>64 or sum(_sizes.get(k,0) for k in _cache)>16_000_000:
            oldest=min(_cache,key=lambda k:_cache[k][0])
            _cache.pop(oldest,None)
            _sizes.pop(oldest,None)
        _pending.discard(url)

def cached(url,now):
    with _lock:
        hit=_cache.get(url)
        if (not hit or now-hit[0]>=REFRESH) and url not in _pending and len(_pending)<32:
            _pending.add(url)
            _pool.submit(_load,url)
    return hit if hit and 0<=now-hit[0]<=FRESH and hit[1] is not None else None

def enrich(payload):
    """Return copies: shared odds-analysis caches must never be mutated."""
    now=time.time()
    events=[]
    for original in payload.get('events',[]):
        item={**original,**unknown()}
        path=espn_path(item['sport_key'])
        if path:
            try:
                start=parse(item['commence_time'])
                date=start.astimezone(CENTRAL).strftime('%Y%m%d')
                hit=cached(f'{ESPN}/{path}/scoreboard?dates={date}&limit=300',now)
                if hit:
                    matched=find_event(hit[1].get('events',[]),item['away_team'],item['home_team'],item['commence_time'])
                    if matched and abs((parse(matched['date'])-start).total_seconds())<=3*3600:
                        item.update(classify(matched,now,hit[0]))
                        event_id=str(matched.get('id',''))
                        if item['game_status']=='in_play' and re.fullmatch(r'[0-9]{1,20}',event_id):
                            summary=cached(f'{ESPN}/{path}/summary?event={event_id}',now)
                            if summary:
                                header=summary[1].get('header') or {}
                                # Use only a fresher summary from this matched event.
                                if str(header.get('id',''))==event_id:
                                    item.update(classify(header,now,summary[0],summary[1].get('plays')))
            except (KeyError,ValueError,TypeError,AttributeError): pass
        if item['game_status'] in ('finished','not_started'):
            item.update(opportunities=[],tool_rows=[],quotes=[])
        events.append(item)
    return {**payload,'events':events,'game_stoppage_confirmed':any(e['game_stoppage_confirmed'] for e in events)}
