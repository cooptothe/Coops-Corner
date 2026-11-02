"""Local authenticated GET-only feed check. No credentials or tokens are printed."""
import json
import os
import sqlite3
import time
from pathlib import Path
from contextlib import closing
from dotenv import dotenv_values
import requests

def main():
    for key,value in dotenv_values('/srv/corner/config/staging.env').items():
        if value is not None:os.environ[key]=value
    from corner import auth
    from pipelines.accounts import DB_PATH,SECRET_PATH
    session=None
    try:
        with closing(sqlite3.connect(DB_PATH.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            row=db.execute("SELECT id,username,session_epoch FROM users WHERE username_key='wonya'").fetchone()
        if row is None:raise ValueError('Owner account absent')
        secret=os.environ.get('CORNER_AUTH_SECRET','').strip()
        if not secret:
            secret=SECRET_PATH.read_text(encoding='utf-8').strip()
        if len(secret)<32:raise ValueError('Existing signing key required')
        token=auth.issue_token(secret,row[0],row[1],epoch=row[2],ttl=120)
        session=requests.Session();session.trust_env=False
        session.cookies.set('corner_session',token,domain='127.0.0.1',path='/')
        for cycle in ('initial','refresh'):
            if cycle=='refresh':time.sleep(16)
            snapshot=None
            paths=[('capabilities',{}),('tools/positive_ev',{'limit':250,'include_quotes':'true'}),('games',{'limit':100})]
            for path,params in paths:
                if snapshot:params['snapshot_id']=snapshot
                started=time.monotonic()
                response=session.get('http://127.0.0.1:8765/api/v1/'+path,params=params,timeout=(5,40),allow_redirects=False)
                body=response.json()
                if response.status_code!=200:
                    print(json.dumps(dict(result='feed_http_failed',cycle=cycle,stage=path,status=response.status_code,code=(body.get('error') or {}).get('code'),seconds=round(time.monotonic()-started,3),provider_calls=0)),flush=True)
                    return 1
                meta=body['meta'];data=body['data']
                if snapshot and meta['snapshot_id']!=snapshot:raise ValueError('Mixed snapshot response')
                snapshot=meta['snapshot_id']
                print(json.dumps(dict(result='feed_http_passed',cycle=cycle,stage=path,status=200,seconds=round(time.monotonic()-started,3),items=len(data.get('items',[])),captured_at=meta.get('captured_at'),provider_calls=0)),flush=True)
        return 0
    except Exception as error:
        print(json.dumps(dict(result='feed_http_failed',error_type=type(error).__name__,provider_calls=0)),flush=True)
        return 1
    finally:
        if session:session.close()
if __name__=='__main__':raise SystemExit(main())
