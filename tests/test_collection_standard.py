import json
import unittest
from unittest.mock import patch, Mock
from datetime import timedelta
from corner.credit_governor import Refused
from pipelines.collection_enable_standard import prepare
from pipelines.collection_live import LiveProvider
from tests.test_collection_live import ActivationTests
from tests.test_collection_smoke import Smoke
from tests.test_collection_setup import NOW, KEY, quota
from corner.collection_policy import TOTAL, EXCHANGE, Job


class StandardActivation(ActivationTests):
    def test_standard_profile_does_not_claim_unverified_fast_or_throughput_evidence(self):
        self.approval['profile'] = 'standard-pregame-v1'
        for key in ('exchange_classification_verified','full_slate_throughput_measured'):
            self.approval['evidence'].pop(key)
        self.assertEqual(self.check()['profile'],'standard-pregame-v1')
        self.approval['profile'] = 'full-v1'
        with self.assertRaises(Refused):
            self.check()

    def test_unknown_profile_refused(self):
        self.approval['profile'] = 'ignore-all-gates'
        with self.assertRaises(Refused):
            self.check()


class StandardLaunch(Smoke):
    def approved_smoke(self):
        return dict(result='smoke_passed',replay_counts_unchanged=True,
                    fresh_quotes_visible=True,restricted_reader_quotes=396)

    def test_reconcile_retains_three_credit_charge_and_prepares_standard_only(self):
        token=self.reserve()
        self.g.finish(self.job,token,'owner',NOW,
                      {'x-requests-last':'3','x-requests-used':'3','x-requests-remaining':str(TOTAL-3)},[])
        self.g.db.execute('UPDATE publication_outbox SET published_at=?',(NOW.timestamp(),))
        self.g.release('owner')
        approval=prepare(self.g,{'ODDS_API_KEY':KEY},
                         {**quota(),'provider_used':3,'provider_remaining':TOTAL-3}, NOW,'a'*40,self.approved_smoke())
        self.assertEqual(approval['profile'],'standard-pregame-v1')
        self.assertEqual(approval['provider_used'],3)
        self.assertFalse(self.g.db.execute('SELECT paused FROM controls').fetchone()[0])
        self.assertNotIn('exchange_classification_verified',approval['evidence'])

    def test_quota_drift_cannot_be_silently_rebased(self):
        self.g.release('owner')
        with self.assertRaises(Refused):
            prepare(self.g,{'ODDS_API_KEY':KEY},
                    {**quota(),'provider_used':7,'provider_remaining':TOTAL-7},NOW,'a'*40,self.approved_smoke())
        self.assertEqual(self.g._binding(self.g.db,NOW)['used'],0)

    def test_fast_jobs_blocked_before_any_transport(self):
        session=Mock()
        provider=LiveProvider(self.g,'owner',key=KEY,enabled=True,exchange_verified=True,
                              session=session,clock=lambda:NOW)
        job=Job('main','icehockey_nhl','exchange',EXCHANGE,('h2h','spreads','totals'))
        with patch('pipelines.collection_live.activation',return_value={'profile':'standard-pregame-v1'}):
            with self.assertRaises(Refused):
                provider.odds(self.g,job,'unused','owner')
        session.get.assert_not_called()

    def test_standard_discovery_excludes_leagues_without_upcoming_events(self):
        provider=LiveProvider(self.g,'owner',key=KEY,enabled=True,clock=lambda:NOW)
        from pipelines.collection_provider import Provider
        inventory={'active_sport_keys':['icehockey_nhl','basketball_nba'],
                   'events':[{'sport_key':'icehockey_nhl'}]}
        with patch.object(Provider,'discover',return_value=inventory), \
             patch('pipelines.collection_live.activation',return_value={'profile':'standard-pregame-v1'}):
            self.assertEqual(provider.discover()['active_sport_keys'],['icehockey_nhl'])
        provider.close()

    def test_runner_filters_fast_jobs_before_credit_reservation(self):
        from pipelines.collection_runner import Runner
        self.g.db.execute("UPDATE controls SET paused='' WHERE id=1")
        groups=[]
        def transport(governor,job,token,owner):
            groups.append(job.group)
            return 200,[],{'x-requests-last':'3','x-requests-used':'3',
                           'x-requests-remaining':str(TOTAL-3)},NOW
        runner=Runner(self.g,lambda:{'active_sport_keys':['icehockey_nhl'],
                                    'events':[],'discovered_at':NOW.isoformat()},
                      transport,owner='owner',clock=lambda:NOW,
                      job_filter=lambda job:job.group=='standard')
        self.assertEqual(runner.tick()['executed'],1)
        self.assertEqual(groups,['standard'])
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM attempts').fetchone()[0],1)


if __name__=='__main__':
    unittest.main()
