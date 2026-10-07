"""Disposable DB rehearsal of harness bookkeeping, NOT an installed service test."""
import os
from pathlib import Path
import unittest

from test_deployment_database import LoginDatabase
import test_host_adapter_database as host_tests
from corner import deployment as d, host_service, polling
from run_scm_acceptance import Harness


@unittest.skipUnless(os.environ.get('CORNER_DEPLOYMENT_ACCEPTANCE') == '1', 'disposable DB opt-in')
class FixtureTests(LoginDatabase, unittest.TestCase):
    for name in ('select', 'evaluate', 'qualify', 'register', 'capture', 'command', 'record', 'app', 'opened',
                 'sql_error', 'enqueue', 'claim', 'prepare', 'execution', 'expire', 'routed', 'setUp', 'host_config'):
        locals()[name] = getattr(host_tests.HostDatabaseTests, name)

    def test_harness_request_frozen_identity_and_result_report(self):
        h = Harness(Path('unused'), None, None, self, {'work': []})
        request = h.request()
        config = self.host_config('execution').value
        config['worker'].update(lease_seconds=12, statement_timeout_seconds=1)
        config['polling'].update(operation_seconds=3, shutdown_grace=2, attempts_per_cycle=1,
                                idle_initial=.1, idle_cap=.1)
        config = d.Configuration.parse(d.canonical(config), service='execution')
        runner, _ = host_service.build('execution', config, self.host_approval, stop=polling.Stop(),
                                      secret_provider=lambda _: self.passwords['execution'])
        reports = []
        runner.run(max_cycles=1, emit=reports.append)
        frozen = h.prepared(request)
        row = h.completed(request, frozen)
        self.assertEqual(1, row['claim_count'])
        self.assertEqual(request['id'], h.report['work'][0]['execution_work_request_id'])
        self.assertEqual(frozen, h.report['work'][0]['preparation_id'])
