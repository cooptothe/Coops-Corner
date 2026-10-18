from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from corner.manual_markets import markets_for_event
from pipelines import props_ingestion as props
from pipelines import odds_ingestion as board

NOW=datetime.fromisoformat('2030-01-01T18:00:00+00:00')
MARKETS=('player_points','player_points_alternate')


class ManualDayMarkets(unittest.TestCase):
    def test_chicago_calendar_day_not_utc_day_or_next_24_hours(self):
        now=datetime.fromisoformat('2026-10-18T03:30:00+00:00')
        self.assertEqual(markets_for_event(MARKETS,'2026-10-18T04:30:00Z',now),MARKETS)
        self.assertEqual(markets_for_event(MARKETS,'2026-10-18T05:30:00Z',now),MARKETS[:1])
        now=datetime.fromisoformat('2026-10-18T23:00:00+00:00')
        self.assertEqual(markets_for_event(MARKETS,'2026-10-19T01:00:00Z',now),MARKETS)
        self.assertEqual(markets_for_event(MARKETS,'2026-10-18T22:00:00Z',now),MARKETS[:1])

    def test_daylight_saving_and_both_alternate_key_conventions(self):
        keys=('h2h','alternate_spreads','team_totals','alternate_team_totals','player_threes_alternate')
        now=datetime.fromisoformat('2026-11-01T05:30:00+00:00')
        self.assertEqual(markets_for_event(keys,'2026-11-01T07:30:00Z',now),keys)
        self.assertEqual(markets_for_event(keys,'2026-11-02T07:30:00Z',now),('h2h','team_totals'))

    def test_future_prop_alternates_make_no_paid_request(self):
        events=[dict(id='tomorrow',commence_time=(NOW+timedelta(days=1)).isoformat())]
        with tempfile.TemporaryDirectory() as folder,patch.object(props,'STORE',Path(folder)/'props.json'),patch.object(props,'ODDS_API_KEY','fixture'),patch.object(props,'plan',return_value=(events,{'x-requests-remaining':'100'})),patch.object(props,'fetch') as request:
            result=props.capture('basketball_nba',['player_points_alternate'],1,now=NOW)
            request.assert_not_called()
            self.assertEqual((result['events'],result['planned'],result['credits_used']),(0,0,0))
            self.assertEqual(result['day_of_skipped'],1)

    def test_mixed_props_fetch_standard_future_but_alternates_only_today(self):
        events=[dict(id='today',commence_time=(NOW+timedelta(hours=2)).isoformat()),dict(id='tomorrow',commence_time=(NOW+timedelta(days=1)).isoformat())]
        requested=[]
        def fetch(session,url,params):
            requested.append(tuple(params['markets'].split(',')))
            cost=len(requested[-1])*props.BOOKMAKER_REGIONS
            event=events[len(requested)-1]
            return 200,json.dumps({**event,'home_team':'H','away_team':'A','bookmakers':[]}).encode(),{'x-requests-last':str(cost),'x-requests-remaining':'90'}
        with tempfile.TemporaryDirectory() as folder,patch.object(props,'STORE',Path(folder)/'props.json'),patch.object(props,'ODDS_API_KEY','fixture'),patch.object(props,'plan',return_value=(events,{'x-requests-remaining':'100'})),patch.object(props,'fetch',side_effect=fetch):
            result=props.capture('basketball_nba',list(MARKETS),2,now=NOW)
            self.assertEqual(requested,[MARKETS,MARKETS[:1]])
            self.assertEqual(result['credits_used'],6)

    def test_main_alternates_today_and_standard_additions_later_without_event_cap(self):
        events=[dict(id=str(i),commence_time=(NOW+timedelta(hours=2) if i<5 else NOW+timedelta(days=1)).isoformat()) for i in range(6)]
        requested=[]
        def fetch(session,url,params):
            requested.append(tuple(params['markets'].split(',')))
            event=events[len(requested)-1]
            return 200,json.dumps({**event,'sport_key':'basketball_nba','bookmakers':[]}).encode(),{'x-requests-last':str(len(requested[-1])*board.BOOKMAKER_REGIONS),'x-requests-remaining':'1000'}
        with tempfile.TemporaryDirectory() as folder,patch.object(board,'fetch',side_effect=fetch):
            target=Path(folder);(target/'manifest.json').write_text('{}')
            board.capture_additional(target,'basketball_nba',events,board.PARAMS,{'x-requests-remaining':'1000'},now=NOW)
            self.assertEqual(len(requested),6)
            self.assertTrue(all('alternate_spreads' in keys for keys in requested[:5]))
            self.assertEqual(requested[5],('btts','draw_no_bet','team_totals'))
            self.assertEqual(json.loads((target/'manifest.json').read_text())['planned_credits'],72)

if __name__=='__main__':unittest.main()
