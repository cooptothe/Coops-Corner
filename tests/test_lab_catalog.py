import json
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
from corner.lab_catalog import remember
from pipelines.collection_publication import read_props
from pipelines.trends_service import contracts

NOW=datetime(2030,1,20,tzinfo=timezone.utc)

class LabCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'catalog.sqlite3'
        self.item={'id':'saved','player':'Player','starts_at':(NOW+timedelta(days=1)).isoformat(),'observed_at':NOW.isoformat(),'point':'20.5','price':'2','commission':'0','links':{'outcome':'example'},'quote_status':'current'}
    def test_catalog_survives_empty_feed_and_process_reopen_without_retimestamping(self):
        remember({'saved':self.item},self.path,NOW.timestamp())
        saved=remember({},self.path,(NOW+timedelta(hours=1)).timestamp())['saved']
        self.assertEqual(saved['observed_at'],self.item['observed_at'])
        self.assertEqual(saved['quote_status'],'stale');self.assertIsNone(saved['commission']);self.assertIsNone(saved['links'])
        self.assertTrue(remember({},self.path,(NOW+timedelta(days=90)).timestamp()))
    def test_newer_quote_replaces_saved_price_but_older_capture_cannot_roll_it_back(self):
        remember({'saved':self.item},self.path,NOW.timestamp())
        new={**self.item,'price':'2.2','observed_at':(NOW+timedelta(minutes=1)).isoformat()}
        remember({'saved':new},self.path,NOW.timestamp()+60)
        # Empty current feed must recover the most recently observed saved price.
        self.assertEqual(remember({},self.path,NOW.timestamp()+120)['saved']['price'],'2.2')
        remember({'saved':self.item},self.path,NOW.timestamp()+120)
        self.assertEqual(remember({},self.path,NOW.timestamp()+180)['saved']['price'],'2.2')
    def test_expired_and_started_scopes_are_researchable_but_not_feed_eligible(self):
        dbpath=Path(self.temp.name)/'collection-live.sqlite3'
        part={'event':{'id':'e','sport_key':'basketball_nba','home_team':'Home','away_team':'Away','commence_time':(NOW+timedelta(hours=1)).isoformat()},'book':{'key':'draftkings','last_update':(NOW-timedelta(hours=2)).isoformat()},'market':{'key':'player_points','last_update':(NOW-timedelta(hours=2)).isoformat(),'outcomes':[{'name':'Over','description':'Player','point':20.5,'price':2}]}}
        with closing(sqlite3.connect(dbpath)) as db, db:
            db.execute('CREATE TABLE snapshots(kind,sport,event_id,captured_at,payload,expires_at,starts_at,market,book)')
            db.execute('INSERT INTO snapshots VALUES(?,?,?,?,?,?,?,?,?)',('props','basketball_nba','e',NOW.timestamp()-7200,json.dumps(part),NOW.timestamp()-5400,NOW.timestamp()+3600,'player_points','draftkings'))
        self.assertFalse(read_props(dbpath,NOW)['events'])
        self.assertTrue(read_props(dbpath,NOW,research=True)['events'])
        self.assertTrue(read_props(dbpath,NOW+timedelta(days=2),research=True)['events'])
        with closing(sqlite3.connect(dbpath)) as db, db:
            db.execute('CREATE TABLE clv_scopes AS SELECT * FROM snapshots')
            db.execute('DELETE FROM snapshots')
        archived=read_props(dbpath,NOW,research=True)
        self.assertTrue(archived['events'])
        self.assertFalse(archived['events']['e']['markets']['player_points']['quotes'][0]['_research_active'])
        self.assertFalse(read_props(dbpath,NOW)['events'])
    def test_stale_contracts_keep_their_original_line_without_executable_fees(self):
        old=(datetime.now(timezone.utc)-timedelta(hours=3)).isoformat()
        data={'events':{'e':{'sport_key':'basketball_nba','home_team':'Home','away_team':'Away','commence_time':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),'markets':{'player_points':{'captured_at':old,'quotes':[{'book':'draftkings','player':'Player','side':0,'point':'20.5','price':'2','updated_at':old}]}}}}}
        with patch('pipelines.props_ingestion.load',return_value=data),patch('corner.collection_readers.store_path',return_value=None):
            found=contracts(research=True)
        item=next(iter(found.values()))
        self.assertEqual(item['quote_status'],'stale');self.assertEqual(item['point'],'20.5');self.assertEqual(item['observed_at'],old);self.assertIsNone(item['commission'])
