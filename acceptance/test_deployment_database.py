"""Separate opt-in deployment DB acceptance; never part of tests/ regression."""
from dataclasses import asdict
from pathlib import Path
import json
import os
import secrets
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

import psycopg2
from psycopg2 import sql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from test_corner_work import WorkDatabase
import test_corner_worker as fixtures
from corner import deployment as d, polling, versioned_dispatch, versioned_reconciliation, work, health


class LoginDatabase(WorkDatabase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.logins = {k: 'corner_login_test_' + uuid4().hex[:16] for k in d.SERVICES}
        cls.passwords = {k: secrets.token_urlsafe(40) for k in d.SERVICES}
        cls.addClassCleanup(cls.drop_logins)
        with cls.connect() as conn:
            with conn.cursor() as cur:
                cur.execute((ROOT / 'db/migrations/013_corner_v2_actionability_reasons.sql').read_text())
                for service, login in cls.logins.items():
                    verifier = psycopg2.extensions.encrypt_password(cls.passwords[service], login, conn,
                                                                   algorithm='scram-sha-256')
                    cur.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS').format(
                        sql.Identifier(login), sql.Literal(verifier)))
                    cur.execute(sql.SQL('GRANT {} TO {}').format(sql.Identifier(cls.roles[d.SERVICES[service]]), sql.Identifier(login)))
        database = {'host': cls.connection_config.get('host', 'localhost'),
                    'port': int(cls.connection_config.get('port', 5432)), 'dbname': cls.database_name}
        cls.doc = {'format': 'corner.deployment.acceptance/1', 'environment': 'isolated_nonproduction',
            'production_positive_authorization': False, 'database': database,
            'identities': {k: {'login': v, 'secret_ref': 'CORNER_ACCEPTANCE_' + k.upper()} for k, v in cls.logins.items()},
            'authority': {'kind': 'service', 'identifier': 'deployment-acceptance'},
            'polling': asdict(polling.PollSettings()),
            'worker': {'lease_seconds': 90, 'retry_seconds': 5, 'max_retries': 3, 'statement_timeout_seconds': 5},
            'work_kinds': list(polling.KINDS), 'partitions': [{'obligation': 'occurrence', 'channel_id': None}], 'max_cycles': 1}
        cls.service_config = d.Configuration.parse(d.canonical(cls.doc))
        # Expected manifest comes from the fully migrated disposable release
        # fixture, BEFORE faults are injected. Never relearn it during readiness.
        with cls.connect() as conn:
            with conn.cursor() as cur:
                cls.approval_doc = {'environment': 'isolated_nonproduction', 'database': database,
                    'logins': cls.logins, 'profiles': cls.roles, 'handlers': versioned_dispatch.HANDLERS, 'authority': cls.doc['authority'],
                    'catalog_sha256': d.catalog_digest(cur),
                    'privileges': {k: d.privilege_digest(cur, cls.roles[v]) for k, v in d.SERVICES.items()}}
        cls.approval = d.TargetApproval(d.canonical(cls.approval_doc))

    @classmethod
    def drop_logins(cls):
        with cls.connect() as conn:
            with conn.cursor() as cur:
                for login in cls.logins.values():
                    if not login.startswith('corner_login_test_'): raise AssertionError('not disposable')
                    cur.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(login)))

    def secret(self, ref):
        return next(self.passwords[k] for k, v in self.doc['identities'].items() if v['secret_ref'] == ref)

    def factories(self):
        return d.connections(self.service_config, self.approval, self.secret)


@unittest.skipUnless(os.getenv('CORNER_DEPLOYMENT_ACCEPTANCE') == '1', 'explicit disposable LOGIN acceptance opt-in')
class DeploymentDatabaseTests(LoginDatabase, unittest.TestCase):
    for _name in ('select', 'evaluate', 'qualify', 'register', 'capture', 'command', 'record', 'app', 'opened',
                  'sql_error', 'enqueue', 'claim', 'prepare', 'execution', 'expire', 'routed'):
        locals()[_name] = getattr(fixtures.WorkerTests, _name)
    setUp = fixtures.WorkerTests.setUp

    def denied(self, service, statement):
        conn = self.factories()[service]()
        try:
            with conn.cursor() as cur:
                with self.assertRaises(psycopg2.Error) as error: cur.execute(statement)
                self.assertEqual('42501', error.exception.pgcode)
        finally: conn.rollback(); conn.close()

    def test_real_password_logins_and_effective_readiness(self):
        self.assertTrue(d.readiness(self.service_config, self.approval, self.factories())['ready'])
        for service, connect in self.factories().items():
            with connect() as conn:
                with conn.cursor() as cur:
                    cur.execute('SELECT session_user,current_user')
                    self.assertEqual((self.logins[service],) * 2, cur.fetchone())
        # A trust-only HBA must not be mistaken for password authentication proof.
        bad = d.connections(self.service_config, self.approval, lambda _: 'deliberately-wrong-' + uuid4().hex)
        with self.assertRaises(d.ReadinessError): bad['health']()

    def test_discovery_enqueues_execution_completes_health_only_reads(self):
        judgment = self.qualify(self.evaluation)
        routed, _ = self.routed(); self.conn.commit()
        for obligation, identity in (('occurrence', judgment['id']), ('activation', self.condition['id']), ('qualification', routed['id'])):
            with self.factories()['discovery']() as conn:
                report = versioned_reconciliation.sweep(conn, obligation=obligation,
                    **({'channel_id': self.channel['id']} if obligation != 'occurrence' else {}))
                item = next(i for i in report['items'] if i['candidate_id'] == identity)
                self.assertEqual('newly_requested', item['status'], item)
            result = versioned_dispatch.run_once(self.factories()['execution'], settings=self.settings, request_id=item['request_id'])
            self.assertEqual('completed', result['status'], result)
        snapshot = health.read_health(self.factories()['health'])
        self.assertGreaterEqual(snapshot.queue.completion_count, 3)

    def test_cross_service_and_administrative_writes_denied(self):
        for service in d.SERVICES:
            for statement in ("CREATE TABLE corner.forbidden(id int)", "CREATE ROLE forbidden_role",
                              "ALTER TABLE corner.odds_observations DISABLE TRIGGER ALL"):
                self.denied(service, statement)
        for statement in ('INSERT INTO corner.engine_evaluations DEFAULT VALUES',
                          "UPDATE corner.work_executions SET status=status", 'INSERT INTO corner.prepared_work_commands DEFAULT VALUES'):
            self.denied('discovery', statement)
        for statement in ('INSERT INTO corner.work_requests DEFAULT VALUES', 'INSERT INTO corner.work_executions DEFAULT VALUES',
                          'UPDATE corner.work_executions SET status=status', 'INSERT INTO corner.lifecycle_applications DEFAULT VALUES'):
            self.denied('health', statement)
        for statement in ('INSERT INTO corner.channel_generation_activations DEFAULT VALUES',
                          'DELETE FROM corner.opportunities', 'INSERT INTO corner.observation_dispositions DEFAULT VALUES'):
            self.denied('execution', statement)

    def test_execution_cannot_update_delete_truncate_immutable_ledgers(self):
        for table in ('odds_observations', 'engine_evaluations', 'qualification_decisions', 'actionability_assessments',
                      'lifecycle_applications', 'opportunity_transitions', 'prepared_work_commands', 'work_requests'):
            for command in (f'UPDATE corner.{table} SET id=id', f'DELETE FROM corner.{table}', f'TRUNCATE corner.{table} CASCADE'):
                self.denied('execution', command)

    def test_unexpected_direct_or_inherited_membership_fails_readiness(self):
        for member in (self.logins['execution'], self.roles['worker']):
            with self.connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql.SQL('GRANT {} TO {}').format(sql.Identifier(self.roles['work_admin']), sql.Identifier(member)))
            try:
                with self.assertRaisesRegex(d.ReadinessError, 'membership'):
                    d.readiness(self.service_config, self.approval, self.factories())
            finally:
                with self.connect() as conn:
                    with conn.cursor() as cur:
                        cur.execute(sql.SQL('REVOKE {} FROM {}').format(sql.Identifier(self.roles['work_admin']), sql.Identifier(member)))

    def test_unexpected_direct_grant_fails_even_without_extra_membership(self):
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL('GRANT UPDATE ON corner.work_executions TO {}').format(sql.Identifier(self.logins['health'])))
        try:
            with self.assertRaisesRegex(d.ReadinessError, 'privileges'): d.readiness(self.service_config, self.approval, self.factories())
        finally:
            with self.connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql.SQL('REVOKE UPDATE ON corner.work_executions FROM {}').format(sql.Identifier(self.logins['health'])))

    def test_missing_migration_shape_fails_then_restored(self):
        with self.connect() as conn:
            with conn.cursor() as cur: cur.execute('ALTER TABLE corner.opportunity_transitions DROP CONSTRAINT opportunity_transitions_check')
        try:
            with self.assertRaisesRegex(d.ReadinessError, 'schema'): d.readiness(self.service_config, self.approval, self.factories())
        finally:
            text = (ROOT / 'db/migrations/013_corner_v2_actionability_reasons.sql').read_text()
            text = text.replace('DROP CONSTRAINT opportunity_transitions_check;', 'DROP CONSTRAINT IF EXISTS opportunity_transitions_check;')
            with self.connect() as conn:
                with conn.cursor() as cur: cur.execute(text)

    def test_missing_required_profile_grant_fails_readiness(self):
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL('REVOKE SELECT ON corner.work_requests FROM {}').format(sql.Identifier(self.roles['reader'])))
        try:
            with self.assertRaisesRegex(d.ReadinessError, 'privileges'):
                d.readiness(self.service_config, self.approval, self.factories())
        finally:
            with self.connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql.SQL('GRANT SELECT ON corner.work_requests TO {}').format(sql.Identifier(self.roles['reader'])))

    def test_disabled_immutability_trigger_fails_readiness(self):
        with self.connect() as conn:
            with conn.cursor() as cur: cur.execute('ALTER TABLE corner.lifecycle_applications DISABLE TRIGGER USER')
        try:
            with self.assertRaisesRegex(d.ReadinessError, 'schema'):
                d.readiness(self.service_config, self.approval, self.factories())
        finally:
            with self.connect() as conn:
                with conn.cursor() as cur: cur.execute('ALTER TABLE corner.lifecycle_applications ENABLE TRIGGER USER')

    def test_unexpected_system_function_grant_fails_readiness(self):
        function = 'pg_catalog.pg_read_file(text)'
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL('GRANT EXECUTE ON FUNCTION ' + function + ' TO {}').format(sql.Identifier(self.logins['health'])))
        try:
            with self.assertRaisesRegex(d.ReadinessError, 'privileges'):
                d.readiness(self.service_config, self.approval, self.factories())
        finally:
            with self.connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql.SQL('REVOKE EXECUTE ON FUNCTION ' + function + ' FROM {}').format(sql.Identifier(self.logins['health'])))

    def test_unexpected_grant_option_fails_even_for_an_already_readable_table(self):
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL('GRANT SELECT ON corner.work_requests TO {} WITH GRANT OPTION').format(sql.Identifier(self.logins['health'])))
        try:
            with self.assertRaisesRegex(d.ReadinessError, 'privileges'):
                d.readiness(self.service_config, self.approval, self.factories())
        finally:
            with self.connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql.SQL('REVOKE SELECT ON corner.work_requests FROM {}').format(sql.Identifier(self.logins['health'])))

    def test_changed_manifest_and_production_classification_rejected_before_connect(self):
        for change in ({'environment': 'production'}, {'handlers': {}}):
            approval = d.TargetApproval(d.canonical(self.approval_doc | change))
            with patch.object(d.psycopg2, 'connect', side_effect=AssertionError('no connection permitted')):
                with self.assertRaises(d.ReadinessError): d.connections(self.service_config, approval, self.secret)
        unsafe = d.Configuration(d.canonical(self.doc | {'production_positive_authorization': True}))
        with patch.object(d.psycopg2, 'connect', side_effect=AssertionError('no connection permitted')):
            with self.assertRaises(d.ReadinessError): d.connections(unsafe, self.approval, self.secret)

    def test_runtime_schema_owner_connection_is_not_accepted_as_configured_login(self):
        factories = self.factories(); factories['execution'] = lambda **kwargs: self.connect()
        with self.assertRaisesRegex(d.ReadinessError, 'identity'): d.readiness(self.service_config, self.approval, factories)

    def test_unknown_frozen_implementation_blocks_not_upgrades(self):
        request = self.enqueue(); self.conn.commit()
        with self.factories()['execution']() as conn:
            lease = work.claim(conn, owner=self.settings.owner, lease_for=self.settings.lease_for, request_id=request['id'])
            from psycopg2.extras import Json
            from corner import evaluations
            document = {'format': 'not-installed/99', 'work_kind': 'ensure_occurrence', 'implementation': 'unknown'}
            with conn.cursor() as cur:
                cur.execute('INSERT INTO corner.prepared_work_commands(work_request_id,command_format_version,command_snapshot,command_sha256) VALUES (%s,%s,%s,%s)',
                            (request['id'], document['format'], Json(document), evaluations._digest(document)))
        self.expire(request); self.conn.commit()
        result = versioned_dispatch.run_once(self.factories()['execution'], settings=self.settings, request_id=request['id'])
        self.assertEqual('blocked', result['status'])
