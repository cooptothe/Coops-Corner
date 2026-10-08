"""Local media service: resolves team logos and player headshots, and serves them same-origin.

Nothing here touches the Odds API or spends credits. Lookups use ESPN's public endpoints, with
TheSportsDB (its public test key) as a fallback. Results and image bytes are cached on disk so each
name is resolved once and the app keeps working offline. Failures are never cached, so a rate limit
or outage cannot turn into a permanent "no image".
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import threading
import time

import requests
from fastapi import APIRouter, Query
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response

from corner import media

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / 'retained' / 'media'
ESPN_SITE = 'https://site.api.espn.com/apis/site/v2/sports'
ESPN_SEARCH = 'https://site.web.api.espn.com/apis/common/v3/search'
TSDB = 'https://www.thesportsdb.com/api/v1/json/3'
TEAM_TTL = 7 * 86400
INDEX_VERSION = 2  # bump when the index shape or matching keys change, so stale files are rebuilt
HIT_TTL = 30 * 86400
MISS_TTL = 86400
BACKOFF = 60
MAX_NAMES = 40
MAX_IMAGE = 1_500_000
IMAGE_TYPES = {'image/png', 'image/jpeg', 'image/webp', 'image/gif'}
SPORT_KEY = re.compile(r'^[a-z0-9_]{1,60}$')


class UpstreamError(RuntimeError):
    pass


def http_json(url, params=None, limit=8_000_000):
    try:
        with requests.get(url, params=params, timeout=(5, 12), allow_redirects=False, stream=True,
                          headers={'User-Agent': 'coops-corner-local/1'}) as response:
            if response.status_code != 200:
                raise UpstreamError(f'HTTP {response.status_code}')
            body = response.raw.read(limit + 1, decode_content=True)
            if len(body) > limit:
                raise UpstreamError('response too large')
            return json.loads(body)
    except (requests.RequestException, ValueError) as error:
        raise UpstreamError(type(error).__name__) from None


def http_image(url):
    try:
        with requests.get(url, timeout=(5, 12), allow_redirects=False, stream=True,
                          headers={'User-Agent': 'coops-corner-local/1'}) as response:
            kind = response.headers.get('content-type', '').split(';')[0].strip().lower()
            if response.status_code != 200 or kind not in IMAGE_TYPES:
                return None
            body = response.raw.read(MAX_IMAGE + 1, decode_content=True)
            return (body, kind) if 0 < len(body) <= MAX_IMAGE else None
    except requests.RequestException:
        return None


class MediaStore:
    def __init__(self, cache=CACHE, fetch_json=http_json, fetch_image=http_image, clock=time.time):
        self.cache, self.fetch_json, self.fetch_image, self.clock = Path(cache), fetch_json, fetch_image, clock
        self._lock = threading.Lock()
        self._indexes = {}
        self._lookups = None
        self._blocked = {}

    # -- small JSON cache -------------------------------------------------------------------
    def _read(self, name):
        try:
            return json.loads((self.cache / name).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None

    def _write(self, name, value):
        try:
            self.cache.mkdir(parents=True, exist_ok=True)
            tmp = (self.cache / name).with_suffix('.tmp')
            tmp.write_text(json.dumps(value, separators=(',', ':')), encoding='utf-8')
            tmp.replace(self.cache / name)
        except OSError:
            pass

    def _lookups_view(self):
        if self._lookups is None:
            self._lookups = self._read('lookups.json') or {}
        return self._lookups

    def _cached(self, key):
        entry = self._lookups_view().get(key)
        if not entry:
            return False, None
        ttl = HIT_TTL if entry.get('url') else MISS_TTL
        return (True, entry.get('url')) if self.clock() - entry.get('at', 0) < ttl else (False, None)

    def _store(self, key, url):
        with self._lock:
            self._lookups_view()[key] = {'url': url, 'at': self.clock()}

    def _flush(self):
        with self._lock:
            self._write('lookups.json', self._lookups_view())

    # -- upstream, with a short backoff after a failure -------------------------------------
    def _call(self, host, url, params=None):
        if self._blocked.get(host, 0) > self.clock():
            raise UpstreamError('backing off')
        try:
            return self.fetch_json(url, params)
        except UpstreamError:
            self._blocked[host] = self.clock() + BACKOFF
            raise

    # -- teams ------------------------------------------------------------------------------
    def team_index(self, sport_key):
        sources = media.team_sources(sport_key)
        if not sources:
            return {}
        name = 'teams-' + hashlib.sha1(json.dumps([INDEX_VERSION, sources]).encode()).hexdigest()[:12]
        if name in self._indexes and self.clock() - self._indexes[name][0] < TEAM_TTL:
            return self._indexes[name][1]
        saved = self._read(name + '.json')
        if saved and self.clock() - saved.get('at', 0) < TEAM_TTL:
            self._indexes[name] = (saved['at'], saved['index'])
            return saved['index']
        try:
            payloads = [self._call('espn', f'{ESPN_SITE}/{s}/{lg}/teams', {'limit': 1000}) for s, lg in sources]
        except UpstreamError:
            if saved:  # a stale index beats no logos while ESPN is unreachable
                return saved['index']
            raise
        index = media.build_team_index(payloads)
        self._indexes[name] = (self.clock(), index)
        self._write(name + '.json', {'at': self.clock(), 'index': index})
        return index

    def _team(self, sport_key, name, index):
        if index is None:
            return None, False
        record = media.match_team(index, name)
        if record:
            return media.team_logo_url(record), True
        key = f'team|{sport_key}|{media.norm(name)}'
        hit, url = self._cached(key)
        if hit:
            return url, True
        try:
            data = self._call('tsdb', f'{TSDB}/searchteams.php', {'t': name})
        except UpstreamError:
            return None, False
        url = media.pick_tsdb_team(data.get('teams'), name, sport_key)
        self._store(key, url)
        return url, True

    # -- players ----------------------------------------------------------------------------
    def _player(self, sport_key, name):
        key = f'player|{sport_key}|{media.norm(name, drop_suffix=True)}'
        hit, url = self._cached(key)
        if hit:
            return url, True
        try:
            data = self._call('espn', ESPN_SEARCH, {'query': name, 'limit': 8, 'type': 'player'})
            url = media.pick_player(data.get('items'), name, sport_key)
            if not url:
                data = self._call('tsdb', f'{TSDB}/searchplayers.php', {'p': name})
                url = media.pick_tsdb_player(data.get('player'), name, sport_key)
        except UpstreamError:
            return None, False
        self._store(key, url)
        return url, True

    # -- batch ------------------------------------------------------------------------------
    def resolve(self, kind, sport_key, names):
        """-> (results, retry). `retry` lists names that failed upstream: not "no image", just not yet."""
        results, retry = {}, []
        if kind == 'team':
            try:
                index = self.team_index(sport_key)
            except UpstreamError:
                index = None  # ESPN is unreachable: do not let the fallback cache a false "no logo"
            work = lambda n: self._team(sport_key, n, index)
        else:
            work = lambda n: self._player(sport_key, n)
        unique = list(dict.fromkeys(names))
        with ThreadPoolExecutor(max_workers=4) as pool:
            for name, (url, cacheable) in zip(unique, pool.map(work, unique)):
                results[name] = url
                if url is None and not cacheable:
                    retry.append(name)
        self._flush()
        return results, retry

    # -- image proxy ------------------------------------------------------------------------
    def image(self, url):
        if not media.allowed_image(url):
            return None
        digest = hashlib.sha256(url.encode()).hexdigest()
        body, kind = self.cache / 'img' / f'{digest}.bin', self.cache / 'img' / f'{digest}.type'
        try:
            return body.read_bytes(), kind.read_text(encoding='ascii')
        except OSError:
            pass
        fetched = self.fetch_image(url)
        if fetched:
            try:
                body.parent.mkdir(parents=True, exist_ok=True)
                body.write_bytes(fetched[0])
                kind.write_text(fetched[1], encoding='ascii')
            except OSError:
                pass
        return fetched


def create_router(store=None):
    store = store or MediaStore()
    router = APIRouter(prefix='/api/refresh/v1/media')

    @router.get('/resolve')
    async def resolve(kind: str = Query(...), sport: str = Query(...), n: list[str] = Query(default=[])):
        valid = (kind in ('team', 'player') and SPORT_KEY.match(sport)
                 and (media.sport_family(sport) or media.team_sources(sport))
                 and 0 < len(n) <= MAX_NAMES and all(0 < len(x) <= 80 for x in n))
        if not valid:
            return JSONResponse({'error': 'Invalid media request.'}, status_code=400)
        results, retry = await run_in_threadpool(store.resolve, kind, sport, n)
        return JSONResponse({'results': results, 'retry': retry}, headers={'Cache-Control': 'no-store'})

    @router.get('/img')
    async def image(u: str = Query(..., max_length=600)):
        found = await run_in_threadpool(store.image, u)
        if not found:
            return Response(status_code=404, headers={'Cache-Control': 'no-store'})
        return Response(found[0], media_type=found[1], headers={
            'Cache-Control': 'public, max-age=604800, immutable',
            'X-Content-Type-Options': 'nosniff',
            'Content-Security-Policy': "default-src 'none'; sandbox"})

    return router
