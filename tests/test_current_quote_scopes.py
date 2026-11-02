from contextlib import closing
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timezone
from api.database import current_quote_scopes,SCOPED_QUOTE_SQL

class CurrentScopeLookup(unittest.TestCase):
    def test_only_current_line_points_and_books_reach_postgres(self):
        now=datetime(2026,11,2,20,tzinfo=timezone.utc);stamp=now.timestamp()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'scopes.sqlite3'
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE snapshots(kind,event_id,book,market,captured_at,payload,expires_at,starts_at,source_at)')
                payload=json.dumps({'market':{'outcomes':[{'name':'Over','point':45.5},{'name':'Under','point':45.5}]}})
                for kind,book,expiry,start in [('main','draftkings',stamp+100,stamp+500),('main','fanduel',stamp-1,stamp+500),('props','novig',stamp+100,stamp+500),('main','pinnacle',stamp+100,stamp-1)]:
                    db.execute('INSERT INTO snapshots VALUES(?,?,?,?,?,?,?,?,?)',(kind,'event',book,'totals',stamp-1,payload,expiry,start,stamp-1))
            rows=current_quote_scopes(path,now)
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['book_code'],'draftkings')
            self.assertEqual(rows[0]['market_code'],'total')
            self.assertEqual(rows[0]['point'],'45.5')
            with closing(sqlite3.connect(path)) as db, db:db.execute('DELETE FROM snapshots')
            self.assertEqual(current_quote_scopes(path,now),[])

    def test_database_winner_is_still_verified_after_current_inventory_selection(self):
        self.assertIn('jsonb_to_recordset(%(scopes)s::jsonb)',SCOPED_QUOTE_SQL)
        self.assertIn('o.point IS NOT DISTINCT FROM scope.point',SCOPED_QUOTE_SQL)
        self.assertIn('b.code=scope.book_code',SCOPED_QUOTE_SQL)
        self.assertIn('q.observed_at=scope.captured_at',SCOPED_QUOTE_SQL)
        self.assertIn('trusted_quote_for_stream(o.id, b.id)',SCOPED_QUOTE_SQL)
