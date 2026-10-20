from datetime import timedelta
import unittest

from corner.collection_policy import interval, plan, snapshot_max_age, POOLS, PROTECTED, TOTAL
from tests.test_collection_adapters import event, NOW


class RevisedScheduleTests(unittest.TestCase):
    def test_exact_bands(self):
        for seconds, expected in [(1,60),(900,60),(901,60),(7200,60),(7201,300),(21600,300),(21601,3600)]:
            self.assertEqual(interval('props','standard',NOW,NOW+timedelta(seconds=seconds)),expected)
        self.assertEqual(interval('main','standard',NOW),300)
        self.assertEqual(interval('additional','standard',NOW),120)
        self.assertEqual(snapshot_max_age('main','standard'),360)
        self.assertEqual(snapshot_max_age('additional','standard'),180)
        self.assertEqual(snapshot_max_age('props','standard'),180)
        self.assertEqual(snapshot_max_age('main','exchange'),60)

    def test_main_bands_follow_soonest_upcoming_game(self):
        for seconds, expected in [(7200,300),(7201,900),(21600,900),(21601,3600)]:
            e={**event(),'commence_time':(NOW+timedelta(seconds=seconds)).isoformat()}
            job=plan(NOW,['basketball_nba'],[e])[0]
            from corner.collection_policy import parse
            self.assertEqual(interval('main','standard',NOW,parse(job.starts_at)),expected)
            later={**e,'id':'later','commence_time':(NOW+timedelta(hours=20)).isoformat()}
            self.assertEqual(plan(NOW,['basketball_nba'],[later,e])[0].starts_at,job.starts_at)

    def test_no_college_props_but_main_and_additional_remain(self):
        from corner.collection_policy import NO_SCHEDULED_PROPS
        for sport in NO_SCHEDULED_PROPS:
            e={**event(),'sport_key':sport,'commence_time':(NOW+timedelta(minutes=45)).isoformat()}
            jobs=plan(NOW,[sport],[e],additional=True)
            self.assertFalse(any(j.kind=='props' for j in jobs))
            self.assertEqual({j.kind for j in jobs},{'main','additional'})

    def test_college_prop_claim_is_invalid_even_if_constructed_directly(self):
        from corner.collection_policy import Job, PROP_STANDARD, FAMILIES, family, NO_SCHEDULED_PROPS
        for sport in NO_SCHEDULED_PROPS:
            job=Job('props',sport,'standard',PROP_STANDARD,
                    tuple(m.key for m in FAMILIES[family(sport)]),'college',
                    (NOW+timedelta(hours=1)).isoformat())
            with self.assertRaises(ValueError):job.validate()

    def test_additional_final_hour_boundary(self):
        for seconds, expected in [(3600,True),(3601,False),(1,True)]:
            e={**event(),'commence_time':(NOW+timedelta(seconds=seconds)).isoformat()}
            jobs=plan(NOW,['basketball_nba'],[e],additional=True)
            self.assertEqual(any(j.kind=='additional' for j in jobs),expected)
