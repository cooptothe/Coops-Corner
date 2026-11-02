import os
import unittest
from pathlib import Path
from tests.test_corner_trusted_quotes import TrustedQuoteTests

@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE') == '1','opt-in PostgreSQL tests')
class IndexedQuotePostgres(TrustedQuoteTests):
    def current(self):
        from psycopg2.extras import RealDictCursor
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT * FROM corner.trusted_quote_for_stream(%s,%s)',(self.outcome,self.book))
            fast=cur.fetchone()
            cur.execute('SELECT * FROM corner.trusted_current_quotes WHERE outcome_id=%s AND sportsbook_id=%s',(self.outcome,self.book))
            original=cur.fetchone()
            self.assertEqual(fast,original)
            return fast
