from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import tempfile
import unittest

from corner.collection_policy import (additional_limits, interval, POOLS, TOTAL,
    PROTECTED, STANDARD, Job, CENTRAL)
from corner.additional_markets import SCHEDULED_ADDITIONAL_MARKETS
from corner.credit_governor import Governor, Refused
from tests.test_collection_adapters import Session, Response, NOW
from pipelines.collection_provider import Provider


class OptimizedCadence(unittest.TestCase):
    def test_month_lengths_budget_partial_central_dates(self):
        for begin,end,expected_events in [('2026-11-01','2026-12-01',66),
                                         ('2026-10-01','2026-11-01',66),
                                         ('2027-02-01','2027-03-01',66)]:
            start=datetime.fromisoformat(begin).replace(tzinfo=timezone.utc)
            stop=datetime.fromisoformat(end).replace(tzinfo=timezone.utc)
            events,credits=additional_limits(start,stop)
            days=(stop-start).days
            self.assertEqual(events,expected_events)
            self.assertLessEqual(credits,30000)
            self.assertLessEqual(credits*(days+1),POOLS['main'])
            self.assertLessEqual(events*90*5,credits)
        self.assertEqual(sum(POOLS.values()),TOTAL-PROTECTED)
        self.assertEqual(PROTECTED,0)

    def test_standard_floors_and_distant_bands(self):
        now=datetime(2026,11,15,16,tzinfo=timezone.utc)
        for group in ('standard','exchange'):
            for remaining, expected in [(1,60),(7200,60),(7201,60),(14401,120),(21601,180),(43201,300)]:
                self.assertEqual(interval('props',group,now,now+timedelta(seconds=remaining)),expected)
            for remaining, expected in [(1,60),(900,90),(901,90),(1801,180),(3601,480)]:
                self.assertEqual(interval('additional',group,now,now+timedelta(seconds=remaining)),expected)
            self.assertEqual(interval('main',group,now),900)


    def test_daily_caps_refuse_extra_events_and_credit_reservations(self):
        now=datetime(2026,11,15,16,tzinfo=timezone.utc)
        begin=datetime(2026,11,1,tzinfo=timezone.utc)
        end=datetime(2026,12,1,tzinfo=timezone.utc)
        event_limit,credit_limit=additional_limits(begin,end)
        def job(key):
            return Job('additional','basketball_nba','standard',STANDARD,
                       SCHEDULED_ADDITIONAL_MARKETS,key,(now+timedelta(minutes=45)).isoformat())
        with tempfile.TemporaryDirectory() as folder:
            g=Governor(Path(folder)/'ledger.sqlite3')
            try:
                g.configure_cycle('nov',begin,end);g.acquire('worker',now)
                day=now.astimezone(CENTRAL).date().isoformat()
                g.db.executemany('INSERT INTO additional_events VALUES(?,?,?)',
                                [(day,'basketball_nba',str(i)) for i in range(event_limit)])
                with self.assertRaisesRegex(Refused,'event cap'):g.claim(job('extra'),'worker',now)
                token=g.claim(job('0'),'worker',now)
                # Synthetic settled spend at the cap; no network or real ledger.
                g.db.execute("UPDATE attempts SET state='settled',actual=? WHERE token=?",(credit_limit,token))
                with self.assertRaisesRegex(Refused,'credit cap'):g.claim(job('1'),'worker',now)
            finally:g.close()

    def test_provider_spaces_inventory_and_odds_without_retry(self):
        session=Session([Response([],charge='0'),Response([],charge='0')])
        provider=Provider(key='synthetic-key',enabled=True,session=session,clock=lambda:NOW)
        with patch('pipelines.collection_provider.time.monotonic',return_value=100.0), \
             patch('pipelines.collection_provider.time.sleep') as sleep:
            provider._get('/',{})
            provider._get('/basketball_nba/events',{})
        sleep.assert_called_once()
        self.assertAlmostEqual(sleep.call_args.args[0],0.1)
        self.assertEqual(len(session.calls),2)
