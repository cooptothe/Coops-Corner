from datetime import timedelta
import unittest
from corner.collection_policy import interval, COUNTDOWN_BANDS, EXCHANGE_COUNTDOWN_BANDS, ADDITIONAL_POLLS_PER_GROUP, additional_limits, parse, POOLS, CENTRAL
from corner.live_pacing import plan

NOW=parse('2026-11-02T15:00:00Z')

class NovemberCadence(unittest.TestCase):
    def test_all_edges_and_provider_floors(self):
        for group in ('standard','exchange'):
            for kind,standard in COUNTDOWN_BANDS.items():
                bands=EXCHANGE_COUNTDOWN_BANDS.get(kind,standard) if group=='exchange' else standard
                lower=1
                for upper,period in bands:
                    for seconds in (lower,upper):
                        self.assertEqual(interval(kind,group,NOW,NOW+timedelta(seconds=seconds)),period)
                        self.assertGreaterEqual(period,20 if group=='exchange' else 60)
                    lower=upper+1
        self.assertEqual(interval('main','standard',NOW),900)

    def test_alternate_admission_covers_transition_polls(self):
        self.assertEqual(ADDITIONAL_POLLS_PER_GROUP,45)
        events,credits=additional_limits(parse('2026-11-01T00:00:00Z'),parse('2026-12-01T00:00:00Z'))
        self.assertLessEqual(events*2*ADDITIONAL_POLLS_PER_GROUP*5,credits)
        self.assertEqual(POOLS['props'],9500000)

    def test_live_budget_does_not_plan_past_10pm(self):
        for day in ('2026-11-01','2027-03-14'):
            from datetime import datetime
            now=CENTRAL.localize(datetime.fromisoformat(day+'T21:00:00'))
            result=plan(now,now+timedelta(days=20),{'live_events':[dict(sport_key='basketball_nba',commence_time=now.isoformat())]},spent_month=0,spent_today=0,monthly_cap=500000,daily_cap=20000,available_main=7900000)
            self.assertEqual(result['forecast_league_hours_remaining'],1)
            self.assertGreaterEqual(result['interval_seconds']['standard'],40)
            self.assertGreaterEqual(result['interval_seconds']['exchange'],10)
