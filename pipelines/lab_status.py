"""Bounded SQL-only saved Lab count. No quote reconstruction or provider IO."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
from dotenv import dotenv_values

def main():
    config=Path('/srv/corner/config/staging.env')
    if config.exists():
        for key,value in dotenv_values(config).items():
            if value is not None:os.environ.setdefault(key,value)
    root=Path(__file__).resolve().parents[1]
    path=Path(os.environ.get('CORNER_TRENDS_DB',str(root/'retained/trends.sqlite3'))).with_name('lab-catalog.sqlite3')
    count=0
    if path.is_file():
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='lab_catalog'").fetchone():
                count=db.execute('SELECT count(*) FROM lab_catalog').fetchone()[0]
    print(json.dumps({'lab_quotes':count,'saved_catalog_only':True,
        'provider_calls':0,'result':'saved_catalog_present' if count else 'no_saved_lab_catalog'}))

if __name__=='__main__':main()
