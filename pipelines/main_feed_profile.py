"""Read-only main quote timing; no catalog reconstruction or provider requests."""
import json
import os
import time
from datetime import datetime, timedelta, timezone
from dotenv import dotenv_values

def main():
    for key,value in dotenv_values('/srv/corner/config/staging.env').items():
        if value is not None:os.environ[key]=value
    import psycopg2
    from config import DB_CONFIG
    from api.database import read_source
    conn=None;started=time.monotonic()
    try:
        conn=psycopg2.connect(**DB_CONFIG,connect_timeout=5,options='-c statement_timeout=15000')
        conn.set_session(readonly=True,isolation_level='REPEATABLE READ')
        rows,participants=read_source(conn,now=datetime.now(timezone.utc),max_age=timedelta(minutes=30))
        print(json.dumps(dict(result='main_quote_read_passed',seconds=round(time.monotonic()-started,3),quote_rows=len(rows),participant_rows=len(participants),provider_calls=0)))
        return 0
    except Exception as error:
        print(json.dumps(dict(result='main_quote_read_failed',error_type=type(error).__name__,sqlstate=getattr(error,'pgcode',None),seconds=round(time.monotonic()-started,3),provider_calls=0)))
        return 1
    finally:
        if conn:conn.close()
if __name__=='__main__':raise SystemExit(main())
