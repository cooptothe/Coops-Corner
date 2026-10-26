import sqlite3
import unittest
from pipelines.collection_health import diagnose

class HealthTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript("CREATE TABLE controls(id,paused); INSERT INTO controls VALUES(1,'uncertain'); CREATE TABLE attempts(started,state); CREATE TABLE quota_inventory(started,state); CREATE TABLE publication_outbox(published_at);")
    def test_one_old_unknown_is_candidate(self):
        self.db.execute("INSERT INTO attempts VALUES(0,'unknown')")
        self.assertTrue(diagnose(self.db,126)['bounded_recovery_candidate'])
        self.assertFalse(diagnose(self.db,100)['bounded_recovery_candidate'])
    def test_multiple_or_inventory_unknown_refused(self):
        self.db.executemany("INSERT INTO attempts VALUES(0,'unknown')",[(),()])
        self.assertFalse(diagnose(self.db,200)['bounded_recovery_candidate'])
        self.db.execute('DELETE FROM attempts WHERE rowid=2')
        self.db.execute("INSERT INTO quota_inventory VALUES(0,'unknown')")
        self.assertFalse(diagnose(self.db,200)['bounded_recovery_candidate'])

    def test_single_old_inventory_candidate_not_inflight(self):
        self.db.execute("INSERT INTO quota_inventory VALUES(0,'unknown')")
        self.assertTrue(diagnose(self.db,126)['bounded_recovery_candidate'])
        self.assertFalse(diagnose(self.db,100)['bounded_recovery_candidate'])
        self.db.execute("UPDATE quota_inventory SET state='inflight'")
        self.assertFalse(diagnose(self.db,200)['bounded_recovery_candidate'])


    def test_publication_error_is_visible_without_triggering_quota_recovery(self):
        self.db.executescript("ALTER TABLE publication_outbox ADD COLUMN token; CREATE TABLE publication_failures(token,failures,retry_at,quarantined,error_type,sqlstate);")
        self.db.execute("INSERT INTO publication_outbox VALUES(NULL,'capture')")
        self.db.execute("INSERT INTO publication_failures VALUES('capture',5,300,0,'UniqueViolation','23505')")
        self.db.execute("UPDATE controls SET paused=''")
        result=diagnose(self.db,200)
        self.assertTrue(result['publication_blocked'])
        self.assertFalse(result['bounded_recovery_candidate'])
        self.assertEqual(result['publication_errors'],[dict(error_type='UniqueViolation',sqlstate='23505',failures=5,retry_after_seconds=100)])
        self.db.execute("UPDATE publication_outbox SET published_at=201")
        self.assertFalse(diagnose(self.db,202)['publication_blocked'])
