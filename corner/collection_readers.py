"""Read-only authority for scheduled scopes. No provider calls or quote re-dating."""
import os
from pathlib import Path
import sqlite3

from corner import beta_access
from corner.collection_policy import EXCHANGE,aware


def store_path():
    value=os.environ.get('CORNER_COLLECTION_DB','')
    if not beta_access.enabled() or not value:return None
    path=Path(value)
    if 'simulation' in path.name.lower():
        raise ValueError('Simulation state cannot be a member feed source')
    return path


def main_scopes(rows,path,now):
    now=aware(now);stamp=now.timestamp()
    path=Path(path)
    if not path.exists():return []
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=3)
    try:
        scopes={(r[0],r[1],r[2]):r[3] for r in db.execute("SELECT event_id,book,market,captured_at FROM snapshots WHERE kind='main' AND expires_at>? AND starts_at>?",(stamp,stamp))}
    finally:db.close()
    market_keys={'moneyline':'h2h','spread':'spreads','total':'totals'}
    kept=[]
    for row in rows:
        expected=scopes.get((row.get('source_event_id'),row['book_code'],market_keys.get(row['market_code'])))
        updated=row.get('provider_updated_at')
        observed=row['observed_at']
        if expected is None or updated is None:continue
        age=60 if row['book_code'] in EXCHANGE else 180
        if abs(observed.timestamp()-expected)>.001:continue
        if not (0<=stamp-observed.timestamp()<age and -5<=stamp-updated.timestamp()<age):continue
        kept.append(row)
    return kept
