import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from api.app import create_app
from api.catalog import FixtureCatalog
from api.database import build_raw
from corner.prop_tools import merge_props
from corner.featured_markets import normalize_featured_payload


class LargeToolPages(unittest.TestCase):
    def test_middle_pages_past_ten_thousand_are_complete_and_still_bounded(self):
        catalog=FixtureCatalog()
        row=next(r for r in catalog.rows if r.kind=='middle')
        rows=tuple(row.model_copy(update={'id':f'middle:{i:06d}'}) for i in range(12050))
        with patch.object(catalog,'rows',rows),patch.object(catalog,'memo',{}),TestClient(create_app(catalog=catalog),base_url='http://127.0.0.1') as client:
            response=client.get('/api/v1/tools/middle',params={'offset':11000,'limit':1000,'snapshot_id':catalog.snapshot_id})
            self.assertEqual(response.status_code,200,response.text)
            page=response.json()['data']
            self.assertEqual((page['total'],len(page['items']),page['next_offset']),(12050,1000,12000))
            self.assertEqual(page['items'][0]['id'],'middle:011000')
            last=client.get('/api/v1/tools/middle',params={'offset':12000,'limit':1000}).json()['data']
            self.assertEqual((len(last['items']),last['next_offset']),(50,None))
            for params in ({'offset':100001},{'limit':1001},{'limit':0},{'offset':-1}):
                self.assertEqual(client.get('/api/v1/tools/middle',params=params).status_code,422)
            self.assertEqual(client.get('/api/v1/games',params={'limit':101}).status_code,422)

    def test_prop_games_use_short_league_labels(self):
        now=datetime.now(timezone.utc)
        for sport,label in [('americanfootball_nfl','NFL'),('baseball_mlb','MLB'),('icehockey_nhl','NHL')]:
            market='player_pass_yds' if label=='NFL' else 'batter_hits' if label=='MLB' else 'player_shots_on_goal'
            data={'events':{'provider':dict(sport_key=sport,home_team='H',away_team='A',commence_time=(now+timedelta(hours=1)).isoformat(),markets={market:dict(captured_at=now.isoformat(),quotes=[dict(book='draftkings',player='P',point='1.5',side=s,price='2') for s in (0,1)])})}}
            raw=merge_props(build_raw([],[],now=now),now=now,data=data)
            self.assertEqual(raw['games'][0]['competition'],label)

    def test_ambiguous_peer_offers_excluded_without_rejecting_other_quotes(self):
        now=datetime.now(timezone.utc)
        event=dict(id='e',sport_key='americanfootball_nfl',home_team='H',away_team='A',commence_time=(now+timedelta(hours=1)).isoformat(),bookmakers=[])
        def book(key):
            return dict(key=key,markets=[dict(key='alternate_spreads',outcomes=[dict(name='H',point=-3.5,price=2),dict(name='A',point=3.5,price=2)])])
        target=book('betopenly');target['markets'][0]['outcomes'].append(dict(name='H',point=-3.5,price=2.2))
        event['bookmakers']=[target,book('draftkings'),book('pinnacle')]
        original=copy.deepcopy(event);raw=json.dumps([event]).encode()
        snapshot=normalize_featured_payload(raw,received_at=now)
        self.assertEqual(snapshot.payload_sha256,hashlib.sha256(raw).hexdigest())
        self.assertEqual(event,original)
        self.assertFalse(any(q.bookmaker_key=='betopenly' and q.selection_side=='home' for q in snapshot.quotes))
        self.assertEqual(sum(q.bookmaker_key=='draftkings' for q in snapshot.quotes),2)
        self.assertEqual(sum(q.bookmaker_key=='pinnacle' for q in snapshot.quotes),2)
        self.assertTrue(any(e.reason=='ambiguous_peer_offers_excluded' for e in snapshot.excluded_markets))

if __name__=='__main__':unittest.main()
