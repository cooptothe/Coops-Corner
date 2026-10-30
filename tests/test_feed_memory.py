from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pipelines.trends_service import inventory_digest
from pipelines import lab_status

class FeedMemory(unittest.TestCase):
    def test_incremental_inventory_digest_matches_canonical_snapshot_identity(self):
        for items in ([],[{'id':'x','player':'José','price':'2'}],[{'id':str(i),'point':'2.5'} for i in range(100)]):
            expected=hashlib.sha256(json.dumps(items,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            self.assertEqual(inventory_digest(items),expected)

    def test_lab_diagnostic_counts_rows_without_decoding_or_reconstructing(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'lab-catalog.sqlite3'
            db=sqlite3.connect(path)
            db.execute('CREATE TABLE lab_catalog(id TEXT,body TEXT)')
            db.execute("INSERT INTO lab_catalog VALUES('test','not-json-on-purpose')")
            db.commit();db.close()
            output=io.StringIO()
            with patch.dict(os.environ,{'CORNER_TRENDS_DB':str(Path(directory)/'trends.sqlite3')}),patch('pipelines.trends_service.contracts',side_effect=AssertionError('must not reconstruct')) ,redirect_stdout(output):
                lab_status.main()
            result=json.loads(output.getvalue())
            self.assertEqual(result['lab_quotes'],1)
            self.assertEqual(result['provider_calls'],0)
