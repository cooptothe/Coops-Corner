"""Owner-authorized odds retention. Root CLI; no provider/network requests."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import time
import uuid

BASE=Path('/srv/corner')
TOKEN=re.compile(r'[a-f0-9]{48}\Z')
UNITS=('corner-collection-recovery.timer','corner-collection-recovery.service',
       'corner-live-odds.timer','corner-live-odds.service','corner-collection.service',
       'corner-backup.timer','corner-backup.service','corner-trends.timer','corner-trends.service',
       'corner-staging-accounts.service','corner-staging-api.service')

def emit(step,**fields):print(json.dumps(dict(step=step,**fields)),flush=True)
def quote(name):return '"'+name.replace('"','""')+'"'
@contextlib.contextmanager
def ro(path):
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=30)
    try:yield db
    finally:db.close()
def regular(path):
    if path.is_symlink() or not path.is_file():raise RuntimeError('Expected existing regular private file: '+path.name)
    return path
def stable_order(db,table,schema='main'):
    definition=db.execute('SELECT sql FROM '+quote(schema)+'.sqlite_master WHERE name=?',(table,)).fetchone()[0]
    if 'WITHOUT ROWID' not in definition.upper():return 'rowid'
    columns=db.execute('PRAGMA '+quote(schema)+'.table_info('+quote(table)+')').fetchall()
    return ','.join(quote(r[1]) for r in sorted(columns,key=lambda r:r[5]) if r[5])

def logical_hash(db,table,schema='main'):

    digest=hashlib.sha256();count=0
    for row in db.execute('SELECT * FROM '+quote(schema)+'.'+quote(table)+' ORDER BY '+stable_order(db,table,schema)):
        digest.update(repr(tuple(row)).encode());digest.update(b'\n');count+=1
    return count,digest.hexdigest()

def logged_refs(tracker):
    ids=set();pairs=set()
    def visit(ref):
        if not isinstance(ref,dict):return
        for key in ('game_id','event_id','source_event_id','provider_event_id'):
            value=ref.get(key)
            if isinstance(value,str) and value:
                value=value.removeprefix('prop:');ids.add(value)
                if ref.get('prop_market'):pairs.add((value,ref['prop_market']))
                else:pairs.add((value,'*'))
        if isinstance(ref.get('ref'),dict):visit(ref['ref'])
    with ro(regular(tracker)) as db:
        columns={r[1] for r in db.execute('PRAGMA table_info(bets)')}
        legs='parlay_legs' if 'parlay_legs' in columns else "'[]'"
        count=0
        for ref,children in db.execute('SELECT ref,'+legs+' FROM bets'):
            visit(json.loads(ref or '{}'))
            for child in json.loads(children or '[]'):visit(child)
            count+=1
    return ids,pairs,count

def compact(state,tracker,receipts,now):
    """Build and verify a smaller replacement; original is untouched until rename."""
    regular(state);regular(tracker)
    if receipts.is_symlink():raise RuntimeError('Receipt directory symlink refused')
    receipts.mkdir(parents=True,exist_ok=True,mode=0o700)
    ids,pairs,bets=logged_refs(tracker)
    with ro(tracker) as account:
        account_hash={t:logical_hash(account,t) for t in ('users','bets','cash')}
        backup=receipts/('accounts-'+hashlib.sha256(repr(account_hash).encode()).hexdigest()[:32]+'.sqlite3')
        if not backup.exists():
            with contextlib.closing(sqlite3.connect(backup)) as dst:account.backup(dst)
            os.chmod(backup,0o600)
        with ro(regular(backup)) as saved:
            if saved.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or saved.execute('PRAGMA foreign_key_check').fetchone() or {t:logical_hash(saved,t) for t in account_hash}!=account_hash:
                raise RuntimeError('Account safety copy verification failed')
    with contextlib.closing(sqlite3.connect(state,timeout=30,isolation_level=None)) as source:
        result=source.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
        if result[0]:raise RuntimeError('Ledger has an active reader/writer; no replacement made')
    info=state.stat();old_size=info.st_size
    tmp=state.with_name(state.name+'.compact-'+uuid.uuid4().hex+'.tmp')
    filtered={'clv_scopes','snapshots','publication_outbox','live_captures'}
    try:
        with contextlib.closing(sqlite3.connect(tmp,isolation_level=None,uri=True)) as db:
            db.execute('PRAGMA journal_mode=DELETE');db.execute('PRAGMA synchronous=FULL')
            phase='schema';phase_started=time.monotonic();last_report=phase_started
            def enough_space():
                nonlocal last_report
                free=shutil.disk_usage(state.parent).free
                if time.monotonic()-last_report>=10:
                    emit('ledger_progress',phase=phase,elapsed_seconds=int(time.monotonic()-phase_started),free_bytes=free)
                    last_report=time.monotonic()
                return int(free<256*1024**2)
            db.set_progress_handler(enough_space,100000)
            db.execute('PRAGMA temp_store=FILE');db.execute('PRAGMA cache_size=-32768')
            db.execute('ATTACH DATABASE ? AS src',(state.resolve().as_uri()+'?mode=ro',))
            schema=db.execute("SELECT type,name,sql FROM src.sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY rowid").fetchall()
            tables=[name for kind,name,_ in schema if kind=='table']
            if any('VIRTUAL TABLE' in sql.upper() for kind,_,sql in schema if kind=='table'):
                raise RuntimeError('Unreviewed virtual table; original retained')
            for kind,_,sql in schema:
                if kind=='table':db.execute(sql)
            db.execute('CREATE TEMP TABLE protected(event_id TEXT,market TEXT,PRIMARY KEY(event_id,market))')
            db.executemany('INSERT INTO protected VALUES(?,?)',sorted(pairs))
            db.execute('CREATE TEMP TABLE keep_clv(row_id INTEGER PRIMARY KEY)')
            if 'clv_scopes' in tables:
                # Snapshots already identify the latest current capture. Probe
                # the complete CLV primary key instead of grouping all history.
                phase='current_scope_probes';emit('ledger_selection',phase=phase)
                db.execute("INSERT OR IGNORE INTO keep_clv SELECT c.rowid FROM src.snapshots AS s CROSS JOIN src.clv_scopes AS c WHERE s.starts_at>=? AND c.kind=s.kind AND c.sport=s.sport AND c.event_id=s.event_id AND c.book=s.book AND c.market=s.market AND c.captured_at=s.captured_at",(now-6*3600,))
                # A single covering-index pass reads only identity metadata,
                # never the 62 GiB payload table once per logged event.
                phase='logged_history_index_scan';emit('ledger_selection',phase=phase)
                retain="INSERT OR IGNORE INTO keep_clv SELECT c.rowid FROM src.clv_scopes AS c WHERE EXISTS(SELECT 1 FROM protected p WHERE p.event_id=c.event_id AND (p.market='*' OR p.market=c.market))"
                emit('ledger_selection_plan',plan=[row[3] for row in db.execute('EXPLAIN QUERY PLAN '+retain)])
                db.execute(retain)
            conditions={
                'clv_scopes':'rowid IN (SELECT row_id FROM keep_clv)',
                'snapshots':'starts_at>='+repr(now-6*3600)+' OR EXISTS(SELECT 1 FROM protected p WHERE p.event_id=snapshots.event_id AND (p.market=\'*\' OR p.market=snapshots.market))',
                'publication_outbox':'published_at IS NULL OR token IN (SELECT token FROM src.publication_outbox WHERE published_at IS NOT NULL ORDER BY published_at DESC LIMIT 32)',
                'live_captures':'captured>='+repr(now-300),
                'runner_inventory':'1=1',
            }
            db.execute('BEGIN')
            counts={}
            for name in tables:
                phase='copy_'+name;emit('ledger_copy_table',table=name)
                where=' WHERE '+conditions[name] if name in conditions else ''
                db.execute('INSERT INTO main.'+quote(name)+' SELECT * FROM src.'+quote(name)+where+' ORDER BY '+stable_order(db,name,'src'))
                counts[name]=db.execute('SELECT count(*) FROM main.'+quote(name)).fetchone()[0]
            if db.execute("SELECT 1 FROM src.sqlite_master WHERE name='sqlite_sequence'").fetchone():
                db.execute('DELETE FROM main.sqlite_sequence')
                db.execute('INSERT INTO main.sqlite_sequence SELECT * FROM src.sqlite_sequence')
            db.execute('COMMIT')
            phase='rebuild_indexes';emit('ledger_selection',phase=phase)
            for kind,_,sql in schema:
                if kind!='table':db.execute(sql)
            db.execute('PRAGMA user_version='+str(db.execute('PRAGMA src.user_version').fetchone()[0]))
            db.execute('PRAGMA application_id='+str(db.execute('PRAGMA src.application_id').fetchone()[0]))
            phase='verify_candidate';emit('ledger_selection',phase=phase)
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchone():
                raise RuntimeError('Replacement integrity/FK verification failed')
            # Compare every unfiltered table exactly, including all financial
            # records, unknown attempts, controls, policy, offsets and audits.
            verified={}
            for name in tables:
                if name in filtered:continue
                if logical_hash(db,name,'main')!=logical_hash(db,name,'src'):raise RuntimeError('Preserved table mismatch: '+name)
                verified[name]=logical_hash(db,name)
            db.execute('DETACH DATABASE src')
        with ro(tracker) as account:
            if {t:logical_hash(account,t) for t in account_hash}!=account_hash:
                raise RuntimeError('Accounts changed during retention; original retained')
        for suffix in ('-wal','-shm'):
            side=Path(str(state)+suffix)
            if side.exists():
                if suffix=='-wal' and side.stat().st_size:raise RuntimeError('Unexpected live WAL; original retained')
                if side.is_symlink():raise RuntimeError('Unexpected SQLite sidecar symlink')
                side.unlink()
        os.chmod(tmp,0o600)
        with tmp.open('r+b') as stream:os.fsync(stream.fileno())
        if hasattr(os,'chown'):os.chown(tmp,info.st_uid,info.st_gid)
        os.replace(tmp,state)
        if os.name=='posix':
            fd=os.open(state.parent,os.O_DIRECTORY)
            try:os.fsync(fd)
            finally:os.close(fd)
        receipt=dict(old_bytes=old_size,new_bytes=state.stat().st_size,logged_bets=bets,preserved_tables=verified,rows=counts)
        (receipts/('ledger-'+str(int(now))+'.json')).write_text(json.dumps(receipt,indent=2))
        emit('ledger_compacted',old_bytes=old_size,new_bytes=state.stat().st_size,logged_bets=bets)
        return ids
    finally:
        for candidate in (tmp,Path(str(tmp)+'-journal')):
            if candidate.exists() and not candidate.is_symlink():candidate.unlink()

def remove_published_captures(state,root):
    if root.is_symlink():raise RuntimeError('Capture root cannot be a symlink')
    removed=0
    with ro(state) as db:
        keep={r[0] for r in db.execute('SELECT token FROM publication_outbox WHERE published_at IS NOT NULL ORDER BY published_at DESC LIMIT 32')}
        for folder in root.iterdir():
            if not TOKEN.fullmatch(folder.name) or not folder.is_dir() or folder.is_symlink():continue
            row=db.execute('SELECT published_at FROM publication_outbox WHERE token=?',(folder.name,)).fetchone()
            if row is None or row[0] is None or folder.name in keep:continue
            children=list(folder.iterdir())
            if any(p.is_symlink() or p.is_dir() or p.name not in ('response.body','manifest.json') for p in children):continue
            for child in children:child.unlink()
            folder.rmdir();removed+=1
    emit('published_capture_cleanup',directories=removed)

def postgres_prune(ids):
    data=json.dumps(sorted(ids)).replace("'","''")
    sql=POSTGRES_SQL.replace('__IDS__',data)
    subprocess.run(['runuser','-u','postgres','--','/usr/bin/psql','-X','-p','5432','-d','corner_staging','-v','ON_ERROR_STOP=1','-P','pager=off'],input=sql,text=True,check=True)

POSTGRES_SQL="""
SET statement_timeout=0;
BEGIN;
CREATE TEMP TABLE storage_logged(id uuid PRIMARY KEY) ON COMMIT DROP;
INSERT INTO storage_logged
SELECT e.id FROM corner.events e WHERE e.id::text IN (SELECT value FROM jsonb_array_elements_text('__IDS__'::jsonb))
UNION SELECT event_id FROM corner.event_provider_identities WHERE external_id IN (SELECT value FROM jsonb_array_elements_text('__IDS__'::jsonb));
CREATE TEMP TABLE storage_keep_obs(id uuid PRIMARY KEY) ON COMMIT DROP;
INSERT INTO storage_keep_obs SELECT ob.id FROM corner.odds_observations ob JOIN corner.outcomes o ON o.id=ob.outcome_id JOIN corner.markets m ON m.id=o.market_id JOIN storage_logged p ON p.id=m.event_id;
CREATE TEMP TABLE storage_streams ON COMMIT DROP AS SELECT DISTINCT ob.outcome_id,ob.sportsbook_id FROM corner.odds_observations ob JOIN corner.outcomes o ON o.id=ob.outcome_id JOIN corner.markets m ON m.id=o.market_id JOIN corner.events e ON e.id=m.event_id WHERE e.scheduled_start>=now()-interval '6 hours';
CREATE TEMP TABLE storage_expected_winners ON COMMIT DROP AS SELECT s.outcome_id,s.sportsbook_id,q.observation_id FROM storage_streams s CROSS JOIN LATERAL corner.trusted_quote_for_stream(s.outcome_id,s.sportsbook_id) q;
INSERT INTO storage_keep_obs SELECT observation_id FROM storage_expected_winners ON CONFLICT DO NOTHING;
INSERT INTO storage_keep_obs SELECT q.id FROM storage_streams s CROSS JOIN LATERAL (SELECT id FROM corner.odds_observations WHERE outcome_id=s.outcome_id AND sportsbook_id=s.sportsbook_id ORDER BY observed_at DESC,id DESC LIMIT 1) q ON CONFLICT DO NOTHING;
DO $keep$
DECLARE item record;
BEGIN
 FOR item IN SELECT c.conrelid::regclass AS rel,a.attname AS col FROM pg_constraint c CROSS JOIN LATERAL unnest(c.conkey,c.confkey) pair(child,parent) JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=pair.child JOIN pg_attribute p ON p.attrelid=c.confrelid AND p.attnum=pair.parent WHERE c.contype='f' AND c.confrelid='corner.odds_observations'::regclass AND p.attname='id'
 LOOP EXECUTE format('INSERT INTO storage_keep_obs SELECT %I FROM %s WHERE %I IS NOT NULL ON CONFLICT DO NOTHING',item.col,item.rel,item.col); END LOOP;
END $keep$;
ALTER TABLE corner.odds_observations DISABLE TRIGGER odds_observations_immutable;
DELETE FROM corner.odds_observations ob WHERE NOT EXISTS(SELECT 1 FROM storage_keep_obs k WHERE k.id=ob.id);
ALTER TABLE corner.odds_observations ENABLE TRIGGER odds_observations_immutable;
DO $verify$ BEGIN
 IF EXISTS ((SELECT * FROM storage_expected_winners EXCEPT SELECT s.outcome_id,s.sportsbook_id,q.observation_id FROM storage_streams s CROSS JOIN LATERAL corner.trusted_quote_for_stream(s.outcome_id,s.sportsbook_id) q) UNION ALL (SELECT s.outcome_id,s.sportsbook_id,q.observation_id FROM storage_streams s CROSS JOIN LATERAL corner.trusted_quote_for_stream(s.outcome_id,s.sportsbook_id) q EXCEPT SELECT * FROM storage_expected_winners)) THEN RAISE EXCEPTION 'Current quote changed during retention'; END IF;
END $verify$;
CREATE TEMP TABLE storage_keep_payload(id uuid PRIMARY KEY) ON COMMIT DROP;
DO $keep$
DECLARE item record;
BEGIN
 FOR item IN SELECT c.conrelid::regclass AS rel,a.attname AS col FROM pg_constraint c CROSS JOIN LATERAL unnest(c.conkey,c.confkey) pair(child,parent) JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=pair.child JOIN pg_attribute p ON p.attrelid=c.confrelid AND p.attnum=pair.parent WHERE c.contype='f' AND c.confrelid='corner.provider_payloads'::regclass AND p.attname='id'
 LOOP EXECUTE format('INSERT INTO storage_keep_payload SELECT %I FROM %s WHERE %I IS NOT NULL ON CONFLICT DO NOTHING',item.col,item.rel,item.col); END LOOP;
END $keep$;
ALTER TABLE corner.provider_payloads DISABLE TRIGGER provider_payloads_immutable;
DELETE FROM corner.provider_payloads p WHERE NOT EXISTS(SELECT 1 FROM storage_keep_payload k WHERE k.id=p.id);
ALTER TABLE corner.provider_payloads ENABLE TRIGGER provider_payloads_immutable;
COMMIT;
VACUUM (FULL,ANALYZE) corner.odds_observations;
VACUUM (FULL,ANALYZE) corner.provider_payloads;
"""

def command(args,**kwargs):return subprocess.run(args,check=True,**kwargs)
def active(unit):return subprocess.run(['systemctl','is-active','--quiet',unit]).returncode==0
def usage(base):
    d=shutil.disk_usage(base);return dict(total=d.total,used=d.used,free=d.free,percent=round(100*d.used/d.total,2))

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply',action='store_true');parser.add_argument('--force',action='store_true');parser.add_argument('--leave-collection-stopped',action='store_true');args=parser.parse_args()
    state=BASE/'config/collection-live.sqlite3';tracker=BASE/'config/staging-tracker.sqlite3'
    before=usage(BASE);emit('disk_before',**before)
    if not args.apply:return
    if os.name!='posix' or os.geteuid()!=0:raise SystemExit('Root VPS maintenance required')
    import fcntl
    gate_dir=Path('/run/corner-storage')
    if gate_dir.is_symlink():raise RuntimeError('Maintenance run path symlink refused')
    gate_dir.mkdir(mode=0o700,exist_ok=True)
    gate_path=gate_dir/'maintenance.lock'
    if gate_path.is_symlink():raise RuntimeError('Maintenance gate symlink refused')
    gate=gate_path.open('a+b')
    try:fcntl.flock(gate,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('Storage maintenance is already running')
    regular(state);regular(tracker)
    if not args.force and before['percent']<45:return
    os.umask(0o077)
    existing=[u for u in UNITS if active(u)]
    loaded=[u for u in UNITS if subprocess.run(['systemctl','show','-p','LoadState','--value',u],capture_output=True,text=True).stdout.strip()=='loaded']
    success=False
    try:
        command(['systemctl','stop',*loaded])
        import fcntl
        with contextlib.ExitStack() as stack:
            for name in ('collection-repair.lock','collection-maintenance.lock'):
                path=BASE/'config'/name
                if path.is_symlink():raise RuntimeError('Lock symlink refused')
                lock=stack.enter_context(path.open('a+b'))
                owner=state.stat();os.fchown(lock.fileno(),owner.st_uid,owner.st_gid);os.fchmod(lock.fileno(),0o600)
                deadline=time.monotonic()+30
                while True:
                    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);break
                    except BlockingIOError:
                        if time.monotonic()>deadline:raise RuntimeError('Maintenance lock busy; no cleanup performed')
                        time.sleep(.2)
            remove_published_captures(state,BASE/'collection')
            ids=compact(state,tracker,BASE/'backups/storage-account-checkpoints',time.time())
            postgres_prune(ids)
        command(['journalctl','--vacuum-size=100M'])
        after=usage(BASE);emit('disk_after',**after)
        success=after['percent']<50
        if not success:raise RuntimeError('Protected data still exceeds 50%; collector remains stopped. No accounts or completed backups deleted.')
    finally:
        # Restore serving components even on a failure; the original ledger is
        # retained unless its compact replacement already passed all checks.
        serve=[u for u in existing if (u.startswith('corner-staging-') or u=='corner-trends.timer')]
        if serve:subprocess.run(['systemctl','start',*serve],check=False)
        if success:
            if not args.leave_collection_stopped and 'corner-collection.service' in existing:
                command(['/bin/bash',str(BASE/'app/deploy/repair-collection.sh')])
            timers=[u for u in existing if u.endswith('.timer') and u not in serve and (not args.leave_collection_stopped or u=='corner-backup.timer')]
            if timers:command(['systemctl','start',*timers])
    emit('storage_cleanup_passed',target_percent=50,completed_backups='preserved',provider_calls_by_cleanup=0)

if __name__=='__main__':main()
