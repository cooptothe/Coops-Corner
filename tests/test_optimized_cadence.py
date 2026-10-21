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
        for begin,end,expected_events in [('2026-11-01','2026-12-01',73),
                                         ('2026-10-01','2026-11-01',50),
                                         ('2027-02-01','2027-03-01',75)]:
            start=datetime.fromisoformat(begin).replace(tzinfo=timezone.utc)
            stop=datetime.fromisoformat(end).replace(tzinfo=timezone.utc)
            events,credits=additional_limits(start,stop)
            days=(stop-start).days
            self.assertEqual(events,expected_events)
            self.assertLessEqual(credits,30000)
            self.assertLessEqual(82*960*3*days+credits*(days+1),POOLS['main'])
            self.assertLessEqual(events*72*5,credits)
        self.assertEqual(sum(POOLS.values()),TOTAL-PROTECTED)
        self.assertEqual(PROTECTED,1500000)

    def test_standard_floors_and_distant_bands(self):
        for month,far in [(10,180),(11,150),(2,150)]:
            now=datetime(2026,month,15,16,tzinfo=timezone.utc)
            for remaining in (1,3600,7200,21600):
                self.assertEqual(interval('props','standard',now,now+timedelta(seconds=remaining)),60)
            self.assertEqual(interval('props','standard',now,now+timedelta(seconds=21601)),far)
            for remaining in (1,3600,3601,7200):
                expected=60 if remaining<=3600 else 300
                self.assertEqual(interval('additional','standard',now,now+timedelta(seconds=remaining)),expected)
            self.assertEqual(interval('main','standard',now),60)

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
