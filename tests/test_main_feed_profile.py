import builtins
import contextlib
import io
import unittest
from unittest.mock import patch,MagicMock
from pipelines.main_feed_profile import main

class ProfileConfig(unittest.TestCase):
    def test_profile_uses_staging_reader_without_a_config_module(self):
        original=builtins.__import__
        def restricted(name,*args,**kwargs):
            if name=='config':raise ModuleNotFoundError('config absent on VPS')
            return original(name,*args,**kwargs)
        values={'DB_HOST':'127.0.0.1','DB_PORT':'5432','DB_NAME':'corner_staging','DB_USER':'corner_api','DB_PASSWORD':'synthetic-secret'}
        conn=MagicMock()
        output=io.StringIO()
        with patch('builtins.__import__',side_effect=restricted),patch('pipelines.main_feed_profile.dotenv_values',return_value=values),patch('psycopg2.connect',return_value=conn) as connect,patch('api.database.read_source',return_value=([],[])),contextlib.redirect_stdout(output),patch.dict('os.environ',{},clear=True):
            self.assertEqual(main(),0)
        self.assertEqual(connect.call_args.kwargs['user'],'corner_api')
        conn.set_session.assert_called_once_with(readonly=True,isolation_level='REPEATABLE READ')
        self.assertNotIn('synthetic-secret',output.getvalue())
        self.assertIn('main_quote_read_passed',output.getvalue())
