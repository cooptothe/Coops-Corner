"""Odds API ingestion: Odds API -> retained payload -> normalization -> PostgreSQL, per league, <=6 credits each.

No automatic retries, recurring calls, lifecycle processing, or quote re-dating.
Replay ingestion from the retained manifest spends zero provider credits.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

import requests
import psycopg2
import psycopg2.extras
from config import DB_CONFIG, ODDS_API_KEY
from corner.featured_markets import normalize_featured_payload
from corner.featured_matching import BookRoute, MarketRoute, SelectionRoute, bind_snapshot, MARKET_TYPES
from corner.featured_store import ingest_featured_payload
from corner.links import link_rows
from corner.ingestion import (_seed_provider, _create_batch, _create_payload, _resolve_event,
                              _resolve_event_participants, _resolve_sportsbook, _resolve_market,
                              _resolve_outcome, _ensure_vocabulary)

ROOT=Path(__file__).resolve().parents[1]
BASE='https://api.the-odds-api.com/v4/sports'
SPORT='americanfootball_nfl'
# Twelve named books count as two regions (six credits for three main-line markets).
# Main-line references include pinnacle, betfair_ex_uk, prophetx, kalshi, betopenly and polymarket.
BOOKMAKER_REGIONS = 2
CREDITS_PER_SPORT = 6
PARAMS={'bookmakers':'draftkings,fanduel,espnbet,betmgm,novig,betrivers,pinnacle,betfair_ex_uk,prophetx,kalshi,betopenly,polymarket','markets':'h2h,spreads,totals',
        'oddsFormat':'decimal','dateFormat':'iso','includeLinks':'true','includeSids':'true'}
SAFE_HEADERS={'date','content-type','x-requests-used','x-requests-remaining','x-requests-last'}


class InactiveSport(ValueError):
    pass


def fetch(session, url, params):
    try:
        with session.get(url,params={**params,'apiKey':ODDS_API_KEY},timeout=(10,30),
                         allow_redirects=False,stream=True) as response:
            body=response.raw.read(10*1024*1024+1,decode_content=True)
            if len(body)>10*1024*1024: raise ValueError('Response size limit')
            if ODDS_API_KEY.encode() in body: raise ValueError('Credential echo refused')
            headers={k.lower():v for k,v in response.headers.items() if k.lower() in SAFE_HEADERS}
            if ODDS_API_KEY in json.dumps(headers): raise ValueError('Credential echo refused')
            return response.status_code,body,headers
    except requests.RequestException:
        raise RuntimeError('Provider request failed; no automatic retry performed.') from None


def sanitize(body):
    """Drop book markets quoting a degenerate price (<= 1.00, e.g. a dead exchange contract)."""
    events=json.loads(body)
    changed=False
    for event in events:
        for book in event.get('bookmakers',[]):
            keep=[m for m in book.get('markets',[]) if all(o['price']>1 for o in m.get('outcomes',[]))]
            changed|=len(keep)!=len(book.get('markets',[]))
            book['markets']=keep
        event['bookmakers']=[b for b in event.get('bookmakers',[]) if b['markets']]
    if not changed: return body
    return json.dumps(events,separators=(',',':')).encode()

def active_sport_keys(prefix):
    """Active provider sport keys with this prefix, from the zero-credit catalog."""
    with requests.Session() as session:
        session.trust_env=False
        status,catalog,_=fetch(session,BASE+'/',{})
        if status!=200: raise ValueError(f'Catalog HTTP {status}; odds not requested')
        return sorted(s['key'] for s in json.loads(catalog) if s['key'].startswith(prefix) and s.get('active') and not s.get('has_outrights'))


def capture(destination, extra_params=None, sport=SPORT):
    if not ODDS_API_KEY: raise ValueError('ODDS_API_KEY is not configured')
    if destination.exists(): raise ValueError('Capture destination already exists; use --ingest to reuse it')
    with requests.Session() as session:
        session.trust_env=False
        status,catalog,quota=fetch(session,BASE+'/',{}) # documented zero-credit catalog
        if status!=200: raise ValueError(f'Catalog HTTP {status}; odds not requested')
        if int(quota.get('x-requests-remaining','0'))<CREDITS_PER_SPORT: raise ValueError('Fewer than six credits remain')
        if not any(s['key']==sport and s.get('active') for s in json.loads(catalog)):
            raise InactiveSport(f'{sport} is not listed as active; no paid request made')
        started=datetime.now(timezone.utc).isoformat()
        params={**PARAMS,**(extra_params or {})}
        status,body,headers=fetch(session,BASE+'/'+sport+'/odds/',params)
        received=datetime.now(timezone.utc).isoformat()
    destination.mkdir(parents=True,exist_ok=False)
    if status==200:
        clean=sanitize(body)
        if clean is not body:
            (destination/'response.raw').write_bytes(body); body=clean
    (destination/'response.body').write_bytes(body)
    manifest={'format':'corner.board_capture/1','endpoint':BASE+'/'+sport+'/odds/','sport':sport,
              'parameters':params,'requested_at':started,'received_at':received,'http_status':status,
              'sha256':hashlib.sha256(body).hexdigest(),'response_headers':headers,
              'catalog_quota':quota,'planned_credits':CREDITS_PER_SPORT,'automatic_retries':0,'production_authorized':False}
    (destination/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'capture':str(destination),'http_status':status,'quota':headers}))
    if status!=200: raise ValueError('Provider error retained; no ingestion performed')
    if int(headers.get('x-requests-last','0'))>CREDITS_PER_SPORT: raise ValueError('Unexpected provider charge; no further calls permitted')


def _bind(conn,provider,snapshot,raw,sport):
    """Resolve (creating when new) the canonical events, markets, outcomes and sportsbooks a capture refers to."""
    routes=[];books={}
    for event in json.loads(raw,parse_float=Decimal):
        if event['sport_key']!=sport: raise ValueError('Unexpected sport')
        with conn.cursor() as cur:
            cur.execute('SELECT e.event_status_id FROM corner.events e JOIN corner.event_provider_identities p ON p.event_id=e.id WHERE p.provider_id=%s AND p.external_id=%s',(provider,event['id']))
            previous=cur.fetchone()
            unknown=_ensure_vocabulary(cur,'event_statuses','unknown','Unknown')
        event_id,competition_id=_resolve_event(conn,provider,event)
        with conn.cursor() as cur:
            cur.execute('UPDATE corner.events SET event_status_id=%s WHERE id=%s',(previous[0] if previous else unknown,event_id))
            # Explicit provider competition identity needed by the featured writer.
            cur.execute('INSERT INTO corner.competition_provider_identities(provider_id,competition_id,external_id) VALUES (%s,%s,%s) ON CONFLICT(provider_id,external_id) DO NOTHING',(provider,competition_id,sport))
        participants=_resolve_event_participants(conn,provider,competition_id,event_id,event)
        event_quotes=[q for q in snapshot.quotes if q.event_id==event['id']]
        for key in sorted({q.market_key for q in event_quotes}):
            market_id=str(_resolve_market(conn,event_id,MARKET_TYPES[key],'full_game'))
            selections={}
            for q in (q for q in event_quotes if q.market_key==key):
                if q.bookmaker_key not in books:
                    books[q.bookmaker_key]=str(_resolve_sportsbook(conn,provider,q.bookmaker_key,q.bookmaker_title))
                paid=(q.selection_name,q.point)
                if paid not in selections:
                    outcome=str(_resolve_outcome(conn,market_id,participants.get(q.selection_name),q.selection_side,q.point))
                    selections[paid]=SelectionRoute(*paid,outcome)
            routes.append(MarketRoute(event['id'],sport,key,market_id,tuple(selections.values())))
    bindings=bind_snapshot(snapshot,markets=tuple(routes),books=tuple(BookRoute(k,v) for k,v in books.items()))
    return bindings,books


def upsert_links(conn,rows,captured_at):
    """Keep the newest links per outcome and sportsbook; an older capture never replaces a newer one."""
    if not rows: return 0
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur,'''INSERT INTO corner.quote_links
            (outcome_id,sportsbook_id,event_url,market_url,outcome_url,captured_at) VALUES %s
            ON CONFLICT (outcome_id,sportsbook_id) DO UPDATE SET event_url=EXCLUDED.event_url,market_url=EXCLUDED.market_url,
                outcome_url=EXCLUDED.outcome_url,captured_at=EXCLUDED.captured_at
            WHERE corner.quote_links.captured_at<=EXCLUDED.captured_at''',
            [(o,s,e,m,u,captured_at) for o,s,e,m,u in rows])
    return len(rows)


def refresh_links(directory):
    """Store the links in a retained capture without ingesting it again. Spends no provider credits."""
    manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    raw=(directory/'response.body').read_bytes()
    if manifest['http_status']!=200 or hashlib.sha256(raw).hexdigest()!=manifest['sha256']:
        raise ValueError('Retained capture integrity failure')
    sport=manifest.get('sport',SPORT)
    at=datetime.fromisoformat(manifest['received_at'])
    snapshot=normalize_featured_payload(raw,received_at=at)
    conn=psycopg2.connect(**DB_CONFIG)
    try:
        bindings,_=_bind(conn,_seed_provider(conn),snapshot,raw,sport)
        stored=upsert_links(conn,link_rows(snapshot,bindings),at)
        conn.commit()
        print(json.dumps({'capture':directory.name,'sport':sport,'links':stored}))
    finally:
        conn.rollback();conn.close()

def ingest(directory):
    manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    raw=(directory/'response.body').read_bytes()
    if manifest['http_status']!=200 or hashlib.sha256(raw).hexdigest()!=manifest['sha256']:
        raise ValueError('Retained capture integrity failure')
    sport=manifest.get('sport',SPORT)
    at=datetime.fromisoformat(manifest['received_at'])
    snapshot=normalize_featured_payload(raw,received_at=at)
    if any(q.sport_key!=sport or q.market_key not in ('h2h','spreads','totals','h2h_lay') for q in snapshot.quotes):
        raise ValueError('Capture exceeds the explicit main-market scope')
    conn=psycopg2.connect(**DB_CONFIG)
    try:
        # Reuses exact retained payload on rerun. The process does not fetch again.
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM corner.provider_payloads WHERE payload_sha256=%s AND received_at=%s ORDER BY id LIMIT 1",(bytes.fromhex(manifest['sha256']),at))
            old=cur.fetchone()
            if old:
                cur.execute('SELECT count(*) FROM corner.odds_observations WHERE provider_payload_id=%s',(old[0],))
                count=cur.fetchone()[0]
                if count!=len(snapshot.quotes): raise ValueError('Existing ingestion is incomplete')
                print(json.dumps({'payload_id':str(old[0]),'observations':count,'reused':True}));return
        provider=_seed_provider(conn)
        bindings,books=_bind(conn,provider,snapshot,raw,sport)
        batch=_create_batch(conn,provider,{'source':'one_shot_board_capture','capture_sha256':manifest['sha256'],'parameters':PARAMS})
        payload=str(_create_payload(conn,batch,provider,at,raw))
        receipt=ingest_featured_payload(conn,payload_id=payload,bindings=bindings)
        stored_links=upsert_links(conn,link_rows(snapshot,bindings),at)
        with conn.cursor() as cur: cur.execute("UPDATE corner.ingestion_batches SET processing_status='completed',completed_at=now() WHERE id=%s",(batch,))
        conn.commit()
        print(json.dumps({'payload_id':payload,'events':len(json.loads(raw)),'observations':len(receipt.observation_ids),'links':stored_links,'books':list(books),'production_authorized':False}))
    finally:
        conn.rollback();conn.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    actions=parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--capture',type=Path);actions.add_argument('--ingest',type=Path)
    actions.add_argument('--links',type=Path,help='store the links of a retained capture (no credits, no re-ingest)')
    args=parser.parse_args()
    try:
        if args.capture: capture(args.capture)
        elif args.links: refresh_links(args.links)
        else: ingest(args.ingest)
    except Exception as error:
        # Requests/DB exception text may contain connection details.
        print(f'Operation failed ({type(error).__name__}); retained evidence is preserved.',file=sys.stderr)
        raise SystemExit(1) from None

if __name__=='__main__': main()
