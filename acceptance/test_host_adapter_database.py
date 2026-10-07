"""Disposable LOGIN proof for the fixed-role adapters, not SCM supervision."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from test_deployment_database import LoginDatabase, fixtures, ROOT
from corner import deployment as d, host_service as host, polling, windows_control as control, windows_shutdown


@unittest.skipUnless(os.name == 'nt' and os.getenv('CORNER_DEPLOYMENT_ACCEPTANCE') == '1',
                     'explicit disposable Windows adapter DB acceptance')
class HostDatabaseTests(LoginDatabase, unittest.TestCase):
    for _name in ('select', 'evaluate', 'qualify', 'register', 'capture', 'command', 'record', 'app', 'opened',
                  'sql_error', 'enqueue', 'claim', 'prepare', 'execution', 'expire', 'routed'):
        locals()[_name] = getattr(fixtures.WorkerTests, _name)

    def setUp(self):
        fixtures.WorkerTests.setUp(self)
        self.sid = control.current_sid()
        self.host_approval = d.TargetApproval(d.canonical(dict(self.approval_doc,
            windows_sids={s: self.sid for s in d.SERVICES})))

    def host_config(self, service):
        doc = json.loads(self.service_config.document)
        doc.update(format='corner.host-service/1', identities={service: {
            'login': self.logins[service], 'secret_ref': 'Corner/Postgres/' + service.capitalize()}},
            work_kinds=['ensure_occurrence'] if service == 'execution' else [],
            partitions=[{'obligation': 'occurrence', 'channel_id': None}] if service == 'discovery' else [])
        return d.Configuration.parse(d.canonical(doc), service=service)

    def test_each_role_readies_with_only_own_credential(self):
        for service in d.SERVICES:
            seen = []
            def secret(ref):
                self.assertEqual('Corner/Postgres/' + service.capitalize(), ref)
                seen.append(ref); return self.passwords[service]
            runner, _ = host.build(service, self.host_config(service), self.host_approval,
                                   stop=polling.Stop(), secret_provider=secret)
            self.assertEqual(1, len(seen))  # Only the one readiness connection.
            self.assertEqual(service == 'health', isinstance(runner, host.HealthRunner))

    def test_swapped_authenticated_connection_fails_effective_readiness(self):
        for service, wrong in (('discovery', 'execution'), ('execution', 'discovery')):
            wrong_factory = d.connections(self.host_config(wrong), self.host_approval, lambda _: self.passwords[wrong])[wrong]
            with self.assertRaisesRegex(d.ReadinessError, 'identity'):
                d.readiness(self.host_config(service), self.host_approval, {service: wrong_factory})

    def test_wrong_password_does_not_fall_back(self):
        with self.assertRaises(d.ReadinessError):
            host.build('discovery', self.host_config('discovery'), self.host_approval,
                       stop=polling.Stop(), secret_provider=lambda _: self.passwords['execution'])

    def test_health_runner_exports_real_snapshot_under_reader(self):
        runner, _ = host.build('health', self.host_config('health'), self.host_approval,
                              stop=polling.Stop(), secret_provider=lambda _: self.passwords['health'])
        output = []
        runner.run(max_cycles=1, emit=output.append)
        self.assertEqual(['health'], [item['event'] for item in output])
        self.assertIn('queue', output[0]['snapshot'])

    def test_fixed_entrypoints_run_bounded_with_real_role_readiness(self):
        import importlib
        from corner import windows_credentials
        with tempfile.TemporaryDirectory(prefix='corner_host_entry_') as folder:
            config_path, approval_path = Path(folder) / 'config.json', Path(folder) / 'approval.json'
            approval_path.write_text(self.host_approval.document)
            for service in d.SERVICES:
                config_path.write_text(self.host_config(service).document)
                module = importlib.import_module('corner.services.' + service)
                seen = []
                def password(role, target, login):
                    self.assertEqual(service, role)
                    self.assertEqual('Corner/Postgres/' + service.capitalize(), target)
                    self.assertEqual(self.logins[service], login)
                    seen.append(target)
                    return self.passwords[service]
                with patch.object(windows_credentials, 'password', side_effect=password), patch('corner.host_entry.emit') as emit:
                    self.assertEqual(0, module.main(['run', '--config', str(config_path), '--approval', str(approval_path),
                        '--runtime-record', str(Path(folder) / 'instance.json')]))
                self.assertTrue(seen)
                self.assertEqual('ready', emit.call_args_list[0].args[0]['event'])
                self.assertEqual('stopped', emit.call_args_list[-1].args[0]['event'])

    def test_discovery_runner_only_creates_requests(self):
        self.qualify(self.evaluation); self.conn.commit()
        with self.conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM corner.opportunity_occurrences')
            before = cur.fetchone()[0]
        runner, _ = host.build('discovery', self.host_config('discovery'), self.host_approval,
                              stop=polling.Stop(), secret_provider=lambda _: self.passwords['discovery'])
        report = runner.run_cycle()
        self.assertGreater(report['counts']['discovered'], 0)
        self.assertEqual(0, report['counts']['claimed'])
        with self.conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM corner.opportunity_occurrences')
            self.assertEqual(before, cur.fetchone()[0])

    def test_native_stop_drains_actual_completion_without_claiming_next(self):
        # Isolate this scenario's work in the disposable DB only.
        with self.conn.cursor() as cur:
            cur.execute("""UPDATE corner.work_executions SET status='blocked',blocked_reason='host_test_isolation',
                waiting_reason=NULL,lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL WHERE status<>'completed'""")
        first, second = self.enqueue(), self.enqueue(); self.conn.commit()
        config = self.host_config('execution').value
        config['max_cycles'] = 100
        config['polling'].update(attempts_per_cycle=1, idle_initial=.1, idle_cap=.1)
        with tempfile.TemporaryDirectory(prefix='corner_host_adapter_') as folder:
            config_path, approval_path = Path(folder) / 'config.json', Path(folder) / 'approval.json'
            config_path.write_text(d.canonical(config))
            approval_path.write_text(self.host_approval.document)
            child = subprocess.Popen([sys.executable, '-B', '-u', str(ROOT / 'acceptance/host_process_probe.py'),
                str(config_path), str(approval_path), 'drain'], cwd=ROOT, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                env=dict(os.environ, CORNER_HOST_TEST_PASSWORD=self.passwords['execution']))
            events = queue.Queue()
            output = []
            def read():
                for line in child.stdout:
                    output.append(line); events.put(json.loads(line))
            thread = threading.Thread(target=read, daemon=True); thread.start()
            def event(name):
                while True:
                    item = events.get(timeout=20)
                    self.assertNotEqual('probe_error', item['event'] if 'event' in item else None)
                    if item.get('event') == name: return item
            try:
                event('ready'); event('completion_uncommitted')
                stop = subprocess.run([sys.executable, '-B', '-m', 'corner.services.execution',
                'stop', '--expected-sid', self.sid, '--runtime-record', str(Path(folder) / 'instance.json'),
                '--graceful-drain-timeout', '5', '--hard-stop-verification-timeout', '3'], cwd=ROOT, stdin=subprocess.DEVNULL,
                    capture_output=True, text=True, timeout=10)
                self.assertEqual(0, stop.returncode, stop.stderr)
                done = event('done')
                self.assertEqual(0, child.wait(timeout=10))
                self.assertEqual(1, done['totals']['completed'])
                self.assertEqual('completed', self.execution(first)['status'])
                self.assertEqual(0, self.execution(second)['claim_count'])
                self.assertIsNotNone(self.execution(first)['prepared_command_id'])
                self.assertNotIn(self.passwords['execution'], ''.join(output))
            finally:
                if child.poll() is None: child.kill()
                child.wait(timeout=10); thread.join(timeout=2)
                child.stdout.close(); child.stderr.close()

    def test_force_rollback_then_natural_reclaim_of_original_preparation(self):
        from psycopg2.extras import RealDictCursor
        from corner import versioned_dispatch
        with self.conn.cursor() as cur:
            cur.execute("""UPDATE corner.work_executions SET status='blocked',blocked_reason='host_test_isolation',
                waiting_reason=NULL,lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL WHERE status<>'completed'""")
        judgment = self.qualify(self.evaluation)
        request = self.enqueue(sources={'qualification_decision_id': judgment['id']}); self.conn.commit()
        config = self.host_config('execution').value
        config['max_cycles'] = 200
        # Natural DB-clock expiry, no fixture mutation of lease_expires_at.
        config['worker'].update(lease_seconds=4, statement_timeout_seconds=1)
        config['polling'].update(operation_seconds=3, shutdown_grace=2, attempts_per_cycle=1,
                                 idle_initial=.1, idle_cap=.1)
        with tempfile.TemporaryDirectory(prefix='corner_force_rollback_') as folder:
            config_path, approval_path = Path(folder) / 'config.json', Path(folder) / 'approval.json'
            config_path.write_text(d.canonical(config)); approval_path.write_text(self.host_approval.document)
            children = []
            def launch(mode):
                child = subprocess.Popen([sys.executable, '-B', '-u', str(ROOT / 'acceptance/host_process_probe.py'),
                    str(config_path), str(approval_path), mode], cwd=ROOT, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    env=dict(os.environ, CORNER_HOST_TEST_PASSWORD=self.passwords['execution']))
                events = queue.Queue()
                def read():
                    for line in child.stdout: events.put(json.loads(line))
                thread = threading.Thread(target=read, daemon=True); thread.start()
                children.append((child, thread))
                return child, events
            def event(events, name):
                while True:
                    item = events.get(timeout=20)
                    self.assertNotEqual('probe_error', item.get('event'))
                    if item.get('event') == name: return item
            try:
                child, events = launch('force_transaction')
                event(events, 'ready'); event(events, 'completion_uncommitted')
                with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                    prepared = versioned_dispatch.prepared(cur, request['id'])
                self.assertIsNotNone(prepared)
                self.assertEqual('forced_exit', windows_shutdown.stop_instance('execution', self.sid,
                    Path(folder) / 'instance.json', graceful_drain_timeout=.15, hard_stop_verification_timeout=3))
                self.assertEqual(137, child.wait(timeout=5))
                # Acquiring this lock proves the terminated transaction released it.
                with self.conn.cursor() as cur:
                    cur.execute("SET LOCAL lock_timeout='5s'")
                    cur.execute('SELECT status,completed_at FROM corner.work_executions WHERE work_request_id=%s FOR UPDATE', (request['id'],))
                    self.assertEqual(('leased', None), cur.fetchone())
                    cur.execute('SELECT count(*) FROM corner.opportunity_occurrences WHERE qualification_decision_id=%s',
                                (request['qualification_decision_id'],))
                    self.assertEqual(0, cur.fetchone()[0])
                self.conn.commit()  # Release test inspection lock before restart.
                restarted, events = launch('bounded')
                event(events, 'ready')
                # Stop once completion is reported, keeping this proof bounded.
                while True:
                    report = events.get(timeout=20)
                    self.assertNotEqual('probe_error', report.get('event'))
                    if report.get('counts', {}).get('completed'):
                        self.assertEqual(1, report['counts']['reclaimed']); break
                self.assertEqual('graceful_exit', windows_shutdown.stop_instance('execution', self.sid,
                    Path(folder) / 'instance.json', graceful_drain_timeout=3, hard_stop_verification_timeout=3))
                self.assertEqual(0, restarted.wait(timeout=5))
                self.assertEqual('completed', self.execution(request)['status'])
                self.assertEqual(prepared['id'], self.execution(request)['prepared_command_id'])
                with self.conn.cursor() as cur:
                    cur.execute('SELECT count(*) FROM corner.opportunity_occurrences WHERE qualification_decision_id=%s',
                                (request['qualification_decision_id'],))
                    self.assertEqual(1, cur.fetchone()[0])
            finally:
                for child, thread in children:
                    if child.poll() is None: child.kill()
                    child.wait(timeout=5); thread.join(timeout=2)
                    child.stdout.close(); child.stderr.close()
