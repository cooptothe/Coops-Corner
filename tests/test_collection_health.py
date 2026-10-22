import sqlite3
import unittest
from pipelines.collection_health import diagnose

class HealthTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript("CREATE TABLE controls(id,paused); INSERT INTO controls VALUES(1,'uncertain'); CREATE TABLE attempts(started,state); CREATE TABLE quota_inventory(state); CREATE TABLE publication_outbox(published_at);")
    def test_one_old_unknown_is_candidate(self):
        self.db.execute("INSERT INTO attempts VALUES(0,'unknown')")
        self.assertTrue(diagnose(self.db,126)['bounded_recovery_candidate'])
        self.assertFalse(diagnose(self.db,100)['bounded_recovery_candidate'])
    def test_multiple_or_inventory_unknown_refused(self):
        self.db.executemany("INSERT INTO attempts VALUES(0,'unknown')",[(),()])
        self.assertFalse(diagnose(self.db,200)['bounded_recovery_candidate'])
        self.db.execute('DELETE FROM attempts WHERE rowid=2')
        self.db.execute("INSERT INTO quota_inventory VALUES('unknown')")
        self.assertFalse(diagnose(self.db,200)['bounded_recovery_candidate'])
