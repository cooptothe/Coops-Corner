"""Back up private account data, preserve invite codes, and apply permanent-link policy."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from corner.tracker_store import TrackerStore

def fingerprint(db,table,columns='*'):
    h=hashlib.sha256();n=0
    for row in db.execute(f'SELECT {columns} FROM {table} ORDER BY rowid'):
        h.update(repr(tuple(row)).encode());h.update(b'\n');n+=1
    return n,h.hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',default='/srv/corner/config/staging-tracker.sqlite3')
    parser.add_argument('--backup-dir',default='/srv/corner/backups/invitation-policy')
    args=parser.parse_args();os.umask(0o077)
    path=Path(args.db)
    if path.is_symlink() or not path.is_file():raise SystemExit('Existing private account database required')
    folder=Path(args.backup_dir);folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    target=folder/('before-permanent-invites-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]+'.sqlite3')
    tables=('users','bets','cash','beta_members')
    invite_columns='id,token_hash,username_key,expires_at,revoked,redeemed_by,access_kind,evidence,created_at,cohort'
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as source:
        before={t:fingerprint(source,t) for t in tables}
        invites=fingerprint(source,'beta_invites',invite_columns)
        with closing(sqlite3.connect(target)) as backup:
            source.backup(backup)
            if backup.execute('PRAGMA main.integrity_check').fetchone()[0]!='ok':raise RuntimeError('Account backup verification failed')
    os.chmod(target,0o600)
    store=TrackerStore(path)
    try:
        db=store._db
        if before!={t:fingerprint(db,t) for t in tables} or invites!=fingerprint(db,'beta_invites',invite_columns):
            raise RuntimeError('Unexpected account or invitation change; preserve backup and review')
        unused=db.execute('SELECT count(*) FROM beta_invites WHERE revoked=0 AND redeemed_by IS NULL AND non_expiring=1').fetchone()[0]
        print(json.dumps(dict(result='invitation_policy_applied',non_expiring_unused_codes=unused,same_codes=True,accounts_and_logged_bets_preserved=True,backup=str(target))))
    finally:store.close()

if __name__=='__main__':main()
