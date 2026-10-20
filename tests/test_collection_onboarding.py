from datetime import datetime,timezone
import json
from pathlib import Path
import tempfile
import unittest
import requests
from pipelines.collection_onboarding import quota_window,verify_key,store_key,disabled_config,private_file,OnboardingError,URL

KEY='synthetic-key-for-offline-test'
class Response:
    status_code=200
    def __init__(self,used=0,charge=0,total=15000000,body=None):
        self.headers={'X-Requests-Used':str(used),'X-Requests-Remaining':str(total-used),'X-Requests-Last':str(charge)}
        self.body=body if body is not None else json.dumps([{'key':'basketball_nba','active':True}]).encode()
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def iter_content(self,size):yield self.body
class Session:
    def __init__(self,response=None,error=None):self.response=response or Response();self.calls=[];self.error=error;self.closed=False
    def get(self,url,**kwargs):
        self.calls.append((url,kwargs))
        if self.error:raise self.error
        return self.response
    def close(self):self.closed=True
class Onboarding(unittest.TestCase):
    def test_quota_cycle_not_invoice_anniversary(self):
        start,end=quota_window(datetime(2026,10,20,15,tzinfo=timezone.utc))
        self.assertEqual(start,'2026-10-01T00:00:00+00:00');self.assertEqual(end,'2026-11-01T00:00:00+00:00')
        self.assertEqual(quota_window(datetime(2026,12,31,tzinfo=timezone.utc))[1],'2027-01-01T00:00:00+00:00')
    def test_exactly_one_zero_cost_inventory_request_and_no_key_in_report(self):
        session=Session();result=verify_key(KEY,session=session,now=datetime(2026,10,20,tzinfo=timezone.utc))
        self.assertEqual(len(session.calls),1);self.assertEqual(session.calls[0][0],URL)
        options=session.calls[0][1]
        self.assertEqual(options['params'],{'apiKey':KEY});self.assertFalse(options['allow_redirects']);self.assertTrue(options['verify'])
        self.assertEqual(result['paid_odds_calls'],0);self.assertEqual(result['provider_remaining'],15000000)
        self.assertNotIn(KEY,json.dumps(result));self.assertTrue(session.closed)
        self.assertEqual(result['next_invoice_date'],'2026-11-20')
    def test_wrong_quota_charge_missing_headers_or_echo_refused(self):
        responses=[Response(total=5000000),Response(charge=1),Response(body=KEY.encode())]
        missing=Response();missing.headers={};responses.append(missing)
        for response in responses:
            session=Session(response)
            with self.assertRaises(OnboardingError):verify_key(KEY,session=session)
            self.assertEqual(len(session.calls),1);self.assertTrue(session.closed)
    def test_transport_error_never_leaks_key_or_retries(self):
        session=Session(error=requests.RequestException('https://example/?apiKey='+KEY))
        with self.assertRaises(OnboardingError) as caught:verify_key(KEY,session=session)
        self.assertNotIn(KEY,str(caught.exception));self.assertEqual(len(session.calls),1)
    def test_invalid_key_never_dispatches(self):
        session=Session()
        with self.assertRaises(OnboardingError):verify_key('bad\nkey',session=session)
        self.assertFalse(session.calls)
    def test_atomic_private_storage_preserves_disabled_writer_and_refuses_rotation(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'collection.env'
            original="CORNER_COLLECTION_ENABLED='0'\nCORNER_COLLECTION_DB_PASSWORD='writer-secret'\nODDS_API_KEY=''\n"
            path.write_text(original);path.chmod(0o600)
            store_key(path,KEY,original)
            text=path.read_text();self.assertIn("CORNER_COLLECTION_ENABLED='0'",text);self.assertIn('writer-secret',text)
            with self.assertRaises(OnboardingError):store_key(path,'different-key-value',text)
            with self.assertRaises(OnboardingError):store_key(path,KEY,original)
            self.assertEqual(path.read_text(),text);self.assertFalse(list(path.parent.glob('.collection-onboarding-*')))
    def test_stored_worker_key_is_safe_only_with_disabled_config_and_no_staging_key(self):
        with tempfile.TemporaryDirectory() as directory:
            worker=Path(directory)/'collection.env';stage=Path(directory)/'staging.env'
            worker.write_text("CORNER_COLLECTION_ENABLED='0'\nCORNER_PRIVATE_BETA='1'\nODDS_API_KEY='"+KEY+"'\n");worker.chmod(0o600)
            stage.write_text("CORNER_PRIVATE_BETA='1'\nCORNER_REFRESH_DAILY_CAP='0'\n");stage.chmod(0o600)
            self.assertEqual(disabled_config(worker,stage)['ODDS_API_KEY'],KEY)
            stage.write_text(stage.read_text()+"ODDS_API_KEY='"+KEY+"'\n")
            with self.assertRaises(OnboardingError):disabled_config(worker,stage)
            stage.write_text("CORNER_PRIVATE_BETA='1'\nCORNER_REFRESH_DAILY_CAP='0'\n")
            worker.write_text(worker.read_text().replace("ENABLED='0'","ENABLED='1'"))
            with self.assertRaises(OnboardingError):disabled_config(worker,stage)
    def test_duplicate_assignments_do_not_mutate_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'collection.env'
            original="CORNER_COLLECTION_ENABLED='0'\nODDS_API_KEY=''\nexport ODDS_API_KEY=''\n"
            path.write_text(original);path.chmod(0o600)
            with self.assertRaises(OnboardingError):store_key(path,KEY,original)
            self.assertEqual(path.read_text(),original)
if __name__=='__main__':unittest.main()
