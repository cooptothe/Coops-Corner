"""Kills only explicitly spawned disposable probe processes; not a WinSW test."""
import copy
import ctypes as c
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from corner import windows_control as control, windows_shutdown as shutdown

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt', 'native Windows process-instance tests')
class ShutdownTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='corner_shutdown_test_')
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'instance.json'
        self.sid = control.current_sid()

    def child(self, mode='hung'):
        child = subprocess.Popen([sys.executable, '-B', '-u', str(ROOT / 'acceptance/shutdown_probe.py'),
            str(self.path), mode], cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True)
        def cleanup():
            if child.poll() is None: child.kill()
            child.wait(timeout=5); child.stdout.close(); child.stderr.close()
        self.addCleanup(cleanup)
        output = queue.Queue()
        threading.Thread(target=lambda: output.put(child.stdout.readline()), daemon=True).start()
        self.assertEqual('ready\n', output.get(timeout=10))
        return child

    def stop(self, path=None, grace=.15):
        return shutdown.stop_instance('health', self.sid, path or self.path,
            graceful_drain_timeout=grace, hard_stop_verification_timeout=3)

    def record(self):
        # Python's ordinary open does not share DELETE with the live owner.
        kernel, _ = shutdown.api()
        handle = kernel.CreateFileW(str(self.path), 0x80000000, 7, None, 3, 0x00200000, None)
        self.assertNotEqual(shutdown.INVALID_HANDLE, handle)
        try: return shutdown.read_record(kernel, handle, 'health', self.sid)
        finally: kernel.CloseHandle(handle)

    def test_cooperative_exit_does_not_force(self):
        child = self.child('cooperative')
        self.assertEqual('graceful_exit', self.stop(grace=3))
        self.assertEqual(0, child.wait(timeout=3))
        self.assertFalse(self.path.exists())

    def test_hung_drain_forces_exact_process_with_bounded_confirmation(self):
        child = self.child()
        before = time.monotonic()
        self.assertEqual('forced_exit', self.stop())
        self.assertLess(time.monotonic() - before, 4)
        self.assertEqual(shutdown.FORCED_EXIT_CODE, child.wait(timeout=3))
        self.assertFalse(self.path.exists())

    def test_fixed_role_helper_forces_without_database_driver_or_stdin(self):
        child = self.child()
        code = "import sys; sys.modules['psycopg2']=None; from corner.services.health import main; raise SystemExit(main())"
        result = subprocess.run([sys.executable, '-B', '-c', code, 'stop', '--expected-sid', self.sid,
            '--runtime-record', str(self.path), '--graceful-drain-timeout', '.15',
            '--hard-stop-verification-timeout', '3'], cwd=ROOT, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=5)
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        self.assertEqual('forced_exit', json.loads(result.stdout)['event'])
        self.assertEqual(137, child.wait(timeout=3))

    def test_wrong_pid_time_token_event_role_and_executable_refuse_termination(self):
        child = self.child()
        original = self.record()
        mutations = [lambda x: x.update(pid=os.getpid()),
            lambda x: x.update(creation_time=str(int(x['creation_time']) + 1)),
            lambda x: x.update(instance_token='0' * 32),
            lambda x: x.update(stop_event='Global\\wrong'),
            lambda x: x.update(service='execution'),
            lambda x: x.update(executable='C:\\wrong.exe')]
        for number, mutate in enumerate(mutations):
            record = copy.deepcopy(original); mutate(record)
            if number in (0, 1, 2):
                record['stop_event'] = control.endpoint_name('health', self.sid, shutdown.instance_key(record))
            path = Path(self.directory.name) / ('invalid-' + str(number) + '.json')
            with shutdown.RuntimeRecord(path, record):
                with self.assertRaises(control.HostControlError): self.stop(path)
            self.assertIsNone(child.poll())

    def test_stale_record_and_missing_record_never_terminate_new_instance(self):
        old = self.child('cooperative')
        record = self.record()
        self.assertEqual('graceful_exit', self.stop(grace=3)); old.wait(timeout=3)
        new = self.child()
        stale_path = Path(self.directory.name) / 'stale.json'
        with shutdown.RuntimeRecord(stale_path, record):
            try: self.assertEqual('already_exited', self.stop(stale_path))
            except control.HostControlError: pass  # OS may already have removed the old process object.
        with self.assertRaises(control.HostControlError): self.stop(Path(self.directory.name) / 'missing.json')
        self.assertIsNone(new.poll())

    def test_concurrent_duplicate_helpers_are_harmless(self):
        child = self.child('slow')
        results = []; errors = []
        def stop():
            try: results.append(self.stop(grace=3))
            except Exception as error: errors.append(error)
        threads = [threading.Thread(target=stop) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=5)
        self.assertFalse(errors, errors)
        self.assertEqual(['graceful_exit'] * 2, results)
        self.assertEqual(0, child.wait(timeout=3))

    def test_concurrent_force_helpers_wait_on_the_same_terminated_instance(self):
        child = self.child()
        results = []; errors = []
        def stop():
            try: results.append(self.stop())
            except Exception as error: errors.append(error)
        threads = [threading.Thread(target=stop) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=5)
        self.assertFalse(errors, errors)
        self.assertEqual(2, len(results))
        self.assertTrue(set(results) <= {'forced_exit', 'already_exited', 'graceful_exit'})
        self.assertIn('forced_exit', results)
        self.assertEqual(137, child.wait(timeout=3))

    def test_existing_record_is_not_overwritten_and_live_record_denies_writers(self):
        child = self.child()
        record = self.record()
        with self.assertRaises(OSError): self.path.write_text('{}')
        with self.assertRaises(control.HostControlError): shutdown.RuntimeRecord(self.path, record)
        self.assertEqual(record, self.record())
        self.assertIsNone(child.poll())

    def test_unprotected_identity_file_is_rejected(self):
        child = self.child()
        path = Path(self.directory.name) / 'unprotected.json'
        path.write_text(json.dumps(self.record()))
        with self.assertRaises(control.HostControlError): self.stop(path)
        self.assertIsNone(child.poll())

    def test_unconfirmed_termination_is_failure_not_success(self):
        child = self.child()
        with patch.object(shutdown, 'wait_until', return_value=False):
            with self.assertRaisesRegex(control.HostControlError, 'not confirmed'):
                self.stop()
        self.assertEqual(137, child.wait(timeout=3))

    def test_identity_is_rechecked_before_force(self):
        child = self.child()
        original = shutdown.verify_process
        calls = []
        def check(*args):
            calls.append(args[1])
            if len(calls) == 2: raise control.HostControlError('changed identity')
            return original(*args)
        with patch.object(shutdown, 'verify_process', side_effect=check):
            with self.assertRaisesRegex(control.HostControlError, 'changed identity'): self.stop()
        self.assertEqual(2, len(calls))
        self.assertEqual(calls[0], calls[1])  # Same open process handle, never a PID re-open.
        self.assertIsNone(child.poll())

    def test_invalid_deadlines_and_network_paths_fail_before_signal(self):
        for value in (0, -1, True, math.inf, math.nan, 3601):
            with self.assertRaises(control.HostControlError):
                shutdown.stop_instance('health', self.sid, self.path, graceful_drain_timeout=value,
                                       hard_stop_verification_timeout=1)
        for path in ('relative.json', '\\\\localhost\\share\\file.json', 'C:\\tmp\\file:stream'):
            with self.assertRaises(control.HostControlError): shutdown.local_path(path)
