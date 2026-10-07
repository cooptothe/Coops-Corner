"""Rotation rehearsal on fresh PostgreSQL; Windows service/vault proof is separate."""
from contextlib import closing
from datetime import timedelta
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import psycopg2

from test_deployment_database import LoginDatabase
import test_host_adapter_database as host_tests
from corner import deployment as d, work, worker, channels, versioned_dispatch as dispatch
from credential_rotation import Rotation, qualification_request, frozen, verify_result
from run_scm_acceptance import wait_for


class RotationGuards(unittest.TestCase):
    def test_non_disposable_role_or_database_rejected_before_connection(self):
        from run_credential_rotation import RotationHarness
        self.assertEqual(['qualify'], RotationHarness.work_kinds)
        self.assertEqual('corner.credential-rotation-acceptance/1', RotationHarness.report_format)
        for login, database in [('postgres', 'corner_channels_test_' + 'a' * 32),
                                ('corner_login_test_' + 'a' * 16, 'production')]:
            fixture = Mock(logins={'execution': login}, database_name=database)
            with self.assertRaises(AssertionError): Rotation(fixture, {})
            fixture.connect.assert_not_called()

    def test_unrelated_connection_error_is_not_revocation_proof(self):
        rotation = Rotation.__new__(Rotation)
        rotation.login = 'synthetic'; rotation.old_secret = 'old'; rotation.new_secret = 'new'
        rotation.report = {'checks': {}}
        rotation.positive = Mock()
        rotation.connect = Mock(side_effect=psycopg2.OperationalError('connection refused'))
        with self.assertRaises(AssertionError): rotation.reject_old()
        self.assertNotIn('old_secret_rejected_on_new_connections', rotation.report['checks'])

    def test_no_held_session_means_no_termination(self):
        rotation = Rotation.__new__(Rotation)
        rotation.probe = None; rotation.binding = None; rotation.fixture = Mock()
        with self.assertRaises(AssertionError): rotation.revoke_old_session()
        rotation.fixture.conn.cursor.assert_not_called()


@unittest.skipUnless(os.environ.get('CORNER_DEPLOYMENT_ACCEPTANCE') == '1', 'disposable rotation DB opt-in')
class RotationDatabaseTests(LoginDatabase, unittest.TestCase):
    for name in ('select', 'evaluate', 'qualify', 'register', 'capture', 'command', 'record', 'app', 'opened',
                 'sql_error', 'enqueue', 'claim', 'prepare', 'execution', 'expire', 'routed', 'setUp', 'host_config'):
        locals()[name] = getattr(host_tests.HostDatabaseTests, name)

    def rotation(self):
        rotation = Rotation(self, {'checks': {}})
        self.addCleanup(rotation.close)
        # Each test retains the role's current password for the next fixture.
        self.addCleanup(lambda: self.passwords.update(execution=rotation.new_secret)
                        if rotation.verifier is not None else None)
        return rotation

    def test_revoke_new_auth_explicitly_terminate_old_session_without_role_change(self):
        rotation = self.rotation()
        rotation.open_old_session()
        rotation.rotate()
        rotation.reject_old()
        rotation.revoke_old_session()
        self.assertEqual(3, rotation.report['negative_authentication_attempts'])
        self.assertEqual('passed', rotation.report['checks']['old_authenticated_session_survives_password_change'])
        self.assertEqual('passed', rotation.report['checks']['exact_old_session_terminated_and_absent'])
        self.assertEqual(rotation.before_role, rotation.role_fingerprint())

    def test_wrong_session_binding_cannot_terminate_held_connection(self):
        rotation = self.rotation()
        rotation.open_old_session()
        rotation.binding['backend_start'] -= timedelta(seconds=1)
        with self.assertRaises(AssertionError): rotation.revoke_old_session()
        with rotation.probe.cursor() as cur:
            cur.execute('SELECT 1'); self.assertEqual((1,), cur.fetchone())
        self.conn.rollback()

    def test_frozen_qualification_executes_after_rotation_with_same_identity(self):
        rotation = self.rotation()
        config = self.host_config('execution')
        authority = config.value['authority']
        settings = worker.WorkerSettings('rotation-db-rehearsal', channels.ChannelAuthority(**authority),
                                        timedelta(seconds=1), timedelta(seconds=1), 2, timedelta(seconds=1))
        request = qualification_request(self)
        with closing(rotation.connect(rotation.old_secret)) as conn:
            lease = work.claim(conn, owner=settings.owner, lease_for=settings.lease_for, request_id=request['id'])
            conn.commit()
            dispatch._prepare_static(conn, lease, settings)
            conn.commit()
        original = frozen(self, request)
        rotation.open_old_session(); rotation.rotate(); rotation.reject_old(); rotation.revoke_old_session()
        old_factories = d.connections(config, self.host_approval, lambda _: rotation.old_secret)
        with self.assertRaises(d.ReadinessError): d.readiness(config, self.host_approval, old_factories)
        new_factories = d.connections(config, self.host_approval, lambda _: rotation.new_secret)
        self.assertTrue(d.readiness(config, self.host_approval, new_factories)['ready'])
        def execute():
            result = dispatch.run_once(new_factories['execution'], settings=settings, request_id=request['id'])
            self.assertIn(result['status'], ('idle', 'completed'))
            return result if result['status'] == 'completed' else None
        wait_for(execute, 10)
        result = verify_result(self, request, original, authority)
        self.assertEqual(2, result['claim_count'])
        self.assertEqual(authority, result['domain_authority'])
        self.assertEqual(original['id'], result['preparation_id'])
        self.assertEqual(result, verify_result(self, request, original, authority))
