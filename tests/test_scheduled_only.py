import os
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from pipelines import refresh_service as service


class ScheduledOnly(unittest.TestCase):
    def test_main_manual_entry_never_reaches_paid_capture_in_beta(self):
        capture=Mock(side_effect=AssertionError('Paid capture must not run'))
        with patch.dict(os.environ,{'CORNER_PRIVATE_BETA':'1'}):
            code,body=service.run_refresh(capture=capture)
        self.assertEqual((code,body['code']),(403,'scheduled_only'))
        capture.assert_not_called()

    def test_props_manual_entry_never_reaches_paid_capture_in_beta(self):
        capture=Mock(side_effect=AssertionError('Paid capture must not run'))
        with patch.dict(os.environ,{'CORNER_PRIVATE_BETA':'1'}):
            code,body=service.run_props_refresh('basketball_nba',['player_points'],8,capture=capture)
        self.assertEqual((code,body['code']),(403,'scheduled_only'))
        capture.assert_not_called()

    def test_direct_http_posts_cannot_bypass_beta_collection_policy(self):
        with patch.dict(os.environ,{'CORNER_PRIVATE_BETA':'1'}), patch.object(service.accounts.AuthContext,'require',return_value=({'id':'fixture-user'},None)):
            client=TestClient(service.create_app(),base_url='http://localhost')
            for route,body in [('odds',{'sports':['basketball_nba']}),('props',{'sport':'basketball_nba','markets':['player_points'],'max_events':8})]:
                response=client.post('/api/refresh/v1/'+route,json=body)
                self.assertEqual(response.status_code,403)
                self.assertEqual(response.json()['code'],'scheduled_only')

    def test_status_does_not_offer_manual_controls_in_beta(self):
        with patch.dict(os.environ,{'CORNER_PRIVATE_BETA':'1'}), patch.object(service.props,'last_captured',return_value=None):
            self.assertFalse(service.status_view({})['manual_fetch_enabled'])
            self.assertFalse(service.status_view({})['can_refresh'])
            self.assertFalse(service.props_status()['manual_fetch_enabled'])


if __name__=='__main__':unittest.main()
