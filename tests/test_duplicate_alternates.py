import copy
import hashlib
import json
import tempfile
import unittest
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from corner.featured_markets import normalize_featured_payload, FeaturedMarketError
from corner.collection_policy import Job, STANDARD
from corner.additional_markets import SCHEDULED_ADDITIONAL_MARKETS
from pipelines.collection_publication import MainPublisher

NOW=datetime(2030,1,1,15,tzinfo=timezone.utc)

def event():
    return {'id':'event1','sport_key':'basketball_nba', 'home_team':'Home','away_team':'Away',
        'commence_time':(NOW+timedelta(hours=1)).isoformat(),'bookmakers':[
            {'key':book,'title':book,'last_update':NOW.isoformat(),'markets':[
                {'key':'alternate_totals','outcomes':[
                    {'name':'Over','point':200.5,'price':1.91},
                    {'name':'Under','point':200.5,'price':1.91},
                    {'name':'Over','point':201.5,'price':2.0},
                    {'name':'Under','point':201.5,'price':1.8}]}]}
            for book in ('draftkings','fanduel')]}

class DuplicateAlternates(unittest.TestCase):
    def normalize(self, payload):
        raw=json.dumps(payload,separators=(',',':')).encode()
        result=normalize_featured_payload(raw,received_at=NOW)
        self.assertEqual(result.payload_sha256,hashlib.sha256(raw).hexdigest())
        for quote in result.quotes:
            source=payload
            for part in quote.source_pointer.split('/')[1:]:
                source=source[int(part)] if isinstance(source,list) else source[part]
            self.assertEqual(str(quote.decimal_odds),str(source['price']))
        return result

    def test_same_and_conflicting_prices_exclude_all_copies_only(self):
        for price in (1.91,3.5):
            data=[event()];market=data[0]['bookmakers'][0]['markets'][0]
            duplicate={**market['outcomes'][0],'price':price,'sid':'another-id'}
            market['outcomes'].append(duplicate)
            result=self.normalize(data)
            self.assertEqual(len(result.quotes),7)
            self.assertFalse(any(q.bookmaker_key=='draftkings' and q.point==200.5 and q.selection_side=='over' for q in result.quotes))
            self.assertEqual(len([q for q in result.quotes if q.bookmaker_key=='fanduel']),4)
            self.assertTrue(any(e.reason=='ambiguous_duplicate_quote_identity_excluded' for e in result.excluded_markets))
            self.assertEqual(result,self.normalize(data))

    def test_repeated_market_blocks_exclude_ambiguous_lines_without_blocking_other_books(self):
        data=[event()]
        data[0]['bookmakers'][0]['markets'].append(copy.deepcopy(data[0]['bookmakers'][0]['markets'][0]))
        result=self.normalize(data)
        self.assertEqual(len(result.quotes),4)
        self.assertTrue(all(q.bookmaker_key=='fanduel' for q in result.quotes))

    def test_team_total_subjects_remain_distinct(self):
        data=[event()];market=data[0]['bookmakers'][0]['markets'][0]
        market['key']='team_totals'
        for outcome in market['outcomes']:outcome['description']='Home'
        market['outcomes'].append({**market['outcomes'][0],'description':'Away'})
        self.assertEqual(len(self.normalize(data).quotes),9)
        market['outcomes'].append(copy.deepcopy(market['outcomes'][0]))
        result=self.normalize(data)
        self.assertTrue(any(q.subject_name=='Away' and q.selection_side=='over' for q in result.quotes))
        self.assertFalse(any(q.subject_name=='Home' and q.point==200.5 and q.selection_side=='over' for q in result.quotes))

    def test_main_line_duplicate_and_structural_ambiguity_still_rejected(self):
        for key in ('totals','h2h'):
            data=[event()];market=data[0]['bookmakers'][0]['markets'][0];market['key']=key
            if key=='h2h':market['outcomes']=[{'name':'Home','price':1.91},{'name':'Away','price':1.91}]
            market['outcomes'].append(copy.deepcopy(market['outcomes'][0]))
            with self.assertRaises(FeaturedMarketError):self.normalize(data)

    def test_saved_capture_publication_is_repeatable_and_does_not_rewrite_evidence(self):
        data=event();market=data['bookmakers'][0]['markets'][0]
        market['outcomes'].append({**market['outcomes'][0],'price':3.5})
        job=Job('additional','basketball_nba','standard',STANDARD,SCHEDULED_ADDITIONAL_MARKETS,'event1',data['commence_time'])
        record={'job':asdict(job),'events':[data],'captured_at':NOW.isoformat()}
        observed=[]
        with tempfile.TemporaryDirectory() as folder:
            def ingest(path,**kwargs):
                raw=(path/'response.body').read_bytes()
                observed.append(normalize_featured_payload(raw,received_at=NOW))
            publisher=MainPublisher(folder,lambda:None,ingest)
            publisher('a'*48,record)
            original=(Path(folder)/('a'*48)/'response.body').read_bytes()
            publisher('a'*48,record)
            self.assertEqual(original,(Path(folder)/('a'*48)/'response.body').read_bytes())
            self.assertEqual(observed[0],observed[1])
            self.assertEqual(len(observed[0].quotes),7)
