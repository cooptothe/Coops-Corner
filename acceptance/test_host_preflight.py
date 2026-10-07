"""Read-only preflight output semantics, without provisioning or database access."""
import json
import unittest
from unittest.mock import patch

import host_preflight as preflight


class PreflightTests(unittest.TestCase):
    def checks(self):
        return {'windows_access': {'administrator': True, 'scm_create_service_access': True, 'scm_error': 0},
            'artifact_check': {'sha256_matches': True, 'size_matches': True, 'executed': False},
            'dependency_check': {'python_64_bit': True, 'host_modules_imported': True},
            'database_check': {'postgresql_18': True, 'setup_can_create_disposable_database': True,
                               'setup_can_create_disposable_roles': True}}

    def run_with(self, values):
        from contextlib import ExitStack
        with ExitStack() as stack:
            for name, value in values.items():
                stack.enter_context(patch.object(preflight, name,
                    **({'side_effect': value} if isinstance(value, Exception) else {'return_value': value})))
            return preflight.collect('not-executed.exe')

    def test_success_never_claims_installed_acceptance(self):
        report = self.run_with(self.checks())
        self.assertTrue(report['preflight_ok'])
        self.assertFalse(report['installation_performed'])
        self.assertEqual('not_performed', report['installed_acceptance'])

    def test_failure_is_not_zero_or_secret_bearing_exception(self):
        for name in self.checks():
            values = self.checks(); values[name] = RuntimeError('password=do-not-print')
            report = self.run_with(values)
            self.assertFalse(report['preflight_ok'])
            self.assertNotIn('do-not-print', json.dumps(report))
            self.assertEqual('check_failed', report['checks'][{'windows_access': 'windows',
                'artifact_check': 'winsw', 'dependency_check': 'python', 'database_check': 'database'}[name]]['status'])

    def test_each_required_boolean_fails_closed(self):
        for name, result in self.checks().items():
            for key, value in result.items():
                if value is not True: continue
                values = self.checks(); values[name][key] = False
                self.assertFalse(self.run_with(values)['preflight_ok'], (name, key))
