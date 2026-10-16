"""Guarded Odds API transport. Importing this module never performs network I/O.

Default disabled. Before live use, explicitly authorize the worker and verify its
book grouping. The transport requires an inflight governor reservation for odds.
"""
from datetime import datetime, timedelta, timezone
import json
import re
import time

import requests

from corner.collection_policy import SPORTS, aware, open_now, parse, supported
from corner.credit_governor import Refused

BASE='https://api.the-odds-api.com/v4/sports'
EARLIEST=parse('2026-10-19T00:00:00-05:00')
SAFE=re.compile(r'^[A-Za-z0-9_-]{1,150}$')
HEADERS={'x-requests-last','x-requests-used','x-requests-remaining','date'}


class Provider:
    def __init__(self,*,key='',enabled=False,exchange_verified=False,session=None,clock=None):
        self.key=key
        self.enabled=enabled
        self.exchange_verified=exchange_verified
        self.session=session or requests.Session()
        self.session.trust_env=False
        self.clock=clock or (lambda:datetime.now(timezone.utc))

    def close(self):self.session.close()

    def gate(self):
        now=aware(self.clock())
        if not self.enabled or not self.key:
            raise Refused('Live collection is not explicitly enabled')
        if now<EARLIEST: raise Refused('No provider requests before October 19')
        if not open_now(now): raise Refused('After Hours: no provider requests')
        return now

    def _get(self,path,params):
        self.gate()
        start=time.monotonic()
        try:
            with self.session.get(BASE+path,params={**params,'apiKey':self.key},
                                  timeout=(5,20),allow_redirects=False,stream=True,
                                  verify=True) as response:
                headers={k.lower():str(v) for k,v in response.headers.items() if k.lower() in HEADERS}
                chunks=[];size=0
                for chunk in response.iter_content(65536):
                    size+=len(chunk)
                    if size>10*1024*1024 or time.monotonic()-start>40:
                        raise ValueError('Provider response limit reached')
                    chunks.append(chunk)
                raw=b''.join(chunks)
                if self.key.encode() in raw or self.key in json.dumps(headers):
                    raise ValueError('Provider credential echo refused')
                status=response.status_code
                if status!=200:
                    return status,[],headers
                return status,json.loads(raw),headers
        except (requests.RequestException,ValueError,TypeError):
            # Neither exception text nor request URLs are safe to log with apiKey.
            raise RuntimeError('Provider response failed validation; no automatic retry.') from None

    def odds(self,governor,job,token,owner):
        job.validate();now=self.gate()
        if not SAFE.fullmatch(job.sport) or job.event_id and not SAFE.fullmatch(job.event_id):
            raise Refused('Invalid provider path identity')
        if job.group=='exchange' and not self.exchange_verified:
            raise Refused('Exchange classification/cadence needs verification')
        # Reservations are one dispatch only, not a reusable permit.
        with governor.transaction() as db:
            governor._fence(db,owner,now.timestamp())
            row=db.execute("SELECT * FROM attempts WHERE token=? AND job_key=? AND owner=? AND state='inflight'",(token,job.key,owner)).fetchone()
            if not row: raise Refused('No inflight credit reservation')
            if row['cycle_id'].startswith('simulation-') or 'simulation' in governor.path.name.lower():
                raise Refused('Simulation accounting cannot authorize live provider calls')
            if db.execute('SELECT 1 FROM dispatches WHERE token=?',(token,)).fetchone():
                raise Refused('Reservation was already dispatched')
            if not db.execute('SELECT 1 FROM cycles WHERE id=? AND starts<=? AND ends>?',(row['cycle_id'],now.timestamp(),now.timestamp())).fetchone():
                raise Refused('Reservation is outside its provider billing cycle')
            if now.timestamp()-row['started']>5:
                raise Refused('Reservation is too old to dispatch; reconcile it')
            if job.starts_at and parse(job.starts_at)<=now:
                raise Refused('Event started before dispatch')
            if db.execute('SELECT paused FROM controls WHERE id=1').fetchone()[0]:
                raise Refused('Collection is paused')
            db.execute('INSERT INTO dispatches VALUES(?,?)',(token,now.timestamp()))
            # Cadence is measured from actual dispatch authorization, not queue time.
            delta=now.timestamp()-row['started']
            db.execute('UPDATE jobs SET last_started=?,next_due=next_due+? WHERE key=?',(now.timestamp(),delta,job.key))
        params={'bookmakers':','.join(job.books),'markets':','.join(job.markets),
                'oddsFormat':'decimal','dateFormat':'iso','includeLinks':'true','includeSids':'true'}
        if job.kind=='main':
            path=f'/{job.sport}/odds'
            params.update(commenceTimeFrom=now.strftime('%Y-%m-%dT%H:%M:%SZ'),
                          commenceTimeTo=(now+timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%SZ'))
        else:path=f'/{job.sport}/events/{job.event_id}/odds'
        status,data,headers=self._get(path,params)
        if status==200:
            if job.kind=='props':
                if not isinstance(data,dict):raise RuntimeError('Invalid event odds envelope')
                data=[data]
            if not isinstance(data,list):raise RuntimeError('Invalid odds envelope')
        return status,data,headers,aware(self.clock())

    def discover(self):
        """Documented zero-credit sports/events endpoints; no paid market discovery.

        Returns a complete inventory only if every configured active league succeeds.
        Caller must persist it with its timestamp and handle expiration/backoff.
        """
        now=self.gate()
        status,catalog,headers=self._get('/',{})
        self._free_response(status,headers)
        if not isinstance(catalog,list):raise RuntimeError('Invalid sports inventory')
        keys=sorted({s['key'] for s in catalog if s.get('active') and not s.get('has_outrights')
                     and isinstance(s.get('key'),str) and supported(s['key'])
                     and s['key'] not in ('tennis_atp','tennis_wta')})
        events=[]
        for key in keys:
            if not SAFE.fullmatch(key):raise RuntimeError('Invalid sport identity')
            code,data,h=self._get(f'/{key}/events',{'dateFormat':'iso'})
            self._free_response(code,h)
            if not isinstance(data,list):raise RuntimeError('Invalid events inventory')
            for event in data:
                if event.get('sport_key')!=key or not isinstance(event.get('id'),str) or not SAFE.fullmatch(event['id']):
                    raise RuntimeError('Invalid event identity')
                start=parse(event['commence_time'])
                if now<start<=now+timedelta(hours=24):events.append(event)
        return {'active_sport_keys':keys,'events':events,'discovered_at':aware(self.clock()).isoformat()}

    @staticmethod
    def _free_response(status,headers):
        if status!=200 or headers.get('x-requests-last')!='0':
            raise RuntimeError('Inventory request failed or did not confirm zero charge; stop discovery')
