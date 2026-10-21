"""Durable reservations, cadence, fencing and isolated snapshots for collection.

No HTTP adapter is present. Unknown charges stay reserved; uncertain jobs block
until operator reconciliation. A stale process cannot publish after lease loss.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from dataclasses import asdict
import json
from pathlib import Path
import secrets
import sqlite3

from corner.collection_policy import CENTRAL, POOLS, TOTAL, PROTECTED, aware, interval, open_now, parse, snapshot_max_age, additional_limits


class Refused(ValueError):
    pass


class Governor:
    def __init__(self,path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(str(path),isolation_level=None,timeout=10)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS cycles (
          id TEXT PRIMARY KEY, starts REAL NOT NULL, ends REAL NOT NULL,
          CHECK(ends>starts));
        CREATE TABLE IF NOT EXISTS lease (
          id INTEGER PRIMARY KEY CHECK(id=1), owner TEXT NOT NULL, until_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS controls (
          id INTEGER PRIMARY KEY CHECK(id=1), paused TEXT NOT NULL DEFAULT '');
        INSERT OR IGNORE INTO controls(id) VALUES(1);
        CREATE TABLE IF NOT EXISTS jobs (
          key TEXT PRIMARY KEY, next_due REAL NOT NULL, state TEXT NOT NULL,
          last_started REAL NOT NULL, last_error TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS attempts (
          token TEXT PRIMARY KEY, job_key TEXT NOT NULL REFERENCES jobs(key),
          cycle_id TEXT NOT NULL REFERENCES cycles(id), pool TEXT NOT NULL,
          reserved INTEGER NOT NULL CHECK(reserved>=0), actual INTEGER,
          state TEXT NOT NULL CHECK(state IN ('inflight','settled','unknown')),
          owner TEXT NOT NULL, started REAL NOT NULL, finished REAL,
          CHECK(actual IS NULL OR actual>=0));
        CREATE TABLE IF NOT EXISTS snapshots (
          kind TEXT NOT NULL, sport TEXT NOT NULL, event_id TEXT NOT NULL,
          book TEXT NOT NULL, market TEXT NOT NULL, starts_at REAL NOT NULL,
          source_at REAL NOT NULL, captured_at REAL NOT NULL,
          expires_at REAL NOT NULL, payload TEXT NOT NULL,
          PRIMARY KEY(kind,sport,event_id,book,market));
        CREATE TABLE IF NOT EXISTS clv_scopes (
          kind TEXT, sport TEXT, event_id TEXT, book TEXT, market TEXT, starts_at REAL,
          source_at REAL, captured_at REAL, expires_at REAL, payload TEXT,
          PRIMARY KEY(kind,sport,event_id,book,market,captured_at));
        CREATE TABLE IF NOT EXISTS dispatches (
          token TEXT PRIMARY KEY REFERENCES attempts(token), authorized_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS publication_outbox (
          token TEXT PRIMARY KEY REFERENCES attempts(token), payload TEXT NOT NULL,
          published_at REAL);
        CREATE TABLE IF NOT EXISTS additional_events(day TEXT NOT NULL, sport TEXT NOT NULL, event_id TEXT NOT NULL, PRIMARY KEY(day,sport,event_id));
        CREATE TABLE IF NOT EXISTS additional_attempts(token TEXT PRIMARY KEY REFERENCES attempts(token), day TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS collection_live_snapshots
          ON snapshots(kind,expires_at,starts_at);
        ''')

    def close(self): self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield self.db
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def configure_cycle(self,cycle_id,starts,ends):
        """Explicit provider billing period, not an automatic calendar-month reset."""
        starts=aware(starts).timestamp();ends=aware(ends).timestamp()
        if ends<=starts: raise ValueError('Invalid billing cycle')
        with self.transaction() as db:
            old=db.execute('SELECT * FROM cycles WHERE id=?',(cycle_id,)).fetchone()
            if old:
                if (old['starts'],old['ends'])!=(starts,ends): raise Refused('Existing billing period cannot change')
                return
            if db.execute('SELECT 1 FROM cycles WHERE starts<? AND ends>?',(ends,starts)).fetchone():
                raise Refused('Billing periods cannot overlap')
            db.execute('INSERT INTO cycles VALUES(?,?,?)',(cycle_id,starts,ends))

    def acquire(self,owner,now,seconds=120):
        stamp=aware(now).timestamp()
        if not owner or not 60<=seconds<=300: raise ValueError('Invalid worker lease')
        with self.transaction() as db:
            row=db.execute('SELECT * FROM lease WHERE id=1').fetchone()
            if row and row['until_at']>stamp and row['owner']!=owner:
                return False
            if row and row['until_at']<=stamp:
                # Crash recovery never refunds an unconfirmed provider request.
                db.execute("UPDATE jobs SET state='blocked',last_error='unknown prior request' WHERE key IN (SELECT job_key FROM attempts WHERE state='inflight')")
                db.execute("UPDATE attempts SET state='unknown' WHERE state='inflight'")
            db.execute('INSERT INTO lease VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET owner=excluded.owner,until_at=excluded.until_at',(owner,stamp+seconds))
            return True

    def _fence(self,db,owner,stamp):
        if not db.execute('SELECT 1 FROM lease WHERE id=1 AND owner=? AND until_at>?',(owner,stamp)).fetchone():
            raise Refused('Worker lease lost')

    def release(self,owner):
        with self.transaction() as db:
            if db.execute("SELECT 1 FROM attempts WHERE owner=? AND state='inflight'",(owner,)).fetchone():
                raise Refused('Unresolved request; lease must expire conservatively')
            db.execute('UPDATE lease SET until_at=0 WHERE id=1 AND owner=?',(owner,))

    def claim(self,job,owner,now):
        job.validate();now=aware(now);stamp=now.timestamp()
        if not open_now(now): raise Refused('After Hours: no collection')
        if job.starts_at and not now < parse(job.starts_at): raise Refused('Event started')
        if job.starts_at and parse(job.starts_at)>now+timedelta(hours=24): raise Refused('Event outside 24-hour horizon')
        period=interval(job.kind,job.group,now,parse(job.starts_at) if job.starts_at else None)
        with self.transaction() as db:
            self._fence(db,owner,stamp)
            pause=db.execute('SELECT paused FROM controls WHERE id=1').fetchone()[0]
            if pause: raise Refused(pause)
            cycle=db.execute('SELECT id,starts,ends FROM cycles WHERE starts<=? AND ends>?',(stamp,stamp)).fetchone()
            if not cycle: raise Refused('No explicit billing cycle covers this time')
            prior=db.execute('SELECT * FROM jobs WHERE key=?',(job.key,)).fetchone()
            if prior and (prior['state'] in ('inflight','blocked') or prior['next_due']>stamp):
                raise Refused('Job already reserved, blocked or not due')
            # Coarse due bands must accelerate on entering a nearer-start band.
            # ready() adjusts due times using the last dispatch, never replaying missed ticks.
            day = now.astimezone(CENTRAL).date().isoformat()
            if job.kind == 'additional':
                if parse(job.starts_at) > now + timedelta(hours=2):
                    raise Refused('Additional markets only in final two pregame hours')
                event_limit, credit_limit = additional_limits(
                    datetime.fromtimestamp(cycle['starts'],timezone.utc),
                    datetime.fromtimestamp(cycle['ends'],timezone.utc))
                known = db.execute('SELECT 1 FROM additional_events WHERE day=? AND sport=? AND event_id=?',(day,job.sport,job.event_id)).fetchone()
                if not known and db.execute('SELECT count(*) FROM additional_events WHERE day=?',(day,)).fetchone()[0] >= event_limit:
                    raise Refused('Additional-market daily event cap')
                used = db.execute('SELECT coalesce(sum(coalesce(a.actual,a.reserved)),0) FROM attempts a JOIN additional_attempts x ON x.token=a.token WHERE x.day=?',(day,)).fetchone()[0]
                if used + job.cost > credit_limit:
                    raise Refused('Additional-market daily credit cap')
            sums=self.accounted(db,cycle[0])
            if sums.get(job.pool,0)+job.cost>POOLS[job.pool]: raise Refused('Pool limit')
            if sum(sums.values())+job.cost>TOTAL-PROTECTED: raise Refused('Protected reserve')
            token=secrets.token_hex(24)
            db.execute("INSERT INTO jobs(key,next_due,state,last_started) VALUES(?,?,'inflight',?) ON CONFLICT(key) DO UPDATE SET next_due=excluded.next_due,state='inflight',last_started=excluded.last_started,last_error=''",(job.key,stamp+period,stamp))
            db.execute("INSERT INTO attempts(token,job_key,cycle_id,pool,reserved,state,owner,started) VALUES(?,?,?,?,?,'inflight',?,?)",(token,job.key,cycle[0],job.pool,job.cost,owner,stamp))
            if job.kind == 'additional':
                db.execute('INSERT OR IGNORE INTO additional_events VALUES(?,?,?)',(day,job.sport,job.event_id))
                db.execute('INSERT INTO additional_attempts VALUES(?,?)',(token,day))
            return token

    def ready(self,job,now):
        job.validate()
        now=aware(now)
        if not open_now(now) or job.starts_at and parse(job.starts_at)<=now: return False
        period=interval(job.kind,job.group,now,parse(job.starts_at) if job.starts_at else None)
        row=self.db.execute('SELECT * FROM jobs WHERE key=?',(job.key,)).fetchone()
        return not row or row['state']=='idle' and row['last_started']+period<=now.timestamp()

    def prepare_due(self,job,owner,now):
        """Adjust cadence band under the lease, preserving last-start floors."""
        job.validate();now=aware(now)
        period=interval(job.kind,job.group,now,parse(job.starts_at) if job.starts_at else None)
        with self.transaction() as db:
            self._fence(db,owner,now.timestamp())
            db.execute("UPDATE jobs SET next_due=last_started+? WHERE key=? AND state='idle'",(period,job.key))

    def finish(self,job,token,owner,now,headers,payload,status=200):
        """Reconcile even a failed/empty response; publish only validated successful scopes."""
        now=aware(now);stamp=now.timestamp()
        raw=headers.get('x-requests-last')
        actual=int(raw) if isinstance(raw,(str,int)) and str(raw).isdigit() else None
        remaining=headers.get('x-requests-remaining')
        remaining=int(remaining) if isinstance(remaining,(str,int)) and str(remaining).isdigit() else None
        with self.transaction() as db:
            self._fence(db,owner,stamp)
            attempt=db.execute("SELECT * FROM attempts WHERE token=? AND owner=? AND state='inflight'",(token,owner)).fetchone()
            if not attempt or attempt['job_key']!=job.key: raise Refused('Unknown/completed reservation')
            if actual is None:
                db.execute("UPDATE attempts SET state='unknown',finished=? WHERE token=?",(stamp,token))
                db.execute("UPDATE jobs SET state='blocked',last_error='missing charge header' WHERE key=?",(job.key,))
                return 'unknown'
            db.execute("UPDATE attempts SET state='settled',actual=?,finished=? WHERE token=?",(actual,stamp,token))
            reason=''
            if actual>attempt['reserved']: reason='Provider charge exceeded reservation'
            elif remaining is None: reason='Missing provider remaining header'
            elif remaining<PROTECTED: reason='Provider quota reached protected reserve'
            elif status!=200: reason=f'Provider HTTP {status}; operator review required'
            if reason:
                db.execute('UPDATE controls SET paused=? WHERE id=1',(reason,))
                db.execute("UPDATE jobs SET state='blocked',last_error=? WHERE key=?",(reason,job.key))
                return 'paused'
            self._publish(db,job,payload,now)
            if job.kind in ('main','additional'):
                db.execute('INSERT INTO publication_outbox(token,payload) VALUES(?,?)',
                           (token,json.dumps({'job':asdict(job),'events':payload,'captured_at':now.isoformat(),
                                              'simulation':attempt['cycle_id'].startswith('simulation-') or 'simulation' in self.path.name.lower()},separators=(',',':'))))
            db.execute("UPDATE jobs SET state='idle',last_error='' WHERE key=?",(job.key,))
            return 'published'

    def unknown(self,token,owner,now):
        with self.transaction() as db:
            self._fence(db,owner,aware(now).timestamp())
            row=db.execute("SELECT job_key FROM attempts WHERE token=? AND owner=? AND state='inflight'",(token,owner)).fetchone()
            if not row: raise Refused('Unknown reservation')
            db.execute("UPDATE attempts SET state='unknown',finished=? WHERE token=?",(aware(now).timestamp(),token))
            db.execute("UPDATE jobs SET state='blocked',last_error='uncertain provider result' WHERE key=?",(row[0],))

    def _publish(self,db,job,payload,now):
        if not isinstance(payload,list): raise ValueError('Expected event list')
        rows=[];nowstamp=now.timestamp()
        for event in payload:
            if event.get('sport_key')!=job.sport or not isinstance(event.get('id'),str): raise ValueError('Mismatched event')
            if job.event_id and event['id']!=job.event_id: raise ValueError('Mismatched props event')
            start=parse(event['commence_time'])
            if start<=now: continue
            for book in event.get('bookmakers',[]):
                if book['key'] not in job.books: raise ValueError('Unexpected bookmaker')
                for market in book.get('markets',[]):
                    if market['key'] not in job.markets: raise ValueError('Unexpected market')
                    source=parse(market.get('last_update') or book['last_update'])
                    if source.timestamp()>nowstamp+5: raise ValueError('Future provider timestamp')
                    # Actionable snapshots always expire at strict source-band limits,
                    # even when distant polling deliberately runs less frequently.
                    maxage=snapshot_max_age(job.kind, job.group)
                    expiry=min(start.timestamp(),source.timestamp()+maxage,nowstamp+maxage)
                    rows.append((job.kind,job.sport,event['id'],book['key'],market['key'],start.timestamp(),source.timestamp(),nowstamp,expiry,json.dumps({'event':{k:v for k,v in event.items() if k!='bookmakers'},'book':{k:v for k,v in book.items() if k!='markets'},'market':market},separators=(',',':'))))
        # Exact request scope only. Never delete another book group/event/market.
        for book in job.books:
            for market in job.markets:
                # A missing scope is a withdrawal, not permission to reuse its old close.
                previous = db.execute('SELECT * FROM snapshots WHERE kind=? AND sport=? AND book=? AND market=?', (job.kind,job.sport,book,market)).fetchall()
                present = {(r[2],r[3],r[4]) for r in rows}
                for prior in previous:
                    if job.event_id and prior['event_id'] != job.event_id:
                        continue
                    if (prior['event_id'],book,market) in present or prior['starts_at'] <= nowstamp:
                        continue
                    part=json.loads(prior['payload'])
                    part['market']['outcomes']=[]
                    part['market']['last_update']=now.isoformat()
                    tombstone=(job.kind,job.sport,prior['event_id'],book,market,prior['starts_at'],nowstamp,nowstamp,nowstamp,json.dumps(part,separators=(',',':')))
                    db.execute('INSERT OR IGNORE INTO clv_scopes VALUES(?,?,?,?,?,?,?,?,?,?)',tombstone)
                if job.event_id:
                    db.execute('DELETE FROM snapshots WHERE kind=? AND sport=? AND event_id=? AND book=? AND market=?',(job.kind,job.sport,job.event_id,book,market))
                else:
                    db.execute('DELETE FROM snapshots WHERE kind=? AND sport=? AND book=? AND market=?',(job.kind,job.sport,book,market))
        db.executemany('INSERT INTO snapshots VALUES(?,?,?,?,?,?,?,?,?,?)',rows)
        db.executemany('INSERT OR IGNORE INTO clv_scopes VALUES(?,?,?,?,?,?,?,?,?,?)',rows)

    def snapshots(self,now):
        stamp=aware(now).timestamp()
        return [json.loads(row[0]) for row in self.db.execute('SELECT payload FROM snapshots WHERE expires_at>? AND starts_at>? ORDER BY kind,sport,event_id,book,market',(stamp,stamp))]

    def publish_pending(self,owner,now,publish):
        """Publisher must be idempotent across DB commit / outbox acknowledgement crashes."""
        self._fence(self.db,owner,aware(now).timestamp())
        count=0
        for row in self.db.execute('SELECT token,payload FROM publication_outbox WHERE published_at IS NULL ORDER BY rowid').fetchall():
            self._fence(self.db,owner,aware(now).timestamp())
            publish(row['token'],json.loads(row['payload']))
            with self.transaction() as db:
                self._fence(db,owner,aware(now).timestamp())
                db.execute('UPDATE publication_outbox SET published_at=? WHERE token=? AND published_at IS NULL',(aware(now).timestamp(),row['token']))
            count+=1
        return count

    def accounted(self,db,cycle_id):
        return dict(db.execute('SELECT pool,sum(coalesce(actual,reserved)) FROM attempts WHERE cycle_id=? GROUP BY pool',(cycle_id,)).fetchall())

    def status(self):
        cycles=[]
        for cycle in self.db.execute('SELECT * FROM cycles ORDER BY starts'):
            amounts=self.accounted(self.db,cycle['id'])
            cycles.append({'id':cycle['id'],'accounted':amounts,'remaining_pools':{k:v-amounts.get(k,0) for k,v in POOLS.items()}})
        return {'cycles':cycles,'paused':self.db.execute('SELECT paused FROM controls WHERE id=1').fetchone()[0],
                'unknown_attempts':self.db.execute("SELECT count(*) FROM attempts WHERE state='unknown'").fetchone()[0],
                'snapshot_count':self.db.execute('SELECT count(*) FROM snapshots').fetchone()[0]}
