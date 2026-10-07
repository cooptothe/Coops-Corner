"""Local adapter proof, NOT installed WinSW/SCM or service-account acceptance."""
from dataclasses import asdict
import ctypes as c
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock

from corner import deployment as d, polling, host_service as host, windows_control as control
from corner import windows_credentials as vault, versioned_dispatch


ROOT = Path(__file__).resolve().parents[1]


def configuration(service):
    return {'format': 'corner.host-service/1', 'environment': 'isolated_nonproduction',
        'production_positive_authorization': False,
        'database': {'host': '127.0.0.1', 'port': 5432, 'dbname': 'isolated'},
        'identities': {service: {'login': service, 'secret_ref': 'Corner/Postgres/' + service.capitalize()}},
        'authority': {'kind': 'service', 'identifier': 'host-adapter-test'},
        'polling': asdict(polling.PollSettings()),
        'worker': {'lease_seconds': 90, 'retry_seconds': 5, 'max_retries': 3, 'statement_timeout_seconds': 5},
        'work_kinds': ['ensure_occurrence'] if service == 'execution' else [],
        'partitions': [{'obligation': 'occurrence', 'channel_id': None}] if service == 'discovery' else [],
        'max_cycles': 1}


def approval(doc):
    return d.TargetApproval(d.canonical({'environment': doc['environment'], 'database': doc['database'],
        'authority': doc['authority'], 'handlers': versioned_dispatch.HANDLERS,
        'logins': {s: s for s in d.SERVICES}, 'windows_sids': {s: 'S-1-5-21-1-2-3-1001' for s in d.SERVICES}}))


class ConfigurationTests(unittest.TestCase):
    def test_fixed_single_identity_and_responsibility(self):
        for service in d.SERVICES:
            doc = configuration(service)
            self.assertEqual(doc, d.Configuration.parse(d.canonical(doc), service=service).value)
            for other in set(d.SERVICES) - {service}:
                with self.assertRaises(ValueError): d.Configuration.parse(d.canonical(doc), service=other)

    def test_extra_identity_wrong_target_role_flag_and_responsibility_rejected(self):
        for service in d.SERVICES:
            mutations = [lambda x: x.update(role='execution'),
                lambda x: x['identities'][service].update(secret_ref='Corner/Postgres/Wrong'),
                lambda x: x['identities'].update(extra={'login': 'extra', 'secret_ref': 'extra'})]
            if service != 'execution': mutations.append(lambda x: x.update(work_kinds=['qualify']))
            if service != 'discovery': mutations.append(lambda x: x.update(partitions=[{'obligation': 'occurrence'}]))
            for mutate in mutations:
                doc = configuration(service); mutate(doc)
                with self.assertRaises(ValueError): d.Configuration.parse(d.canonical(doc), service=service)

    def test_combined_runner_and_environment_fallback_rejected(self):
        doc = configuration('execution'); config = d.Configuration.parse(d.canonical(doc), service='execution')
        with self.assertRaises(d.ReadinessError): d.connections(config, approval(doc))
        with self.assertRaises(d.ReadinessError): d.build_poller(config, approval(doc))

    def test_entry_modules_pin_role_and_reject_role_option(self):
        for service in d.SERVICES:
            module = importlib.import_module('corner.services.' + service)
            with patch.object(module, '_main', return_value=0) as call:
                self.assertEqual(0, module.main(['stop', '--expected-sid', 'test']))
                call.assert_called_once_with(service, ['stop', '--expected-sid', 'test'])
            with patch('sys.stderr'), self.assertRaises(SystemExit): module.main(['--role', 'execution'])

    def test_build_loads_one_vault_target_and_never_combines_runners(self):
        for service in d.SERVICES:
            doc = configuration(service); config = d.Configuration.parse(d.canonical(doc), service=service)
            seen = []
            def readiness(config, approved, factories):
                self.assertEqual({service}, set(factories))
                factories[service]()
            def secret(role, target, login):
                seen.append((role, target, login)); return 'synthetic-secret'
            with patch.object(control, 'verify_identity'), patch.object(d, 'readiness', side_effect=readiness), \
                 patch.object(vault, 'password', side_effect=secret), patch.object(d.psycopg2, 'connect'):
                runner, _ = host.build(service, config, approval(doc), stop=polling.Stop())
            self.assertEqual([(service, 'Corner/Postgres/' + service.capitalize(), service)], seen)
            if service == 'health': self.assertIsInstance(runner, host.HealthRunner)
            else:
                self.assertEqual(tuple(doc['work_kinds']), runner.kinds)
                self.assertEqual(len(doc['partitions']), len(runner.partitions))
                denied = runner.backend.execute_connect if service == 'discovery' else runner.backend.discover_connect
                with self.assertRaises(d.ReadinessError): denied()

    def test_wrong_windows_identity_fails_before_credential_access(self):
        doc = configuration('health'); config = d.Configuration.parse(d.canonical(doc), service='health')
        with patch.object(control, 'verify_identity', side_effect=control.HostControlError('wrong identity')), \
             patch.object(vault, 'password') as read:
            with self.assertRaises(control.HostControlError): host.build('health', config, approval(doc), stop=polling.Stop())
            read.assert_not_called()

    def test_discovery_only_poller_has_no_execution_attempts(self):
        backend = Mock()
        del backend.stop; del backend.settings
        backend.discover.return_value = ({'next_cursor': None, 'items': [],
            'counts': dict.fromkeys(('newly_requested', 'invalid', 'blocked', 'pending', 'fulfilled'), 0)}, None)
        runner = polling.Poller(backend, kinds=(), partitions=[polling.Partition('occurrence')])
        result = runner.run_cycle()
        backend.execute.assert_not_called()
        self.assertEqual(1, result['counts']['pages'])
        with self.assertRaises(ValueError): polling.Poller(backend, kinds=(), partitions=[])

    def test_vault_decoding_and_binding_without_writing_credentials(self):
        entry = (1, 'Corner/Postgres/Health', 'health_login', 2, 'test-only'.encode('utf-16-le'))
        with patch.object(vault, '_read_entry', return_value=entry) as read:
            self.assertEqual('test-only', vault.password('health', entry[1], entry[2]))
            read.assert_called_once_with(entry[1])
            with self.assertRaises(vault.CredentialError): vault.password('discovery', entry[1], entry[2])
        for index, bad in ((0, 2), (1, 'other'), (2, 'execution_login'), (3, 1), (4, b'x'), (4, b'\0\0')):
            invalid = list(entry); invalid[index] = bad
            with patch.object(vault, '_read_entry', return_value=invalid):
                with self.assertRaises(vault.CredentialError): vault.password('health', entry[1], entry[2])


@unittest.skipUnless(os.name == 'nt', 'native Windows IPC proof')
class NativeStopTests(unittest.TestCase):
    def setUp(self):
        self.sid = control.current_sid()

    def test_native_signal_duplicate_and_fresh_restart(self):
        stop = polling.Stop()
        with control.StopEndpoint('health', self.sid, stop):
            self.assertEqual('stop_requested', control.signal_stop('health', self.sid))
            self.assertEqual('stop_requested', control.signal_stop('health', self.sid))
            self.assertTrue(stop.wait(2))
        fresh = polling.Stop()
        with control.StopEndpoint('health', self.sid, fresh): self.assertFalse(fresh.wait(.1))
        self.assertEqual('not_running', control.signal_stop('health', self.sid))

    def test_old_handle_blocks_restart_instead_of_inheriting_stop(self):
        kernel, _ = control.api()
        with control.StopEndpoint('health', self.sid, polling.Stop()) as endpoint:
            old_handle = kernel.OpenEventW(2, False, endpoint.name)
            self.assertTrue(old_handle)
        try:
            kernel.SetEvent(old_handle)
            with self.assertRaisesRegex(control.HostControlError, 'already exists'):
                control.StopEndpoint('health', self.sid, polling.Stop())
        finally: kernel.CloseHandle(old_handle)
        fresh = polling.Stop()
        with control.StopEndpoint('health', self.sid, fresh): self.assertFalse(fresh.wait(.1))

    def test_concurrent_instance_rejected_and_wrong_role_does_not_stop(self):
        stop = polling.Stop()
        with control.StopEndpoint('execution', self.sid, stop):
            with self.assertRaises(control.HostControlError): control.StopEndpoint('execution', self.sid, polling.Stop())
            self.assertEqual('not_running', control.signal_stop('discovery', self.sid))
            self.assertFalse(stop.wait(.1))
        with self.assertRaises(control.HostControlError): control.signal_stop('execution', 'S-1-5-18')

    def test_separate_stop_process_without_stdin_database_or_driver(self):
        stop = polling.Stop()
        with control.StopEndpoint('execution', self.sid, stop):
            # Any accidental PostgreSQL import fails. No stdin and no DB configuration.
            code = "import sys,json; sys.modules['psycopg2']=None; from corner.windows_control import signal_stop; print(json.dumps({'event':signal_stop('execution',sys.argv[1])}))"
            result = subprocess.run([sys.executable, '-B', '-c', code, self.sid],
                cwd=ROOT, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual('stop_requested', json.loads(result.stdout)['event'])
            self.assertTrue(stop.wait(2))

    def test_endpoint_available_while_database_startup_is_unavailable(self):
        from corner.host_entry import main
        entered = threading.Event()
        result = []
        doc = configuration('health')
        approved = json.loads(approval(doc).document)
        approved['windows_sids']['health'] = self.sid
        def unavailable(*args, stop, **kwargs):
            entered.set()
            if not stop.wait(3): raise AssertionError('startup did not receive local stop')
            raise d.ReadinessError('database unavailable')
        with tempfile.TemporaryDirectory(prefix='corner_ipc_test_') as folder:
            config_path, approval_path = Path(folder) / 'config.json', Path(folder) / 'approval.json'
            config_path.write_text(d.canonical(doc)); approval_path.write_text(d.canonical(approved))
            with patch.object(host, 'build', side_effect=unavailable), patch('corner.host_entry.emit'):
                thread = threading.Thread(target=lambda: result.append(main('health',
                    ['run', '--config', str(config_path), '--approval', str(approval_path),
                     '--runtime-record', str(Path(folder) / 'instance.json')])) )
                thread.start()
                try:
                    self.assertTrue(entered.wait(2))
                    self.assertEqual('stop_requested', control.signal_stop('health', self.sid))
                finally: thread.join(timeout=5)
                self.assertFalse(thread.is_alive())
                self.assertEqual([2], result)  # Startup failure, not fake readiness.

    def test_restricted_native_dacl_contains_only_system_and_current_user(self):
        from ctypes import wintypes as w
        kernel, advapi = control.api()
        advapi.GetSecurityInfo.argtypes = [w.HANDLE, c.c_int, w.DWORD, w.LPVOID, w.LPVOID, w.LPVOID, w.LPVOID, c.POINTER(w.LPVOID)]
        advapi.GetSecurityInfo.restype = w.DWORD
        advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [w.LPVOID, w.DWORD, w.DWORD, c.POINTER(w.LPWSTR), w.LPVOID]
        advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = w.BOOL
        with control.StopEndpoint('health', self.sid, polling.Stop()) as endpoint:
            descriptor = w.LPVOID(); text = w.LPWSTR()
            self.assertEqual(0, advapi.GetSecurityInfo(endpoint.handle, 6, 4, None, None, None, None, c.byref(descriptor)))
            try:
                self.assertTrue(advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(descriptor, 1, 4, c.byref(text), None))
                self.assertEqual('D:P(A;;0x1f0003;;;SY)(A;;0x1f0003;;;' + self.sid + ')', text.value)
            finally:
                if text: kernel.LocalFree(c.cast(text, w.LPVOID))
                kernel.LocalFree(descriptor)
