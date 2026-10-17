"""Free, cached ESPN prop research. No odds purchase, article scraping or news multiplier."""
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
import re
from pathlib import Path
import sqlite3
import threading
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from corner import media, tracker_live
from corner.prop_markets import market_meta
from corner.pricing import fee_policy
from corner.prop_trends import analyze, instant, number
from pipelines import props_ingestion
from pipelines.media import http_json, UpstreamError

ROOT = Path(__file__).resolve().parents[1]
LEAGUES = {key:value[0] for key,value in tracker_live.LEAGUES.items()
           if key in ('basketball_nba','basketball_wnba','americanfootball_nfl','icehockey_nhl','baseball_mlb')}
SITE = 'https://site.api.espn.com/apis/site/v2/sports'
COMMON = 'https://site.web.api.espn.com/apis/common/v3'


def safe_link(value):
    try:
        parsed = urlsplit(value)
        return value if parsed.scheme=='https' and parsed.hostname in ('www.espn.com','espn.com') and not parsed.username else None
    except (ValueError,TypeError):
        return None


def stat_specs(sport, market):
    specs = tracker_live.PROP_TABLES.get(sport.split('_')[0].replace('americanfootball','football').replace('icehockey','hockey'),{}).get(market)
    if not specs:
        return None
    # ESPN game-log fields are atomic, unlike box-score made-attempted cells.
    aliases = {'rebounds':'totalRebounds','threePointFieldGoalsMade-threePointFieldGoalsAttempted':'threePointFieldGoalsMade',
               'completions/passingAttempts':'completions','completions/passingAttempts#2':'passingAttempts',
               'fieldGoalsMade/fieldGoalAttempts':'fieldGoalsMade'}
    return [aliases.get(key,key) for key in specs[1]]


def read_stat(values, key):
    if key=='threePointFieldGoalsMade':
        return number(str(values.get('threePointFieldGoalsMade-threePointFieldGoalsAttempted','')).split('-')[0])
    return tracker_live._read(values,key)


def normalize_games(payload, sport, market, season):
    specs = stat_specs(sport,market)
    if specs is None:
        return []
    names, output = payload.get('names',[]), []
    for kind in payload.get('seasonTypes',[]):
        if 'regular' not in kind.get('displayName','').lower():
            continue
        for category in kind.get('categories',[]):
            if category.get('type')!='event':
                continue
            for row in category.get('events',[]):
                event = payload.get('events',{}).get(str(row.get('eventId')), {})
                if row.get('didNotPlay') or row.get('didNotDress'):
                    continue
                # Final W/L/T plus a historical date is required; scheduled/DNP cells fail closed.
                if event.get('gameResult') not in ('W','L','T') or len(row.get('stats',[]))!=len(names):
                    continue
                values = dict(zip(names,row['stats']))
                parts = [read_stat(values,key) for key in specs]
                if any(number(v) is None for v in parts):
                    continue
                minutes = values.get('minutes') or values.get('timeOnIcePerGame')
                if minutes and ':' in str(minutes):
                    try:
                        minute,second = str(minutes).split(':')
                        minutes = float(minute)+float(second)/60
                    except ValueError:
                        minutes = None
                workload = number(minutes or values.get('atBats') or values.get('passingAttempts') or values.get('rushingAttempts'))
                if minutes is not None and number(minutes)==0:
                    continue
                output.append({'id':str(row['eventId']), 'date':event.get('gameDate'),
                               'value':str(sum(Decimal(str(v)) for v in parts)),
                               'workload':str(workload) if workload is not None else None,
                               'opponent':(event.get('opponent') or {}).get('displayName',''),
                               'home':event.get('atVs')=='vs' if event.get('atVs') in ('vs','@','at') else None, 'completed':True,
                               'season':season, 'team':kind.get('displayTeam',''),
                               'source_url':next((link['href'] for link in event.get('links',[]) if safe_link(link.get('href'))),None)})
    return output


class ResearchUnavailable(ValueError):
    pass


class Trends:
    def __init__(self, path=None, fetch=http_json, clock=time.time):
        self.path = Path(path) if path else Path(os.environ.get('CORNER_TRENDS_DB',str(ROOT/'retained/trends.sqlite3')))
        self.fetch, self.clock, self.lock = fetch,clock,threading.Lock()

    def _db(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        db = sqlite3.connect(self.path,timeout=3)
        db.execute('CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, at REAL, body TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS budget (hour INTEGER PRIMARY KEY, calls INTEGER)')
        return db

    def cached(self,key,ttl,loader,*,cached_only=False):
        # Single-flight across the service; SQLite also shares the hourly request budget.
        with self.lock:
            now = self.clock()
            with closing(self._db()) as db:
                row = db.execute('SELECT at,body FROM cache WHERE key=?',(key,)).fetchone()
                cached = json.loads(row[1]) if row else None
                if row and 0<=now-row[0]<(120 if cached.get('_unavailable') else ttl):
                    return cached,row[0]
                if cached_only:
                    raise ResearchUnavailable('Research has not been cached yet.')
                db.execute('BEGIN IMMEDIATE')
                hour = int(now//3600)
                count = db.execute('SELECT calls FROM budget WHERE hour=?',(hour,)).fetchone()
                if count and count[0]>=240:
                    db.rollback()
                    raise ResearchUnavailable('Free research request limit reached. Please try again later.')
                db.execute('INSERT INTO budget VALUES(?,1) ON CONFLICT(hour) DO UPDATE SET calls=calls+1',(hour,))
                db.execute('DELETE FROM budget WHERE hour<?',(hour-24,))
                db.commit()
                try:
                    data = loader()
                    if not isinstance(data,dict):
                        raise ValueError('Unexpected source schema')
                except (UpstreamError,KeyError,ValueError,TypeError,AttributeError) as error:
                    # Short negative cache prevents outage-driven request storms.
                    data = {'_unavailable':True}
                    db.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?)',(key,now,json.dumps(data)))
                    db.commit()
                    raise ResearchUnavailable('Research source is temporarily unavailable.') from error
                db.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?)',(key,now,json.dumps(data)))
                db.execute('DELETE FROM cache WHERE key IN (SELECT key FROM cache ORDER BY at DESC LIMIT -1 OFFSET 500)')
                db.commit()
                return data,now

    def identity(self,contract,*,cached_only=False):
        sport,league = LEAGUES[contract['sport_key']].split('/')
        name = contract['player']
        def load():
            payload = self.fetch(COMMON+'/search',{'query':name,'type':'player','limit':8})
            hits = [item for item in payload.get('items',[]) if item.get('sport')==sport and item.get('league')==league
                    and media.norm(item.get('displayName'))==media.norm(name) and str(item.get('id','')).isdigit()]
            if len(hits)!=1:
                raise ResearchUnavailable('Player identity could not be matched uniquely.')
            item = hits[0]
            teams = [r.get('core',{}).get('displayName','') for r in item.get('teamRelationships',[])]
            return {'id':str(item['id']), 'name':item['displayName'], 'teams':teams}
        identity, _ = self.cached('identity:'+contract['sport_key']+':'+media.norm(name),7*86400,load,cached_only=cached_only)
        if identity.get('_unavailable') or not identity.get('teams'):
            raise ResearchUnavailable('Player identity is unavailable.')
        matched = [team for team in identity['teams'] if tracker_live.same_team(team,contract['home']) or tracker_live.same_team(team,contract['away'])]
        if len(matched)!=1:
            raise ResearchUnavailable('Player team does not match this event; identity review is needed.')
        return {**identity,'team':matched[0]}

    def research(self,contract,*,cached_only=False):
        if contract['sport_key'] not in LEAGUES or not stat_specs(contract['sport_key'],contract['market_key']):
            raise ResearchUnavailable('Game-log coverage is not available for this league or prop yet.')
        identity = self.identity(contract,cached_only=cached_only)
        path = LEAGUES[contract['sport_key']]
        now = self.clock()
        current = datetime.fromtimestamp(now,timezone.utc)
        season = current.year + int(path in ('basketball/nba','hockey/nhl') and current.month>=7)
        if path=='football/nfl' and current.month<3:
            season -= 1
        games, fetched_at = [],[]
        for year in (season,season-1):
            payload, at = self.cached(f'games:{path}:{identity["id"]}:{year}',6*3600,
                                      lambda year=year:self.fetch(f'{COMMON}/sports/{path}/athletes/{identity["id"]}/gamelog',{'season':year}),cached_only=cached_only)
            if payload.get('_unavailable'):
                raise ResearchUnavailable('Player game logs are temporarily unavailable.')
            games += normalize_games(payload,contract['sport_key'],contract['market_key'],year)
            fetched_at.append(at)
            if len(games)>=30:
                break
        is_home = tracker_live.same_team(identity['team'],contract['home'])
        opponent = contract['away'] if is_home else contract['home']
        for game in games:
            if tracker_live.same_team(game['opponent'],opponent):
                game['opponent'] = opponent
        result = analyze(games,line=contract['point'],side=contract['side'],price=contract['price'],commission=contract['commission'],as_of=now,opponent=opponent,home=is_home)
        result['player'] = identity['name']
        result['stats_fetched_at'] = datetime.fromtimestamp(min(fetched_at),timezone.utc).isoformat()
        result['source'] = 'ESPN game logs; source availability and coverage may change'
        result['workload_label'] = {'basketball':'Minutes','hockey':'Ice time (minutes)','football':'Attempts (where available)','baseball':'At-bats (where available)'}[path.split('/')[0]]
        result['coverage'] = 'Regular season only; up to two seasons, last 40 usable games.'
        result['flags'].append('Confirm starting status, expected role and sportsbook settlement; appearances can differ from eligible wagers.')
        result['contract'] = contract
        result['availability_url'] = f'https://www.espn.com/{path.split("/")[-1]}/injuries'
        try:
            def player_news_load():
                raw = self.fetch(f'{COMMON}/sports/{path}/athletes/{identity["id"]}/overview')
                return {'articles':[{'headline':str(a.get('headline',''))[:180], 'published':a.get('published') or a.get('lastModified'),
                                     'updated':a.get('lastModified'), 'url':(a.get('links',{}).get('web',{}) or {}).get('href'), 'player_specific':True}
                                    for a in raw.get('news',[]) if not a.get('premium')]}
            player_news, player_news_at = self.cached('player-news:'+path+':'+identity['id'],900,player_news_load,cached_only=cached_only)
            def news_load():
                raw = self.fetch(f'{SITE}/{path}/news',{'limit':30})
                return {'articles':[{'headline':str(a.get('headline',''))[:180], 'published':a.get('published'),
                                     'updated':a.get('lastModified'), 'url':(a.get('links',{}).get('web',{}) or {}).get('href')}
                                    for a in raw.get('articles',[])]}
            news, at = self.cached('news:'+path,900,news_load,cached_only=cached_only)
            result['news_fetched_at'] = datetime.fromtimestamp(at,timezone.utc).isoformat()
            articles = player_news.get('articles',[])+news.get('articles',[])
            result['news'] = [a for a in articles if safe_link(a.get('url')) and instant(a.get('published')) is not None
                              and 0<=now-instant(a['published'])<=7*86400 and (instant(a.get('updated')) or 0)<=now
                              and (a.get('player_specific') or any(media.norm(term) in media.norm(a['headline']) for term in (identity['name'],contract['home'],contract['away'])))][:5]
            result['news'] = list({a['url']:a for a in result['news']}.values())
            result['news_status'] = 'unavailable' if news.get('_unavailable') or player_news.get('_unavailable') else 'available'
        except ResearchUnavailable:
            result.update(news=[],news_status='unavailable',news_fetched_at=None)
        if result['news_status']=='unavailable':
            result['flags'].append('News source unavailable; this does not mean there is no injury or lineup news.')
            result['research_signal'] = False
        if any(re.search(r'\b(injur\w*|out|questionable|doubtful|illness|surgery|restricted|minutes limit)\b',a['headline'],re.I) for a in result['news']):
            result['flags'].append('An availability-related headline needs review; no numerical injury adjustment has been fitted.')
            result['research_signal'] = False
        if (instant(contract['starts_at']) or 0)<=self.clock():
            raise ResearchUnavailable('This event has started.')
        return result


def contracts():
    """Include retained one-sided props even when market-consensus EV is unavailable."""
    output, conflicts = {},set()
    data = props_ingestion.prune(props_ingestion.load(),max_age=props_ingestion.MAX_AGE)
    for eid,event in data['events'].items():
        for market,stored in event['markets'].items():
            for quote in stored['quotes']:
                policy = fee_policy(quote['book'])
                point,price = number(quote.get('point')),number(quote.get('price'))
                if policy.commission is None or point is None or price is None or price<=1 or quote.get('side') not in (0,1):
                    continue
                observed = instant(quote.get('updated_at') or stored.get('captured_at'))
                if observed is None or not -60 <= time.time()-observed <= props_ingestion.MAX_AGE:
                    continue
                key = [eid,market,quote['player'],str(point),quote['side'],quote['book']]
                ident = hashlib.sha256(json.dumps(key).encode()).hexdigest()
                if ident in conflicts:
                    continue
                if ident in output:
                    output.pop(ident)
                    conflicts.add(ident)
                    continue
                legacy = f'{eid}:{market}:{quote["player"]}:{quote.get("point") or ""}:{quote["book"]}:{quote["side"]}'
                output[ident] = {'id':ident,'bet_id':legacy,'event_id':eid,'sport_key':event['sport_key'],
                                 'home':event['home_team'],'away':event['away_team'],'starts_at':event['commence_time'],
                                 'player':quote['player'],'market_key':market,'point':str(point),
                                 'side':'Over' if quote['side']==0 else 'Under','book':quote['book'],
                                 'price':str(price),'commission':str(policy.commission)}
                meta = market_meta(event['sport_key'],market)
                output[ident]['market_label'] = meta.label if meta else market
                output[ident]['source_ids'] = quote.get('source_ids')
                output[ident]['observed_at'] = quote.get('updated_at') or stored.get('captured_at')
                output[ident]['links'] = quote.get('links')
                if len(output)>=2000:
                    return output
    return output


def create_router(ctx,service=None):
    router = APIRouter(prefix='/api/refresh/v1/props/trends')
    service = service or Trends()
    @router.get('/options')
    async def options(request:Request):
        _,denied = ctx.require(request,write=False)
        if denied:return denied
        items = await run_in_threadpool(contracts)
        return JSONResponse({'contracts':list(items.values()),'supported_sports':list(LEAGUES)},headers={'Cache-Control':'no-store'})
    @router.get('/shortlist')
    async def shortlist(request:Request):
        _,denied = ctx.require(request,write=False)
        if denied:return denied
        def scan():
            items = sorted(contracts().values(),key=lambda c:c['starts_at'])[:300]
            found,checked,unavailable = [],0,0
            for item in items:
                try:
                    result = service.research(item,cached_only=True)
                    checked += 1
                    if result['research_signal']:
                        found.append({'contract':item,'model_ev':result['model_ev'],'games':result['baseline']['games'],'recent':result['windows']['10']})
                except (ResearchUnavailable,ValueError,sqlite3.Error):
                    unavailable += 1
            return {'signals':sorted(found,key=lambda x:x['model_ev'],reverse=True)[:25],
                    'checked':checked,'unavailable':unavailable,'cached_only':True,'edge_validated':False}
        return JSONResponse(await run_in_threadpool(scan),headers={'Cache-Control':'no-store'})
    @router.get('')
    async def detail(request:Request):
        _,denied = ctx.require(request,write=False)
        if denied:return denied
        ident = request.query_params.get('id','')
        items = await run_in_threadpool(contracts)
        if ident not in items:
            return JSONResponse({'error':'This quote expired or is no longer available.'},status_code=404)
        try:
            result = await run_in_threadpool(service.research,items[ident])
            latest = (await run_in_threadpool(contracts)).get(ident)
            if latest is None or latest['price']!=items[ident]['price'] or latest.get('observed_at')!=items[ident].get('observed_at'):
                return JSONResponse({'error':'This quote changed while research loaded. Select it again to review the current price.'},status_code=409,headers={'Cache-Control':'no-store'})
            return JSONResponse(result,headers={'Cache-Control':'no-store'})
        except (ResearchUnavailable,ValueError,TypeError,KeyError,ArithmeticError,sqlite3.Error):
            return JSONResponse({'error':'Trends are unavailable for this selection. Check coverage or try again later.'},status_code=503,headers={'Cache-Control':'no-store'})
    return router
