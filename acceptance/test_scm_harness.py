"""Non-installed harness checks. These NEVER claim SCM acceptance passed."""
from contextlib import redirect_stderr, contextmanager
import io
import json
import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

import run_scm_acceptance as harness
import scm_native


class HarnessTests(unittest.TestCase):
    def test_credential_encoding_and_binding_precede_impersonation(self):
        account = scm_native.Account.__new__(scm_native.Account)
        account.advapi = object(); account.credential_written = False
        impersonating = False
        actions = []
        @contextmanager
        def impersonate():
            nonlocal impersonating
            impersonating = True; actions.append('impersonate')
            try: yield
            finally: impersonating = False; actions.append('revert')
        account.impersonate = impersonate
        case = self
        class ProtectedPassword(str):
            def encode(self, *args, **kwargs):
                if impersonating: raise LookupError('codec unavailable in protected administrator runtime')
                actions.append('encode')
                return super().encode(*args, **kwargs)
        def bind(library, name, signature):
            self.assertFalse(impersonating)
            self.assertEqual('CredWriteW', name)
            actions.append('bind')
            def write(pointer, flags):
                case.assertTrue(impersonating)
                entry = pointer._obj
                case.assertEqual('Corner/Postgres/Execution', entry.target)
                case.assertEqual('disposable-login', entry.username)
                case.assertEqual(2, entry.persist)
                case.assertEqual('test-\u03a9'.encode('utf-16-le'), c.string_at(entry.blob, entry.blob_size))
                actions.append('write'); return True
            return write
        with patch.object(scm_native, 'function', side_effect=bind):
            account.credential('disposable-login', ProtectedPassword('test-\u03a9'))
        self.assertTrue(account.credential_written)
        self.assertEqual(['encode', 'bind', 'impersonate', 'write', 'revert'], actions)

    def test_lazy_codec_import_failure_reproduces_lookup_error_in_fresh_python(self):
        # No vault or identity mutation. Simulate inaccessible codec source in a
        # fresh interpreter so another test cannot accidentally warm its cache.
        program = '''
import sys
class InaccessibleCodec:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'encodings.utf_16_le':
            # An unreadable module search directory leaves no importable spec.
            raise ModuleNotFoundError('synthetic protected runtime')
sys.meta_path.insert(0, InaccessibleCodec())
try:
    'synthetic'.encode('utf-16-le')
except LookupError:
    print('reproduced_lookup_error')
else:
    raise SystemExit(2)
'''
        result = subprocess.run([sys.executable, '-I', '-B', '-c', program],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(0, result.returncode)
        self.assertEqual('reproduced_lookup_error', result.stdout.strip())

    def test_failure_location_does_not_include_secret_message_or_locals(self):
        try:
            password = 'synthetic-secret-do-not-print'
            raise LookupError(password)
        except LookupError as error:
            report = harness.safe_error(error)
        self.assertEqual('test_scm_harness.py', report['location']['file'])
        self.assertNotIn(password, json.dumps(report))

    def lookup_functions(self, *, first_error=122, domain='TESTHOST', kind=1):
        def computer(buffer, size):
            buffer.value = 'TESTHOST'
            return True
        def lookup(system, name, sid, size, domain_buffer, domain_size, use):
            self.assertIsNone(system)
            self.assertEqual('TESTHOST\\testuser', name)
            if sid is None:
                size._obj.value = 68 if first_error == 122 else 0
                domain_size._obj.value = 64 if first_error == 122 else 0
                c.set_last_error(first_error)
                return False
            domain_buffer.value = domain
            use._obj.value = kind
            return True
        return lambda library, name, args, result=w.BOOL: {
            'GetComputerNameW': computer, 'LookupAccountNameW': lookup}[name]

    def test_account_lookup_uses_machine_name_for_both_calls(self):
        with patch.object(scm_native, 'function', side_effect=self.lookup_functions()):
            self.assertEqual(68, len(scm_native.local_account_sid(None, None, 'testuser')))

    def test_failed_sizing_lookup_stops_before_empty_buffer_allocation(self):
        with patch.object(scm_native, 'function', side_effect=self.lookup_functions(first_error=1332)):
            with self.assertRaises(scm_native.NativeError) as error:
                scm_native.local_account_sid(None, None, 'testuser')
        self.assertEqual(('LookupAccountNameSize', 1332), (error.exception.operation, error.exception.code))

    def test_lookup_rejects_nonlocal_account_or_nonuser_sid(self):
        for values in ({'domain': 'ANOTHERDOMAIN'}, {'kind': 2}):
            with patch.object(scm_native, 'function', side_effect=self.lookup_functions(**values)):
                with self.assertRaises(scm_native.NativeError) as error:
                    scm_native.local_account_sid(None, None, 'testuser')
                self.assertEqual('RefuseNonLocalUserSID', error.exception.operation)

    @unittest.skipUnless(os.name == 'nt', 'read-only Windows account lookup')
    def test_native_lookup_current_local_user_matches_process_token(self):
        # No account/service/vault mutation. Exercise the real API, not a mock.
        from corner import windows_control
        kernel = c.WinDLL('kernel32', use_last_error=True)
        advapi = c.WinDLL('advapi32', use_last_error=True)
        user = c.create_unicode_buffer(257); size = w.DWORD(len(user))
        scm_native.check(scm_native.function(advapi, 'GetUserNameW', [w.LPWSTR, c.POINTER(w.DWORD)])(
            user, c.byref(size)), 'GetUserName')
        sid = scm_native.local_account_sid(kernel, advapi, user.value)
        text = w.LPWSTR()
        scm_native.check(scm_native.function(advapi, 'ConvertSidToStringSidW', [w.LPVOID, c.POINTER(w.LPWSTR)])(
            sid, c.byref(text)), 'ConvertSid')
        try:
            self.assertEqual(windows_control.current_sid(), text.value)
        finally:
            scm_native.function(kernel, 'LocalFree', [w.LPVOID], w.LPVOID)(c.cast(text, w.LPVOID))

    def test_missing_consent_does_not_even_run_preflight(self):
        with patch('host_preflight.collect') as preflight, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit): harness.main(['--winsw', 'unused.exe'])
        preflight.assert_not_called()

    def test_failed_preflight_never_provisions(self):
        with patch('host_preflight.collect', return_value={'preflight_ok': False}), patch.object(
                scm_native, 'Account') as account, patch('builtins.print'):
            self.assertEqual(2, harness.main(['--winsw', 'unused.exe', '--execute']))
        account.assert_not_called()

    def test_xml_fixed_role_private_runtime_explicit_stop_bounds_no_secrets(self):
        xml = ET.fromstring(harness.service_xml('CornerHost123456789abc', Path('C:/Private Stage'), 'S-1-5-21-123'))
        self.assertEqual('Manual', xml.findtext('startmode'))
        self.assertEqual('15 sec', xml.findtext('stoptimeout'))
        self.assertIn('scm_service_probe.py', xml.findtext('startarguments'))
        self.assertIn('-I -B -u', xml.findtext('startarguments'))
        self.assertIn('--graceful-drain-timeout 5', xml.findtext('stoparguments'))
        self.assertIn('--hard-stop-verification-timeout 3', xml.findtext('stoparguments'))
        self.assertNotIn('--config', xml.findtext('stoparguments'))
        self.assertNotIn('--role', ET.tostring(xml, encoding='unicode'))
        for name in ('serviceaccount', 'password', 'env'):
            self.assertIsNone(xml.find(name))

    def test_native_targets_reject_existing_or_arbitrary_names_before_api(self):
        for name in ('Spooler', 'CornerHost', '../x', 'CornerHost123456789ABC'):
            with self.assertRaises(ValueError): scm_native.Service(name)
        for suffix in ('Administrator', '123', '../test', '123456789ABC'):
            with self.assertRaises(ValueError): scm_native.Account(suffix)

    def test_error_reports_never_stringify_secret_bearing_exceptions(self):
        self.assertEqual({'error_type': 'RuntimeError'}, harness.safe_error(RuntimeError('password=secret')))
        self.assertEqual({'error_type': 'NativeError', 'operation': 'CreateDisposableService', 'code': 5},
                         harness.safe_error(scm_native.NativeError('CreateDisposableService', 5)))

    def test_wait_has_finite_timeout_and_does_not_swallow_errors(self):
        with patch.object(harness.time, 'monotonic', side_effect=[0, 2]):
            with self.assertRaises(TimeoutError): harness.wait_for(lambda: False, 1)
        with self.assertRaises(ValueError): harness.wait_for(Mock(side_effect=ValueError()))

    def test_corrupt_or_wrong_stop_outcome_is_not_success(self):
        with tempfile.TemporaryDirectory() as folder:
            stage = Path(folder); (stage / 'logs').mkdir()
            service = Mock(); service.status.return_value = {'state': 1}
            h = harness.Harness(stage, Mock(), service, Mock(), {'scm_states': []})
            def stop():
                (stage / 'logs/stop-results.jsonl').write_text(json.dumps({'event': 'host_adapter_error', 'helper_elapsed_seconds': 1}) + '\n')
            service.stop.side_effect = stop
            with self.assertRaises(AssertionError): h.stop('graceful_exit')
            self.assertEqual([], h.report['scm_states'])

    def test_bad_event_cannot_be_mistaken_for_readiness(self):
        service = Mock(); service.name = 'CornerHost123456789abc'
        with tempfile.TemporaryDirectory() as folder:
            stage = Path(folder); (stage / 'logs').mkdir()
            (stage / 'logs' / (service.name + '.out.log')).write_text('{"event":"host_adapter_error"}\n')
            h = harness.Harness(stage, Mock(), service, Mock(), {})
            with self.assertRaises(AssertionError): h.event('ready')


if __name__ == '__main__': unittest.main()
