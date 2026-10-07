"""Portable config/process acceptance, separately reported from host supervision."""
from dataclasses import asdict
from pathlib import Path
import json
import os
import queue
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from test_deployment_database import LoginDatabase, ROOT, fixtures
from corner import deployment as d, polling, versioned_dispatch
from psycopg2.extras import RealDictCursor


def configuration():
    return {'format': 'corner.deployment.acceptance/1', 'environment': 'isolated_nonproduction',
        'production_positive_authorization': False, 'database': {'host': '127.0.0.1', 'port': 5432, 'dbname': 'isolated'},
        'identities': {k: {'login': k, 'secret_ref': 'ACCEPTANCE_' + k} for k in d.SERVICES},
        'authority': {'kind': 'service', 'identifier': 'process-test'}, 'polling': asdict(polling.PollSettings()),
        'worker': {'lease_seconds': 90, 'retry_seconds': 5, 'max_retries': 3, 'statement_timeout_seconds': 5},
        'work_kinds': ['ensure_occurrence'], 'partitions': [], 'max_cycles': 1}


class ConfigurationAcceptanceTests(unittest.TestCase):
    def test_valid_nonsecret_configuration_roundtrips(self):
        doc = configuration()
        self.assertEqual(doc, d.Configuration.parse(d.canonical(doc)).value)

    def test_production_missing_or_unknown_fields_fail(self):
        for mutate in (lambda x: x.update(environment='production'), lambda x: x.update(production_positive_authorization=True),
                       lambda x: x.pop('production_positive_authorization'), lambda x: x.update(password='not-a-secret'),
                       lambda x: x['database'].update(user='owner'), lambda x: x.update(max_cycles=0),
                       lambda x: x['worker'].update(lease_seconds=10)):
            doc = configuration(); mutate(doc)
            with self.assertRaises((d.ReadinessError, ValueError)): d.Configuration.parse(d.canonical(doc))

    def test_duplicate_configuration_keys_fail(self):
        text = d.canonical(configuration())
        with self.assertRaises(d.ReadinessError): d.Configuration.parse(text[:-1] + ',"max_cycles":2}')

    def test_missing_secret_does_not_fall_back_to_db_config(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(d.ReadinessError, 'unavailable'): d.environment_secret('MISSING_ACCEPTANCE_SECRET')


@unittest.skipUnless(os.getenv('CORNER_DEPLOYMENT_ACCEPTANCE') == '1', 'explicit disposable LOGIN/process acceptance opt-in')
class ProcessDatabaseAcceptanceTests(LoginDatabase, unittest.TestCase):
    for _name in ('select', 'evaluate', 'qualify', 'register', 'capture', 'command', 'record', 'app', 'opened',
                  'sql_error', 'enqueue', 'claim', 'prepare', 'execution', 'expire', 'routed'):
        locals()[_name] = getattr(fixtures.WorkerTests, _name)

    def setUp(self):
        fixtures.WorkerTests.setUp(self)
        # All work in this database is disposable. Prevent previously committed
        # tests from competing with a scenario's one intentional request.
        with self.conn.cursor() as cur:
            cur.execute("""UPDATE corner.work_executions SET status='blocked',blocked_reason='acceptance_isolation',
                waiting_reason=NULL,lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL WHERE status<>'completed'""")
        self.conn.commit()
        self.directory = tempfile.TemporaryDirectory(prefix='corner_acceptance_')
        self.addCleanup(self.directory.cleanup)
        self.output = []

    def launch(self, mode, *, missing_secret=False, cycles=1):
        doc = json.loads(self.service_config.document)
        doc.update(work_kinds=['ensure_occurrence'], partitions=[], max_cycles=cycles)
        doc['polling'].update(attempts_per_cycle=1, idle_initial=.1, idle_cap=.1)
        config_path = Path(self.directory.name) / 'configuration.json'
        approval_path = Path(self.directory.name) / 'target-approval.json'
        config_path.write_text(d.canonical(doc))
        approval_path.write_text(self.approval.document)
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        for name, identity in doc['identities'].items(): env[identity['secret_ref']] = self.passwords[name]
        if missing_secret: env.pop(doc['identities']['health']['secret_ref'])
        process = subprocess.Popen([sys.executable, '-u', str(ROOT / 'acceptance/process_probe.py'), str(config_path), str(approval_path), mode],
            cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        process.events = queue.Queue()
        def output():
            for line in process.stdout:
                self.output.append(line)
                process.events.put(json.loads(line))
        threading.Thread(target=output, daemon=True).start()
        def cleanup():
            if process.poll() is None: process.kill()
            process.wait(timeout=10)
            for stream in (process.stdin, process.stdout, process.stderr): stream.close()
        self.addCleanup(cleanup)
        return process

    def event(self, process, name):
        for _ in range(100):
            item = process.events.get(timeout=20)
            if item['event'] == name: return item
            self.assertNotEqual('startup_or_process_error', item['event'], item)
        self.fail('expected process event missing')

    def test_secret_injection_and_process_counter_reset_without_repo_credentials(self):
        first = self.launch('bounded')
        one = self.event(first, 'ready'); self.event(first, 'done')
        self.assertEqual(0, first.wait(timeout=10))
        second = self.launch('bounded')
        two = self.event(second, 'ready'); self.event(second, 'done')
        self.assertEqual(0, second.wait(timeout=10))
        self.assertNotEqual(one['process_instance_id'], two['process_instance_id'])
        for item in (one, two):
            self.assertTrue(all(n == 0 for _, n in item['telemetry']['current_process_counters']))
        retained = ''.join(p.read_text() for p in Path(self.directory.name).iterdir()) + ''.join(self.output)
        for password in self.passwords.values(): self.assertNotIn(password, retained)

    def test_missing_secret_fails_before_any_claim(self):
        request = self.enqueue(); self.conn.commit()
        process = self.launch('bounded', missing_secret=True)
        item = process.events.get(timeout=20)
        self.assertEqual('startup_or_process_error', item['event'])
        self.assertEqual(2, process.wait(timeout=10))
        self.assertEqual(0, self.execution(request)['claim_count'])

    def test_cooperative_stop_drains_started_completion_without_new_claim(self):
        first, second = self.enqueue(), self.enqueue(); self.conn.commit()
        process = self.launch('drain', cycles=100)
        self.event(process, 'completion_uncommitted')
        self.assertEqual('leased', self.execution(first)['status'])
        process.stdin.write('stop\n'); process.stdin.flush()
        done = self.event(process, 'done')
        self.assertEqual(0, process.wait(timeout=10))
        self.assertEqual(1, done['totals']['completed'])
        self.assertEqual('completed', self.execution(first)['status'])
        self.assertEqual(0, self.execution(second)['claim_count'])

    def test_abrupt_death_restart_reclaims_original_frozen_command(self):
        request = self.enqueue(); self.conn.commit()
        process = self.launch('crash_prepared')
        self.event(process, 'prepared')
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            frozen = versioned_dispatch.prepared(cur, request['id'])
        self.assertIsNotNone(frozen)
        process.kill(); process.wait(timeout=10)
        self.assertEqual('leased', self.execution(request)['status'])
        # Test-only wall-clock advance, not a shutdown release operation.
        self.expire(request); self.conn.commit()
        restarted = self.launch('bounded')
        ready = self.event(restarted, 'ready'); done = self.event(restarted, 'done')
        self.assertEqual(0, restarted.wait(timeout=10))
        self.assertEqual(1, done['totals']['reclaimed'])
        self.assertEqual(frozen['id'], self.execution(request)['prepared_command_id'])
        self.assertEqual('completed', self.execution(request)['status'])
        self.assertTrue(all(n == 0 for _, n in ready['telemetry']['current_process_counters']))

    @unittest.skipIf(os.name == 'nt', 'POSIX SIGTERM is not exercised on Windows; SCM stop acceptance is a separate proof')
    def test_posix_sigterm_drains(self):
        request = self.enqueue(); self.conn.commit()
        process = self.launch('drain', cycles=100)
        self.event(process, 'completion_uncommitted')
        process.send_signal(signal.SIGTERM)
        self.event(process, 'done')
        self.assertEqual(0, process.wait(timeout=10))
        self.assertEqual('completed', self.execution(request)['status'])
