"""Measure retained feed work without provider requests or ledger changes."""
import argparse
import json
import os
import time
from pathlib import Path
from dotenv import dotenv_values

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog',action='store_true')
    args=parser.parse_args()
    stage=Path('/srv/corner/config/staging.env')
    if stage.exists():
        for key,value in dotenv_values(stage).items():
            if value is not None:os.environ[key]=value
    from pipelines import props_ingestion as props
    for run in ('cold','warm'):
        started=time.perf_counter()
        bets=props.bets()
        print(json.dumps({'stage':'props_'+run,'seconds':round(time.perf_counter()-started,3),'bets':len(bets),'provider_calls':0}),flush=True)
    if args.catalog:
        import psycopg2
        from config import DB_CONFIG
        from api.database import LiveCatalog
        print(json.dumps({'stage':'catalog_starting'}),flush=True)
        def connect():
            return psycopg2.connect(**DB_CONFIG,connect_timeout=5,options='-c statement_timeout=30000')
        started=time.perf_counter()
        catalog=LiveCatalog(connect)
        print(json.dumps({'stage':'catalog_cold','seconds':round(time.perf_counter()-started,3),'games':len(catalog._inner.games),'quotes':len(catalog._inner.quotes),'rows':len(catalog._inner.rows)}),flush=True)
        started=time.perf_counter();catalog.reload()
        print(json.dumps({'stage':'catalog_reload','seconds':round(time.perf_counter()-started,3),'provider_calls':0}),flush=True)

if __name__=='__main__':main()
