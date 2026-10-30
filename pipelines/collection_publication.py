"""Recorded-response publication adapters; no provider requests.

MainPublisher needs an explicitly supplied restricted writer connection. API
processes retain their reader login. PostgreSQL ingestion remains replayable.
"""
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile

from corner.collection_policy import Job, aware, NO_SCHEDULED_PROPS, BASE_STANDARD, STANDARD, LEGACY_STANDARD, EXCHANGE, LEGACY_EXCHANGE


class MainPublisher:
    def __init__(self,root,connect,ingest=None):
        self.root=Path(root)
        self.connect=connect
        if ingest is None:
            from pipelines.odds_ingestion import ingest
        self.ingest=ingest

    def __call__(self,token,record):
        if record.get('simulation'):
            raise ValueError('Simulation outbox cannot publish into member feeds')
        if not re.fullmatch(r'[a-f0-9]{48}',token):raise ValueError('Invalid publication identity')
        info=dict(record['job'])
        info['books']=tuple(info['books']);info['markets']=tuple(info['markets'])
        job=Job(**info)
        # Replay previously purchased six-book captures exactly as acquired.
        # New claims require the complete current group; retained captures keep original scope.
        validation = job
        if job.kind in ('main','additional') and job.group == 'standard' and job.books in (BASE_STANDARD, LEGACY_STANDARD):
            validation = replace(job, books=STANDARD)
        elif job.group == 'exchange' and job.books == LEGACY_EXCHANGE:
            validation = replace(job, books=EXCHANGE)
        validation.validate()
        if job.kind not in ('main','additional'):raise ValueError('Main publisher cannot publish props')
        raw=json.dumps(record['events'],separators=(',',':')).encode()
        folder=self.root/token
        manifest={'format':'corner.board_capture/1','sport':job.sport,'http_status':200,
                  'received_at':record['captured_at'],'requested_at':record['captured_at'],
                  'sha256':hashlib.sha256(raw).hexdigest(),
                  'endpoint':f'https://api.the-odds-api.com/v4/sports/{job.sport}/' + (f'events/{job.event_id}/odds' if job.kind == 'additional' else 'odds'),
                  'parameters':{'bookmakers':','.join(job.books),'markets':','.join(job.markets)},
                  'scheduled_reservation':token,'production_authorized':False}
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        folder.mkdir(exist_ok=True,mode=0o700)
        manifest_path=folder/'manifest.json';body_path=folder/'response.body'
        if body_path.exists() and body_path.read_bytes()!=raw:
            raise ValueError('Retained publication payload changed')
        if manifest_path.exists() and json.loads(manifest_path.read_text())!=manifest:
            raise ValueError('Retained publication manifest changed')
        self._atomic(body_path,raw)
        self._atomic(manifest_path,(json.dumps(manifest,sort_keys=True)+'\n').encode())
        # Existing ingest detects matching payload digest/time before writing again.
        self.ingest(folder,connect=self.connect)

    @staticmethod
    def _atomic(path,body):
        fd,name=tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
        try:
            with os.fdopen(fd,'wb') as stream:
                stream.write(body);stream.flush();os.fsync(stream.fileno())
            os.replace(name,path)
        finally:
            if os.path.exists(name):os.unlink(name)


def read_props(path,now=None,*,research=False):
    """Read unexpired per-book scopes, normalize once, never mutate a shared JSON file."""
    from corner.prop_markets import market_meta,normalize_event
    path=Path(path)
    if 'simulation' in path.name.lower():
        raise ValueError('Simulation snapshots cannot be published into member feeds')
    now=aware(now or datetime.now(timezone.utc))
    if not path.exists():return {'events':{}}
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=3)
    try:
        def stream(sql,parameters):
            from itertools import chain
            cursor=db.execute(sql,parameters)
            first=cursor.fetchone()
            return chain((first,),cursor) if first is not None else None
        if research:
            newest=db.execute("SELECT max(starts_at) FROM snapshots WHERE kind='props'").fetchone()[0]
            floor=min(now.timestamp(),newest)-30*86400 if newest is not None else now.timestamp()
            rows=stream("SELECT sport,event_id,captured_at,payload,expires_at FROM snapshots WHERE kind='props' AND starts_at>=? ORDER BY sport,event_id,market,book",(floor,))
        else:
            rows=stream("SELECT sport,event_id,captured_at,payload,expires_at FROM snapshots WHERE kind='props' AND expires_at>? AND starts_at>? ORDER BY sport,event_id,market,book",(now.timestamp(),now.timestamp()))
        if research and not rows and db.execute("SELECT 1 FROM sqlite_master WHERE name='clv_scopes'").fetchone():
            newest=db.execute("SELECT max(starts_at) FROM clv_scopes WHERE kind='props'").fetchone()[0]
            if newest is not None:
                floor=min(now.timestamp(),newest)-30*86400
                # Bootstrap after scope withdrawal from the last retained nonempty
                # capture. Archived records are research-only, never current offers.
                rows=stream("""SELECT c.sport,c.event_id,c.captured_at,c.payload,min(c.expires_at,?)
                    FROM clv_scopes c WHERE c.kind='props' AND c.starts_at>=?
                    AND json_array_length(c.payload,'$.market.outcomes')>0
                    AND c.captured_at=(SELECT max(n.captured_at) FROM clv_scopes n
                        WHERE n.kind=c.kind AND n.sport=c.sport AND n.event_id=c.event_id
                        AND n.book=c.book AND n.market=c.market
                        AND json_array_length(n.payload,'$.market.outcomes')>0)
                    ORDER BY c.sport,c.event_id,c.market,c.book""",(now.timestamp(),floor))
        data={'events':{}}
        for sport,event_id,captured,payload,expires in rows or ():
            if sport in NO_SCHEDULED_PROPS:
                continue
            try:
                part=json.loads(payload);market=part['market'];book=part['book'];event=part['event']
                meta=market_meta(sport,market['key'])
                if not meta:raise ValueError('Unsupported stored market')
                quotes=normalize_event({**event,'bookmakers':[{**book,'markets':[market]}]},market['key'],meta)
            except (ValueError,KeyError,TypeError):
                if research:continue
                raise
            if not quotes:continue
            if research:
                for quote in quotes:quote['_research_active']=expires>now.timestamp()
            slot=data['events'].setdefault(event_id,{
                'sport_key':sport,'home_team':event.get('home_team',''),
                'away_team':event.get('away_team',''),'commence_time':event['commence_time'],
                'markets':{}})
            stamp=datetime.fromtimestamp(captured,timezone.utc).isoformat()
            stored=slot['markets'].setdefault(market['key'],{'captured_at':stamp,'quotes':[]})
            # Each quote retains its own provider updated_at. The enclosing capture
            # age uses the oldest included scope, not the newest group's time.
            stored['captured_at']=min(stored['captured_at'],stamp)
            stored['quotes'].extend(quotes)
        return data
    finally:db.close()
