import contextlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

MODULE=Path(__file__).resolve().parents[1]/'deploy/storage/corner_storage.py'
if not MODULE.exists():MODULE=Path(__file__).with_name('corner_storage.py')
spec=importlib.util.spec_from_file_location('storage_retention',MODULE)
storage=importlib.util.module_from_spec(spec);spec.loader.exec_module(storage)

@contextlib.contextmanager
def connect(path):
    db=sqlite3.connect(path)
    try:
        with db:yield db
    finally:db.close()

class StorageRetentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.state=self.root/'ledger.sqlite3';self.tracker=self.root/'accounts.sqlite3'
        with connect(self.tracker) as db:
            db.executescript('CREATE TABLE users(id TEXT); CREATE TABLE cash(id TEXT,amount INTEGER); CREATE TABLE bets(id TEXT,ref TEXT,parlay_legs TEXT,starts_at TEXT);')
            db.execute('INSERT INTO users VALUES(?)',('owner',));db.execute('INSERT INTO cash VALUES(?,?)',('deposit',100))
            db.execute('INSERT INTO bets VALUES(?,?,?,?)',('logged',json.dumps({'game_id':'prop:logged','prop_market':'player_points'}),'[]','1970-01-01T00:00:50+00:00'))
        with connect(self.state) as db:
            db.executescript('''CREATE TABLE controls(id INTEGER PRIMARY KEY,paused TEXT);
            CREATE TABLE attempts(token TEXT PRIMARY KEY,state TEXT,reserved INTEGER,actual INTEGER);
            CREATE TABLE audit(id INTEGER PRIMARY KEY AUTOINCREMENT,detail BLOB);
            CREATE TABLE clv_scopes(kind TEXT,sport TEXT,event_id TEXT,book TEXT,market TEXT,starts_at REAL,source_at REAL,captured_at REAL,expires_at REAL,payload TEXT,PRIMARY KEY(kind,sport,event_id,book,market,captured_at));
            CREATE TABLE snapshots(kind TEXT,sport TEXT,event_id TEXT,book TEXT,market TEXT,starts_at REAL,source_at REAL,captured_at REAL,expires_at REAL,payload TEXT);
            CREATE TABLE publication_outbox(token TEXT PRIMARY KEY REFERENCES attempts(token),payload TEXT,published_at REAL);
            CREATE TABLE live_captures(sport TEXT,book_group TEXT,captured REAL,payload TEXT);
            CREATE TABLE runner_inventory(id INTEGER PRIMARY KEY,payload TEXT);''')
            db.execute('INSERT INTO controls VALUES(1,?)',('Uncertain request',))
            for i in range(40):
                token=f'{i:048x}';db.execute('INSERT INTO attempts VALUES(?,?,?,?)',(token,'unknown' if i==39 else 'settled',7,None if i==39 else 3))
                db.execute('INSERT INTO publication_outbox VALUES(?,?,?)',(token,'paid capture',None if i==39 else i))
            db.execute('INSERT INTO audit(detail) VALUES(?)',(b'financial evidence',))
            db.execute('UPDATE sqlite_sequence SET seq=100 WHERE name=\'audit\'')
            for event,start,captured in [('logged',50,1),('logged',50,2),('old',-50000,1),('future',200,20),('future',200,10)]:
                row=('props','nba',event,'fanduel','player_points',start,captured,captured,captured+30,'unchanged')
                db.execute('INSERT INTO clv_scopes VALUES(?,?,?,?,?,?,?,?,?,?)',row)
                if (event!='future' or captured==20) and (event!='logged' or captured==2):db.execute('INSERT INTO snapshots VALUES(?,?,?,?,?,?,?,?,?,?)',row)
            db.execute('INSERT INTO runner_inventory VALUES(1,?)',('inventory',))

    def test_compaction_preserves_accounting_logged_history_and_latest_prices(self):
        with storage.ro(self.state) as db:before={t:storage.logical_hash(db,t) for t in ('attempts','audit','controls','runner_inventory')}
        with storage.ro(self.tracker) as db:accounts={t:storage.logical_hash(db,t) for t in ('users','bets','cash')}
        storage.compact(self.state,self.tracker,self.root/'receipts',100)
        with storage.ro(self.state) as db:
            self.assertEqual(before,{t:storage.logical_hash(db,t) for t in before})
            self.assertEqual(db.execute('SELECT event_id,captured_at FROM clv_scopes ORDER BY event_id,captured_at').fetchall(),[('future',20),('logged',2)])
            self.assertEqual(db.execute('SELECT count(*) FROM publication_outbox').fetchone()[0],33)
            self.assertEqual(db.execute("SELECT count(*) FROM publication_outbox WHERE published_at IS NULL").fetchone()[0],1)
            self.assertEqual(db.execute('SELECT seq FROM sqlite_sequence WHERE name=\'audit\'').fetchone()[0],100)
        with storage.ro(self.tracker) as db:self.assertEqual(accounts,{t:storage.logical_hash(db,t) for t in accounts})

    def test_compaction_returns_expired_unlogged_payload_space_to_filesystem(self):
        with connect(self.state) as db:
            db.execute("UPDATE clv_scopes SET payload=? WHERE event_id='old'",('discarded data'*100000,))
        before=self.state.stat().st_size
        storage.compact(self.state,self.tracker,self.root/'receipts',100)
        self.assertLess(self.state.stat().st_size,before/2)

    def test_logged_matchup_history_is_discarded_except_closing_capture(self):
        with connect(self.state) as db:
            db.execute("UPDATE clv_scopes SET payload=? WHERE event_id='logged' AND captured_at=1",('obsolete logged matchup history'*100000,))
        before=self.state.stat().st_size
        storage.compact(self.state,self.tracker,self.root/'receipts',100)
        self.assertLess(self.state.stat().st_size,before/2)
        with storage.ro(self.state) as db:
            self.assertEqual(db.execute("SELECT captured_at FROM clv_scopes WHERE event_id='logged'").fetchall(),[(2,)])

    def test_parlay_closes_use_each_legs_start_and_retain_multiple_cutoffs(self):
        with connect(self.tracker) as db:
            db.execute('UPDATE bets SET parlay_legs=?',(json.dumps([{'ref':{'game_id':'logged','prop_market':'player_points'},'starts_at':'1970-01-01T00:00:01+00:00'}]),))
        storage.compact(self.state,self.tracker,self.root/'receipts',100)
        with storage.ro(self.state) as db:
            self.assertEqual(db.execute("SELECT captured_at FROM clv_scopes WHERE event_id='logged' ORDER BY captured_at").fetchall(),[(1,),(2,)])

    def test_minimal_copy_space_check_preserves_original_before_large_write(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        before=self.state.read_bytes()
        with patch.object(storage.shutil,'disk_usage',return_value=SimpleNamespace(free=300*1024**2)):
            with self.assertRaisesRegex(RuntimeError,'Insufficient space for minimal closing'):
                storage.compact(self.state,self.tracker,self.root/'receipts',100)
        self.assertEqual(before,self.state.read_bytes())

    def test_integrity_verification_does_not_scan_attached_old_ledger(self):
        with connect(':memory:') as db:
            db.execute('CREATE TABLE candidate(id INTEGER PRIMARY KEY)')
            db.execute("ATTACH DATABASE ':memory:' AS src")
            db.execute('CREATE TABLE src.old_history(id INTEGER PRIMARY KEY,payload TEXT)')
            # Unqualified integrity_check visits every attached database. The
            # production check must visit only the compact main candidate.
            original=[row for row in db.execute('EXPLAIN PRAGMA integrity_check') if row[1]=='Transaction']
            self.assertIn(2,{row[2] for row in original})
            plan=list(db.execute('EXPLAIN '+storage.CANDIDATE_INTEGRITY_SQL))
            self.assertEqual({row[2] for row in plan if row[1]=='Transaction'},{0})
            self.assertEqual(db.execute(storage.CANDIDATE_INTEGRITY_SQL).fetchone()[0],'ok')
            self.assertEqual(storage.CANDIDATE_FOREIGN_KEY_SQL,'PRAGMA main.foreign_key_check')

    def test_foreign_key_failure_leaves_original_ledger_unchanged(self):
        with connect(self.state) as db:
            db.execute('CREATE TABLE retained_reference(token TEXT REFERENCES publication_outbox(token))')
            db.execute('INSERT INTO retained_reference VALUES(?)',(f'{0:048x}',))
        before=self.state.read_bytes()
        with self.assertRaisesRegex(RuntimeError,'integrity/FK'):
            storage.compact(self.state,self.tracker,self.root/'receipts',100)
        self.assertEqual(before,self.state.read_bytes())

    def test_capture_cleanup_only_removes_acknowledged_known_files(self):
        root=self.root/'captures';root.mkdir()
        for i in (0,38,39):
            folder=root/f'{i:048x}';folder.mkdir();(folder/'response.body').write_text('data')
        unknown=root/('f'*48);unknown.mkdir();(unknown/'response.body').write_text('data')
        backup=self.root/'completed.tar.gz.gpg';backup.write_bytes(b'protected')
        storage.remove_published_captures(self.state,root)
        self.assertFalse((root/f'{0:048x}').exists())
        self.assertTrue((root/f'{38:048x}').exists());self.assertTrue((root/f'{39:048x}').exists())
        self.assertTrue(unknown.exists());self.assertEqual(backup.read_bytes(),b'protected')

    def test_postgres_retention_keeps_logged_and_current_quote_evidence(self):
        self.assertIn('storage_logged',storage.POSTGRES_SQL)
        self.assertIn('Current quote changed during retention',storage.POSTGRES_SQL)
        self.assertIn("c.contype='f'",storage.POSTGRES_SQL)
        self.assertNotIn('CASCADE',storage.POSTGRES_SQL)

if __name__=='__main__':unittest.main()
