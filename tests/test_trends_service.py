from datetime import datetime,timezone
from pathlib import Path
from contextlib import closing
import tempfile
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse
from pipelines.trends_service import Trends, ResearchUnavailable, normalize_games, contracts, create_router
from pipelines.media import UpstreamError

NOW = datetime(2030,2,1,tzinfo=timezone.utc).timestamp()
CONTRACT = dict(id='id',player='Test Player',sport_key='basketball_nba',market_key='player_points',point='10.5',side='Over',price='2',commission='0',home='Home Team',away='Away Team',starts_at='2030-02-02T00:00:00Z')


def payload():
    return {'names':['minutes','points','totalRebounds'],
            'events':{'game':{'gameResult':'W','gameDate':'2030-01-30T00:00:00Z','atVs':'vs','opponent':{'displayName':'Away Team'},'links':[]}},
            'seasonTypes':[{'displayName':'2030 Regular Season','displayTeam':'HOME','categories':[{'type':'event','events':[{'eventId':'game','stats':['30','20','5']}]}]}]}


class Sources(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.calls=[]
        self.now=NOW
        self.service=Trends(Path(self.tmp.name)/'cache.sqlite3',self.fetch,lambda:self.now)

    def fetch(self,url,params=None):
        self.calls.append((url,params))
        if url.endswith('/search'):
            return {'items':[{'id':'123','displayName':'Test Player','sport':'basketball','league':'nba','teamRelationships':[{'core':{'displayName':'Home Team'}}]}]}
        if url.endswith('/gamelog'): return payload()
        if url.endswith('/overview'):return {'news':[]}
        return {'articles':[]}

    def test_normalization_regular_season_only_and_composite_market(self):
        data=payload()
        self.assertEqual(normalize_games(data,'basketball_nba','player_points_rebounds',2030)[0]['value'],'25.0')
        data['seasonTypes'][0]['displayName']='2030 Preseason'
        self.assertEqual(normalize_games(data,'basketball_nba','player_points',2030),[])

    def test_supported_league_stat_mappings_do_not_invent_missing_values(self):
        cases=[('americanfootball_nfl','player_pass_yds',['passingYards','passingAttempts'],['200','30'],'200.0'),
               ('icehockey_nhl','player_shots_on_goal',['shotsTotal','timeOnIcePerGame'],['3','22:30'],'3.0'),
               ('baseball_mlb','batter_hits',['hits','atBats'],['1','4'],'1.0'),
               ('basketball_wnba','player_points',['points','minutes'],['18','32'],'18.0')]
        for sport,market,names,stats,expected in cases:
            data=payload();data['names']=names
            data['seasonTypes'][0]['categories'][0]['events'][0]['stats']=stats
            with self.subTest(sport=sport):self.assertEqual(normalize_games(data,sport,market,2030)[0]['value'],expected)
            data['seasonTypes'][0]['categories'][0]['events'][0]['stats'][0]='--'
            self.assertEqual(normalize_games(data,sport,market,2030),[])

    def test_shared_cache_reuses_data_and_never_spends_odds_credits(self):
        result=self.service.research(CONTRACT)
        count=len(self.calls)
        again=self.service.research(CONTRACT)
        self.assertEqual(count,len(self.calls))
        self.assertEqual(result['windows']['1']['wins'],1)
        self.assertFalse(again['research_signal'])
        self.assertTrue(all('espn.com' in url for url,_ in self.calls))

    def test_identity_ambiguity_and_team_mismatch_fail_closed(self):
        self.service.fetch=lambda *args,**kwargs:{'items':[]}
        with self.assertRaises(ResearchUnavailable):self.service.research(CONTRACT)
        self.now+=121
        self.service.fetch=self.fetch
        wrong={**CONTRACT,'home':'Different Team','away':'Other Team'}
        with self.assertRaises(ResearchUnavailable):self.service.research(wrong)

    def test_outage_negative_cache_and_hourly_budget(self):
        attempts=[]
        def fail():attempts.append(1);raise UpstreamError('down')
        with self.assertRaises(ResearchUnavailable):self.service.cached('failure',3600,fail)
        data,_=self.service.cached('failure',3600,fail)
        self.assertTrue(data['_unavailable'])
        self.assertEqual(len(attempts),1)
        with closing(self.service._db()) as db:
            db.execute('UPDATE budget SET calls=240');db.commit()
        with self.assertRaises(ResearchUnavailable):self.service.cached('new',3600,lambda:{})

    def test_news_failure_does_not_claim_no_injuries(self):
        original=self.fetch
        def fetch(url,params=None):
            if url.endswith('/overview'):raise UpstreamError('down')
            return original(url,params)
        self.service.fetch=fetch
        result=self.service.research(CONTRACT)
        self.assertEqual(result['news_status'],'unavailable')
        self.assertFalse(result['research_signal'])

    def test_unknown_sport_or_market_never_fetches(self):
        for change in ({'sport_key':'soccer_epl'},{'market_key':'unrecognized'}):
            with self.assertRaises(ResearchUnavailable):self.service.research({**CONTRACT,**change})
        self.assertEqual(self.calls,[])

    def test_nfl_winter_uses_the_season_that_started_in_the_previous_year(self):
        with patch.object(self.service,'identity',return_value={'id':'123','name':'Test Player','team':'Home Team'}):
            self.service.research({**CONTRACT,'sport_key':'americanfootball_nfl','market_key':'player_pass_yds'})
        years=[params['season'] for url,params in self.calls if url.endswith('/gamelog')]
        self.assertEqual(years,[2029,2028])

    def test_cache_only_scan_does_not_trigger_network_or_change_budget(self):
        with self.assertRaises(ResearchUnavailable):self.service.research(CONTRACT,cached_only=True)
        self.assertEqual(self.calls,[])
        self.service.research(CONTRACT)
        before=len(self.calls)
        self.service.research(CONTRACT,cached_only=True)
        self.assertEqual(before,len(self.calls))

    def test_future_news_and_untrusted_links_are_excluded_and_injury_news_flags_review(self):
        original=self.fetch
        def fetch(url,params=None):
            if url.endswith('/overview'):
                return {'news':[
                    {'headline':'Test Player questionable after injury','published':'2030-01-31T00:00:00Z','links':{'web':{'href':'https://www.espn.com/nba/story/_/id/123'}}},
                    {'headline':'Future news','published':'2030-02-02T00:00:00Z','links':{'web':{'href':'https://www.espn.com/nba/story/_/id/124'}}},
                    {'headline':'Untrusted','published':'2030-01-31T00:00:00Z','links':{'web':{'href':'https://example.invalid/news'}}}]}
            return original(url,params)
        self.service.fetch=fetch
        result=self.service.research(CONTRACT)
        self.assertEqual(len(result['news']),1)
        self.assertTrue(any('availability-related' in flag for flag in result['flags']))
        self.assertFalse(result['research_signal'])


class Access(unittest.TestCase):
    def test_quote_change_during_fetch_requires_review(self):
        class Context:
            def require(self,request,*,write):return {},None
        class Service:
            def research(self,item):return {'research_signal':True}
        app=FastAPI();app.include_router(create_router(Context(),Service()))
        client=TestClient(app)
        with patch('pipelines.trends_service.contracts',side_effect=[{'id':CONTRACT},{'id':{**CONTRACT,'price':'1.5'}}]):
            self.assertEqual(client.get('/api/refresh/v1/props/trends?id=id').status_code,409)

    def test_one_sided_retained_quote_is_researchable_without_reference_books(self):
        now=datetime.now(timezone.utc).isoformat()
        data={'events':{'e':{'sport_key':'basketball_nba','home_team':'Home Team','away_team':'Away Team','commence_time':'2030-02-02T00:00:00Z',
              'markets':{'player_points':{'captured_at':now,'quotes':[{'book':'draftkings','player':'Test Player','point':'10.5','side':0,'price':'2'}]}}}}}
        with patch('pipelines.props_ingestion.load',return_value=data):
            result=contracts()
        self.assertEqual(len(result),1)
        self.assertEqual(next(iter(result.values()))['player'],'Test Player')
        # Conflicting duplicate target evidence is not resolved by choosing a convenient price.
        quotes=data['events']['e']['markets']['player_points']['quotes']
        quotes.append({**quotes[0],'price':'3'})
        with patch('pipelines.props_ingestion.load',return_value=data):self.assertEqual(contracts(),{})

    def test_anonymous_cannot_trigger_source_calls_and_expired_quote_never_fetches(self):
        class Context:
            allowed=False
            def require(self,request,*,write):
                return ({},None) if self.allowed else (None,JSONResponse({},status_code=401))
        ctx=Context();app=FastAPI();app.include_router(create_router(ctx))
        client=TestClient(app)
        with patch('pipelines.trends_service.contracts',return_value={}) as lookup:
            self.assertEqual(client.get('/api/refresh/v1/props/trends/options').status_code,401)
            lookup.assert_not_called()
            ctx.allowed=True
            self.assertEqual(client.get('/api/refresh/v1/props/trends?id=unknown').status_code,404)
