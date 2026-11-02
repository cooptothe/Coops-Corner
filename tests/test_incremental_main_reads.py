from datetime import timedelta
from pathlib import Path
import json
import unittest
from unittest.mock import patch
from api.database import read_source,SCOPED_QUOTE_SQL,PARTICIPANT_SQL
from tests.test_database_catalog import NOW

def scope(event,at=NOW):return dict(external_id=event,book_code='draftkings',market_code='total',point='45.5',captured_at=at.isoformat())
def quote(event,at=NOW):return dict(source_event_id=event,event_id=event,book_code='draftkings',market_code='total',point='45.5',observed_at=at,scheduled_start=NOW+timedelta(hours=2))
class Connection:
    def __init__(self):self.calls=[];self.rows=[]
    def cursor(self,**kwargs):return self
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def execute(self,sql,params):
        self.last=sql
        if sql==SCOPED_QUOTE_SQL:self.calls.append(json.loads(params['scopes']))
    def fetchall(self):return self.rows if self.last==SCOPED_QUOTE_SQL else []

class IncrementalMain(unittest.TestCase):
    def test_unchanged_scopes_reused_with_changed_and_withdrawn_lines_revalidated(self):
        conn=Connection();cache={};revision=['r',1];scopes=[scope('a'),scope('b')]
        with patch('api.database.scheduled_store_path',return_value=Path('ledger')),patch('api.database.publication_revision',side_effect=lambda path:tuple(revision)),patch('api.database.current_quote_scopes',side_effect=lambda *args:list(scopes)),patch('api.database.time.monotonic',return_value=100):
            conn.rows=[quote('a'),quote('b')]
            first=read_source(conn,now=NOW,max_age=timedelta(minutes=30),cache=cache)[0]
            later=NOW+timedelta(seconds=60);revision[1]+=1;scopes[1]=scope('b',later);conn.rows=[quote('b',later)]
            rows=read_source(conn,now=later,max_age=timedelta(minutes=30),cache=cache)[0]
            self.assertEqual([s['external_id'] for s in conn.calls[-1]],['b'])
            self.assertEqual(rows,[quote('a'),quote('b',later)])
            self.assertEqual(cache['reused_quotes'],1)
            revision[1]+=1;scopes[:]=[scope('b',later)]
            rows=read_source(conn,now=later,max_age=timedelta(minutes=30),cache=cache)[0]
            self.assertEqual(rows,[quote('b',later)])
            self.assertEqual(len(conn.calls),2)

    def test_unpublished_scope_retries_on_ack_and_full_refresh_has_a_fixed_deadline(self):
        conn=Connection();cache={};revision=['r',1];clock=[100]
        with patch('api.database.scheduled_store_path',return_value=Path('ledger')),patch('api.database.publication_revision',side_effect=lambda path:tuple(revision)),patch('api.database.current_quote_scopes',return_value=[scope('a')]),patch('api.database.time.monotonic',side_effect=lambda:clock[0]):
            self.assertEqual(read_source(conn,now=NOW,max_age=timedelta(minutes=30),cache=cache)[0],[])
            revision[1]+=1;conn.rows=[quote('a')]
            self.assertEqual(read_source(conn,now=NOW,max_age=timedelta(minutes=30),cache=cache)[0],[quote('a')])
            self.assertEqual(len(conn.calls),2)
            clock[0]=701
            read_source(conn,now=NOW,max_age=timedelta(minutes=30),cache=cache)
            self.assertEqual(len(conn.calls),3)

    def test_expired_cached_rows_cannot_survive_a_refresh(self):
        conn=Connection();cache={};revision=['r',1];scopes=[scope('a')]
        with patch('api.database.scheduled_store_path',return_value=Path('ledger')),patch('api.database.publication_revision',side_effect=lambda path:tuple(revision)),patch('api.database.current_quote_scopes',side_effect=lambda *args:list(scopes)),patch('api.database.time.monotonic',return_value=100):
            conn.rows=[quote('a')];read_source(conn,now=NOW,max_age=timedelta(minutes=30),cache=cache)
            revision[1]+=1;scopes.clear()
            self.assertEqual(read_source(conn,now=NOW+timedelta(minutes=31),max_age=timedelta(minutes=30),cache=cache)[0],[])
