from datetime import timedelta
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import os
from unittest.mock import patch

import requests
from corner.collection_policy import plan,parse
from corner.credit_governor import Governor,Refused
from pipelines.collection_provider import Provider
from pipelines.collection_publication import MainPublisher,read_props
from corner.collection_readers import main_scopes,store_path
from api.database import keep_latest_capture

NOW=parse('2026-10-19T15:00:00Z')


def event():
    return {'id':'event1','sport_key':'basketball_nba','commence_time':(NOW+timedelta(minutes=10)).isoformat(),
            'home_team':'Home','away_team':'Away'}


class Response:
    def __init__(self,payload,status=200,charge='3',error=None):
        self.raw=json.dumps(payload).encode();self.status_code=status;self.error=error
        self.headers={'X-Requests-Last':charge,'X-Requests-Remaining':'14999990'}
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def iter_content(self,size):
        if self.error:raise self.error
        yield self.raw


class Session:
    def __init__(self,responses):self.responses=list(responses);self.calls=[];self.trust_env=True
    def get(self,url,**kwargs):
        self.calls.append((url,kwargs));return self.responses.pop(0)
    def close(self):pass


class Adapters(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.g=Governor(Path(self.tmp.name)/'collection-live.sqlite3')
        self.g.configure_cycle('test',NOW-timedelta(days=3),NOW+timedelta(days=28))
        self.g.acquire('worker',NOW)
        self.jobs=plan(NOW,['basketball_nba'],[event()])

    def tearDown(self):self.g.close();self.tmp.cleanup()

    def provider(self,responses,**kwargs):
        session=Session(responses)
        p=Provider(key='TEST_SECRET_NEVER_LOG',enabled=True,session=session,clock=lambda:NOW,**kwargs)
        return p,session

    def priced(self,job):
        e=event()
        e['bookmakers']=[{'key':job.books[0],'last_update':NOW.isoformat(),
                         'markets':[{'key':job.markets[0],'last_update':NOW.isoformat(),
                                     'outcomes':[{'name':'Over','description':'Test player','point':10.5,'price':2.1}]}]}]
        return e

    def test_defaults_before_date_and_after_hours_never_connect(self):
        session=Session([])
        for enabled,key,clock in [(False,'key',lambda:NOW),(True,'',lambda:NOW),
                                  (True,'key',lambda:NOW-timedelta(days=1)),
                                  (True,'key',lambda:parse('2026-10-20T06:00:00Z'))]:
            p=Provider(key=key,enabled=enabled,session=session,clock=clock)
            with self.assertRaises(Refused):p.discover()
        self.assertEqual(session.calls,[])

    def test_main_request_requires_reserved_cost_and_retains_native_ids_flags(self):
        job=self.jobs[0];p,s=self.provider([Response([])])
        with self.assertRaises(Refused):p.odds(self.g,job,'no-reservation','worker')
        token=self.g.claim(job,'worker',NOW)
        status,events,headers,at=p.odds(self.g,job,token,'worker')
        self.assertEqual((status,events),(200,[]))
        url,kwargs=s.calls[0]
        self.assertTrue(url.endswith('/basketball_nba/odds'))
        self.assertEqual(kwargs['params']['bookmakers'],','.join(job.books))
        self.assertEqual(kwargs['params']['includeSids'],'true')
        self.assertFalse(kwargs['allow_redirects']);self.assertTrue(kwargs['verify'])
        self.assertFalse(s.trust_env)
        with self.assertRaises(Refused):p.odds(self.g,job,token,'worker')
        self.assertEqual(len(s.calls),1)

    def test_exchange_requires_classification_verification_and_props_wraps_event(self):
        job=self.jobs[3];p,s=self.provider([Response(self.priced(job),charge=str(job.cost))])
        token=self.g.claim(job,'worker',NOW)
        with self.assertRaises(Refused):p.odds(self.g,job,token,'worker')
        self.assertEqual(s.calls,[])
        p.exchange_verified=True
        status,data,headers,at=p.odds(self.g,job,token,'worker')
        self.assertEqual(data[0]['id'],'event1')
        self.assertIn('/events/event1/odds',s.calls[0][0])

    def test_timeout_is_sanitized_and_not_automatically_retried(self):
        job=self.jobs[0]
        p,s=self.provider([Response([],error=requests.ReadTimeout('URL?apiKey=TEST_SECRET_NEVER_LOG'))])
        token=self.g.claim(job,'worker',NOW)
        with self.assertRaises(RuntimeError) as error:p.odds(self.g,job,token,'worker')
        self.assertNotIn('TEST_SECRET_NEVER_LOG',str(error.exception))
        self.assertEqual(len(s.calls),1)
        self.g.unknown(token,'worker',NOW)
        self.assertEqual(self.g.status()['unknown_attempts'],1)

    def test_discovery_expands_tennis_and_checks_zero_cost_without_cap(self):
        nba=[{**event(),'id':f'event{i}'} for i in range(25)]
        tennis={**event(),'sport_key':'tennis_atp_test'}
        catalog=[{'key':'basketball_nba','active':True},{'key':'tennis_atp_test','active':True},
                 {'key':'basketball_nba_outrights','active':True,'has_outrights':True}]
        p,s=self.provider([Response(catalog,charge='0'),Response(nba,charge='0'),Response([tennis],charge='0')])
        found=p.discover()
        self.assertEqual(found['active_sport_keys'],['basketball_nba','tennis_atp_test'])
        self.assertEqual(len(found['events']),26)
        self.assertEqual(len(s.calls),3)

    def test_nonzero_inventory_charge_stops_discovery(self):
        p,s=self.provider([Response([],charge='1')])
        with self.assertRaises(RuntimeError):p.discover()
        self.assertEqual(len(s.calls),1)

    def test_simulation_reservations_cannot_authorize_live_calls_or_publication(self):
        g=Governor(Path(self.tmp.name)/'simulation.sqlite3')
        try:
            g.configure_cycle('simulation-test',NOW-timedelta(days=1),NOW+timedelta(days=1))
            g.acquire('worker',NOW)
            job=self.jobs[0];token=g.claim(job,'worker',NOW)
            p,s=self.provider([])
            with self.assertRaises(Refused):p.odds(g,job,token,'worker')
            self.assertEqual(s.calls,[])
            g.finish(job,token,'worker',NOW,{'x-requests-last':'3','x-requests-remaining':'14999990'},[])
            record=json.loads(g.db.execute('SELECT payload FROM publication_outbox').fetchone()[0])
            publisher=MainPublisher(Path(self.tmp.name)/'captures',lambda:None,lambda *a,**k:None)
            with self.assertRaises(ValueError):publisher(token,record)
        finally:g.close()

    def settle(self,job):
        token=self.g.claim(job,'worker',NOW)
        self.g.finish(job,token,'worker',NOW,{'x-requests-last':str(job.cost),'x-requests-remaining':'14999990'},[self.priced(job)])
        return token

    def test_main_outbox_retries_publication_without_provider_refetch(self):
        self.settle(self.jobs[0]);calls=[]
        def fail(token,record):calls.append(token);raise RuntimeError('database unavailable')
        with self.assertRaises(RuntimeError):self.g.publish_pending('worker',NOW,fail)
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM publication_outbox WHERE published_at IS NULL').fetchone()[0],1)
        delivered=[]
        self.assertEqual(self.g.publish_pending('worker',NOW,lambda token,record:delivered.append(token)),1)
        self.assertEqual(self.g.publish_pending('worker',NOW,lambda *args:None),0)
        self.assertEqual(len(delivered),1)
        self.assertEqual(self.g.status()['cycles'][0]['accounted']['main'],3)

    def test_retained_manifest_replay_is_identical_and_uses_injected_writer(self):
        token=self.settle(self.jobs[0]);records=[];connect=object()
        def ingest(folder,*,connect):
            manifest=json.loads((folder/'manifest.json').read_text())
            self.assertEqual(hashlib.sha256((folder/'response.body').read_bytes()).hexdigest(),manifest['sha256'])
            self.assertEqual(manifest['parameters']['bookmakers'],','.join(self.jobs[0].books))
            records.append((manifest,connect))
        publisher=MainPublisher(Path(self.tmp.name)/'captures',connect,ingest)
        raw=json.loads(self.g.db.execute('SELECT payload FROM publication_outbox WHERE token=?',(token,)).fetchone()[0])
        publisher(token,raw);publisher(token,raw)
        self.assertEqual(records[0],records[1]);self.assertIs(records[0][1],connect)
        bad={**raw,'captured_at':(NOW+timedelta(seconds=1)).isoformat()}
        with self.assertRaises(ValueError):publisher(token,bad)

    def test_props_read_preserves_groups_and_expires_without_json_writer(self):
        self.settle(self.jobs[2]);self.settle(self.jobs[3])
        data=read_props(self.g.path,NOW)
        quotes=data['events']['event1']['markets']['player_points']['quotes']
        self.assertEqual({q['book'] for q in quotes},{'draftkings','novig'})
        later=read_props(self.g.path,NOW+timedelta(seconds=61))
        quotes=later['events']['event1']['markets']['player_points']['quotes']
        self.assertEqual({q['book'] for q in quotes},{'draftkings'})
        self.assertEqual(read_props(self.g.path,NOW+timedelta(seconds=181)),{'events':{}})

    def test_simulation_store_cannot_be_a_member_props_source(self):
        with self.assertRaises(ValueError):read_props(Path(self.tmp.name)/'collection-simulation.sqlite3',NOW)

    def row(self,book,at=NOW,payload='old'):
        return {'event_id':'canonical-event','source_event_id':'event1',
                'book_code':book,'market_code':'moneyline',
                'observed_at':at,'provider_updated_at':at,'provider_payload_id':payload}

    def test_scheduled_reader_keeps_both_groups_and_drops_old_capture_rows(self):
        self.settle(self.jobs[0]);self.settle(self.jobs[1])
        rows=[self.row('draftkings'),self.row('novig'),self.row('draftkings',NOW-timedelta(seconds=1),'older')]
        selected=main_scopes(rows,self.g.path,NOW)
        self.assertEqual(len(selected),2)
        with patch.dict(os.environ,{'CORNER_PRIVATE_BETA':'1','CORNER_COLLECTION_DB':str(self.g.path)}):
            self.assertEqual(keep_latest_capture(selected),selected)
        self.assertEqual(main_scopes(rows,self.g.path,NOW+timedelta(seconds=61)),[rows[0]])

    def test_withdrawn_book_scope_cannot_survive_in_postgres_rows(self):
        self.settle(self.jobs[0]);self.settle(self.jobs[1])
        rows=[self.row('draftkings'),self.row('novig')]
        later=NOW+timedelta(seconds=60)
        self.g.acquire('worker',later)
        self.g.prepare_due(self.jobs[0],'worker',later)
        token=self.g.claim(self.jobs[0],'worker',later)
        self.g.finish(self.jobs[0],token,'worker',later,{'x-requests-last':'0','x-requests-remaining':'14999990'},[])
        # The standard scope is gone immediately; the old canonical row is not a fallback.
        self.assertFalse(any(r['book_code']=='draftkings' for r in main_scopes(rows,self.g.path,later)))

    def test_local_workflow_ignores_scheduled_store_and_simulation_is_rejected(self):
        with patch.dict(os.environ,{'CORNER_PRIVATE_BETA':'0','CORNER_COLLECTION_DB':str(self.g.path)}):
            self.assertIsNone(store_path())
        with patch.dict(os.environ,{'CORNER_PRIVATE_BETA':'1','CORNER_COLLECTION_DB':'collection-simulation.sqlite3'}):
            with self.assertRaises(ValueError):store_path()


if __name__=='__main__':unittest.main()
