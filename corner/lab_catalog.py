"""Saved research lines, separate from executable/fresh feed snapshots."""
import json
from contextlib import closing
import sqlite3
from corner.prop_trends import instant
from pathlib import Path

MONTH = 30 * 86400

def remember(items, path, now):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(path,timeout=5)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS lab_catalog(id TEXT PRIMARY KEY, source_at REAL NOT NULL, starts_at REAL NOT NULL, body TEXT NOT NULL)')
        db.execute('CREATE INDEX IF NOT EXISTS lab_catalog_start ON lab_catalog(starts_at)')
        for item in items.values():
            source=instant(item.get('observed_at'));start=instant(item.get('starts_at'))
            if source is None or start is None:continue
            db.execute('INSERT INTO lab_catalog VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET source_at=excluded.source_at,starts_at=excluded.starts_at,body=excluded.body WHERE excluded.source_at>lab_catalog.source_at OR (excluded.source_at=lab_catalog.source_at AND excluded.body<>lab_catalog.body)',
                       (item['id'],source,start,json.dumps(item,separators=(',',':'))))
        newest=db.execute('SELECT max(starts_at) FROM lab_catalog').fetchone()[0]
        if newest is None:return {}
        # A rolling recent-event slate, anchored to the last known event if
        # collection stops. No expiry wipe when the collector is offline.
        floor=min(now,newest)-MONTH
        saved=[json.loads(row[0]) for row in db.execute('SELECT body FROM lab_catalog WHERE starts_at>=? ORDER BY starts_at DESC,id',(floor,))]
    output={}
    for old in saved:
        current=items.get(old['id'])
        if current and (instant(current.get('observed_at')) or 0)<(instant(old.get('observed_at')) or 0):current=None
        item=dict(current or old)
        if not current:
            item.update(quote_status='past_event' if item['starts_at'] and instant(item['starts_at'])<=now else 'stale',commission=None,links=None)
        output[item['id']]=item
    return output
