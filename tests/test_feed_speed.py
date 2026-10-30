import copy
from datetime import timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from corner.credit_governor import Governor
from api.database import publication_revision
from pipelines.feed_indexes import install
from pipelines import props_ingestion as props
from tests.test_performance_paths import Conn, read
from tests.test_database_catalog import board, NOW

class Revisions(unittest.TestCase):
    def test_publication_counter_is_atomic_and_acknowledgement_only(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'simulation.sqlite3'
            g=Governor(path)
            try:
                g.db.execute('PRAGMA foreign_keys=OFF')
                g.db.execute("INSERT INTO publication_outbox VALUES('test','{}',NULL)")
                self.assertEqual(publication_revision(path)[-1],0)
                g.db.execute('BEGIN IMMEDIATE')
                g.db.execute("UPDATE publication_outbox SET published_at=1 WHERE token='test'")
                g.db.execute('ROLLBACK')
                self.assertEqual(publication_revision(path)[-1],0)
                g.db.execute("UPDATE publication_outbox SET published_at=1 WHERE token='test'")
                self.assertEqual(publication_revision(path)[-1],1)
                g.db.execute("UPDATE publication_outbox SET published_at=2 WHERE token='test'")
                self.assertEqual(publication_revision(path)[-1],1)
            finally:g.close()

    def test_scheduled_catalog_skips_history_counts_and_invalidates_on_ack(self):
        conn,cache=Conn(board()),{}
        with patch('api.database.publication_revision',return_value=('scheduled',0)) as revision,patch('api.database.fingerprint') as full_scan:
            first=read(conn,cache)
            self.assertEqual(read(conn,cache),first)
            full_scan.assert_not_called()
            self.assertEqual(conn.quote_runs,1)
            revision.return_value=('scheduled',1)
            read(conn,cache)
            self.assertEqual(conn.quote_runs,2)

class LookupIndexes(unittest.TestCase):
    def test_pending_and_closing_queries_use_indexes_and_keep_all_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            g=Governor(Path(folder)/'simulation.sqlite3')
            try:
                g.db.execute('PRAGMA foreign_keys=OFF')
                g.db.executemany('INSERT INTO publication_outbox VALUES(?,?,?)',[(str(i),'{}',None if i==99 else 1) for i in range(100)])
                install(g.db);install(g.db)
                pending=g.db.execute('EXPLAIN QUERY PLAN SELECT token,payload FROM publication_outbox WHERE published_at IS NULL ORDER BY rowid LIMIT 1').fetchall()
                self.assertIn('collection_pending_outbox',str([tuple(x) for x in pending]))
                closing=g.db.execute("EXPLAIN QUERY PLAN SELECT payload FROM clv_scopes WHERE kind='props' AND event_id='e' AND market='m' AND captured_at<=100 ORDER BY captured_at").fetchall()
                self.assertIn('collection_props_close_lookup',str([tuple(x) for x in closing]))
                self.assertEqual(g.db.execute('SELECT count(*) FROM publication_outbox').fetchone()[0],100)
            finally:g.close()

class PropsPricingCache(unittest.TestCase):
    def test_unchanged_inputs_reuse_but_changes_expiry_and_options_reprice(self):
        props._pricing_cache.clear()
        self.addCleanup(props._pricing_cache.clear)
        data={'events':{'e':{'commence_time':(NOW+timedelta(hours=1)).isoformat(),'markets':{'p':{'captured_at':NOW.isoformat(),'quotes':[{'book':'fanduel','player':'P','point':'1.5','side':0,'price':'2'}]}}}}}
        with patch.object(props,'load',side_effect=lambda:copy.deepcopy(data)),patch.object(props,'build_bets',side_effect=lambda events,**kwargs:[{'id':'e:p:P:1.5:fanduel:0','market_key':'p','ev':'1'}] if events else []) as build:
            first=props.bets(NOW);first[0]['ev']='changed'
            self.assertEqual(props.bets(NOW)[0]['ev'],'1')
            self.assertEqual(build.call_count,1)
            props.bets(NOW,one_sided_margin='0.1')
            self.assertEqual(build.call_count,2)
            data['events']['e']['markets']['p']['quotes'][0]['price']='3'
            props.bets(NOW)
            self.assertEqual(build.call_count,3)
            self.assertEqual(props.bets(NOW+timedelta(hours=2)),[])
            self.assertEqual(build.call_count,3)
