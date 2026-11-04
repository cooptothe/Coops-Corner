from datetime import timedelta
from unittest.mock import patch
import unittest
from corner.collection_policy import interval,provider_floor,parse,POOLS,TOTAL
from corner.credit_governor import RequestNotSent
from pipelines.collection_provider import Provider

NOW=parse('2026-11-04T20:00:00Z')

class ProviderCadenceBudget(unittest.TestCase):
    def test_same_event_uses_distinct_standard_and_exchange_floors(self):
        for kind in ('main','props'):
            at=NOW+timedelta(minutes=15)
            self.assertEqual(interval(kind,'standard',NOW,at),60)
            self.assertEqual(interval(kind,'exchange',NOW,at),20)
        self.assertEqual(provider_floor('live','standard'),40)
        self.assertEqual(provider_floor('live','exchange'),10)

    def test_near_start_freshness_is_funded_by_distant_props(self):
        for group in ('standard','exchange'):
            self.assertEqual(interval('props',group,NOW,NOW+timedelta(hours=18)),600)
            self.assertEqual(interval('props',group,NOW,NOW+timedelta(hours=5)),90)
        self.assertEqual(interval('props','exchange',NOW,NOW+timedelta(minutes=45)),40)
        self.assertEqual(interval('main','exchange',NOW,NOW+timedelta(hours=5)),20)
        self.assertEqual(interval('main','exchange',NOW,NOW+timedelta(hours=7)),60)
        self.assertEqual(interval('main','exchange',NOW),900)

    def test_transport_refuses_policy_below_source_floor_before_http(self):
        from tests.test_collection_adapters import event,Session
        from corner.collection_policy import plan
        from types import SimpleNamespace
        job=next(j for j in plan(NOW,['basketball_nba'],[{**event(),'commence_time':(NOW+timedelta(hours=1)).isoformat()}]) if j.kind=='main' and j.group=='exchange')
        session=Session([])
        provider=Provider(key='synthetic-key',enabled=True,budgeted_pregame=True,session=session,clock=lambda:NOW)
        governor=SimpleNamespace(db=SimpleNamespace(execute=lambda *a:SimpleNamespace(fetchone=lambda:None)))
        with patch('corner.collection_policy.interval',return_value=19):
            with self.assertRaises(RequestNotSent):provider.odds(governor,job,'not-dispatched','operator')
        self.assertEqual(session.calls,[])

