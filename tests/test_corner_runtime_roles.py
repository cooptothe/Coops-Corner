"""Real non-owner SET ROLE checks, isolated roles and disposable PostgreSQL DB."""
import os
import unittest
from contextlib import contextmanager
from uuid import uuid4
from pathlib import Path
from psycopg2 import sql
import test_corner_lifecycle_store as fixtures
from corner import runtime_roles as r, lifecycle_store as lifecycle


class RoleDatabase(fixtures.LifecycleDatabase):
    @classmethod
    def setUpClass(cls):
        cls.roles={}
        cls.addClassCleanup(cls.drop_roles)
        super().setUpClass()  # Its DB cleanup runs BEFORE drop_roles (LIFO).
        conn=cls.connect()
        try:
            cls.roles=r.provision(conn,prefix='corner_test_'+uuid4().hex[:12])
            conn.commit()
        finally: conn.close()

    @classmethod
    def drop_roles(cls):
        import psycopg2
        from config import DB_CONFIG
        conn=psycopg2.connect(**DB_CONFIG)
        try:
            with conn.cursor() as cur:
                for role in reversed(list(cls.roles.values())):
                    if not role.startswith('corner_test_'): raise AssertionError('not a test role')
                    cur.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
            conn.commit()
        finally: conn.close()


@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE')=='1' and os.getenv('CORNER_TEST_CONCURRENCY')=='1','opt-in role tests')
class RuntimeRoleTests(RoleDatabase,unittest.TestCase):
    # Reuse setup/helpers, not the inherited tests.
    setUp=fixtures.LifecycleStoreTests.setUp
    select=fixtures.LifecycleStoreTests.select
    evaluate=fixtures.LifecycleStoreTests.evaluate
    qualify=fixtures.LifecycleStoreTests.qualify
    register=fixtures.LifecycleStoreTests.register
    capture=fixtures.LifecycleStoreTests.capture
    command=fixtures.LifecycleStoreTests.command
    record=fixtures.LifecycleStoreTests.record
    app=fixtures.LifecycleStoreTests.app
    opened=fixtures.LifecycleStoreTests.opened
    sql_error=fixtures.LifecycleStoreTests.sql_error

    @contextmanager
    def role(self,name):
        with self.conn.cursor() as cur: cur.execute(sql.SQL('SET LOCAL ROLE {}').format(sql.Identifier(self.roles[name])))
        try: yield
        except Exception:
            # Preserve the original failure rather than masking it with RESET
            # ROLE inside an aborted PostgreSQL transaction.
            from psycopg2.extensions import TRANSACTION_STATUS_INERROR
            if self.conn.get_transaction_status()==TRANSACTION_STATUS_INERROR: self.conn.rollback()
            raise
        finally:
            with self.conn.cursor() as cur: cur.execute('RESET ROLE')

    def test_analysis_adapters_and_locks_work_without_owner(self):
        with self.role('analysis'):
            self.evaluate()
            self.qualify(self.evaluation)
            self.record(key='nonowner')
            self.opened()
            lifecycle.verify_history(self.conn,condition_id=self.condition['id'])

    def test_runtime_cannot_mutate_or_truncate_any_ledger(self):
        tables=('provider_payloads','odds_observations','observation_dispositions','engine_evaluations','engine_evaluation_inputs',
            'qualification_decisions','qualification_channel_generations','channel_generation_activations','opportunity_occurrences',
            'actionability_assessments','assessment_stream_evidence','lifecycle_applications','opportunity_transitions')
        with self.role('worker'):
            for table in tables:
                for command in (f'UPDATE corner.{table} SET id=id',f'DELETE FROM corner.{table}',f'TRUNCATE corner.{table} CASCADE'):
                    self.sql_error(command,(),'42501')
            self.sql_error('ALTER TABLE corner.odds_observations DISABLE TRIGGER ALL',(),'42501')
            self.sql_error('CREATE TABLE corner.runtime_owned(id int)',(),'42501')

    def test_worker_cannot_activate_channels_or_rebuild_by_deletion(self):
        with self.role('worker'):
            self.sql_error('INSERT INTO corner.channel_generation_activations DEFAULT VALUES',(),'42501')
            self.sql_error('DELETE FROM corner.opportunities',(),'42501')
            self.sql_error('INSERT INTO corner.observation_dispositions DEFAULT VALUES',(),'42501')

    def test_recovery_role_can_rebuild_but_not_mutate_history(self):
        self.opened()
        with self.role('recovery'):
            lifecycle.rebuild_projections(self.conn,condition_id=self.condition['id'])
            self.sql_error('DELETE FROM corner.lifecycle_applications',(),'42501')

    def test_roles_are_not_owners_or_privileged_accounts(self):
        with self.conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM pg_roles WHERE rolname=ANY(%s) AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolcanlogin OR rolbypassrls)',(list(self.roles.values()),))
            self.assertEqual(0,cur.fetchone()[0])
            cur.execute('SELECT count(*) FROM pg_class c JOIN pg_roles r ON r.oid=c.relowner WHERE r.rolname=ANY(%s)',(list(self.roles.values()),))
            self.assertEqual(0,cur.fetchone()[0])

    def test_channel_admin_can_register_and_activate_without_ledger_mutation(self):
        from corner import channels
        with self.role('channel_admin'):
            generation=self.register()
            channels.activate_generation(self.conn,authority=self.authority,activation_key='role-activation',
                command=channels.ActivationCommand(self.channel['id'],generation['id'],self.generation['id'],self.time))
            self.sql_error('UPDATE corner.channel_generation_activations SET id=id',(),'42501')

    def test_disposition_writer_only_appends_decisions(self):
        from corner.dispositions import record_disposition,DispositionCommand
        with self.role('disposition'):
            row=record_disposition(self.conn,authority=self.authority,
                command=DispositionCommand(str(uuid4()),self.target_id,'rejected','role test',self.time))
            self.assertEqual(self.target_id,row['observation_id'])
            self.sql_error('DELETE FROM corner.observation_dispositions',(),'42501')

    def test_ingestion_role_can_persist_raw_fixture_without_history_mutation(self):
        from corner.ingestion import ingest_payload
        raw=(Path(__file__).resolve().parents[1]/'fixtures/odds_api/v4/nfl_featured_source_ids_t1.json').read_bytes()
        with self.role('ingest'):
            _,count=ingest_payload(self.conn,raw,received_at=self.time)
            self.assertEqual(24,count)
        # Ingestion owns its commit; SET LOCAL ROLE ended with it. Restore the
        # non-owner role for the denial assertion rather than accidentally testing owner.
        with self.role('ingest'):
            self.sql_error('UPDATE corner.odds_observations SET id=id',(),'42501')
