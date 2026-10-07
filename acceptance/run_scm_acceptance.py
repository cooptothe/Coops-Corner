"""Explicitly opted-in, administrator-run disposable WinSW/SCM acceptance.

Creates ONE fresh Windows account/service and a fresh local PostgreSQL fixture.
No production database writes, existing-account adoption, or secret files. Keeps
the private staging/evidence directory; removes owned service/account/DB on exit.
Interrupted or failed cleanup is reported, never called a successful acceptance.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from uuid import uuid4
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'acceptance'))


def require(value, message):
    if not value:
        raise AssertionError(message)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, default=str, allow_nan=False), encoding='utf-8')


def wait_for(check, seconds=30):
    end = time.monotonic() + seconds
    while True:
        result = check()
        if result:
            return result
        if time.monotonic() >= end:
            raise TimeoutError('bounded acceptance wait expired')
        time.sleep(.1)


def service_xml(name, stage, sid):
    """No serviceaccount/password/env elements. SCM receives account in memory."""
    doc = ET.Element('service')
    python = stage / 'python/python.exe'
    probe = stage / 'app/scm_service_probe.py'
    common = [str(python), '-I', '-B', '-u', str(probe)]
    values = {
        'id': name, 'name': name, 'description': 'Disposable isolated Corner host acceptance',
        'executable': str(python), 'stopexecutable': str(python),
        'startarguments': subprocess.list2cmdline(common[1:] + ['run', '--config', str(stage / 'app/config.json'),
            '--approval', str(stage / 'app/approval.json'), '--runtime-record', str(stage / 'runtime/instance.json')]),
        'stoparguments': subprocess.list2cmdline(common[1:] + ['stop', '--expected-sid', sid,
            '--runtime-record', str(stage / 'runtime/instance.json'), '--graceful-drain-timeout', '5',
            '--hard-stop-verification-timeout', '3']),
        'workingdirectory': str(stage / 'app'), 'logpath': str(stage / 'logs'),
        'startmode': 'Manual', 'stoptimeout': '15 sec',
    }
    for key, value in values.items():
        ET.SubElement(doc, key).text = value
    ET.SubElement(doc, 'log', {'mode': 'append'})
    return ET.tostring(doc, encoding='unicode')


def stage_runtime(stage, sid, winsw, name):
    from scm_native import directory
    directory(stage, sid)
    for part in ('app', 'python', 'runtime', 'logs'):
        directory(stage / part, sid, writable=part in ('runtime', 'logs'))
    source = Path(sys.base_prefix)
    for item in source.iterdir():
        if item.is_file() and (item.suffix.lower() in ('.exe', '.dll') or item.name == 'LICENSE.txt'):
            shutil.copyfile(item, stage / 'python' / item.name)
    for part in ('Lib', 'DLLs'):
        shutil.copytree(source / part, stage / 'python' / part,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    # Copy only module sources, not repository config/.env/fixtures or secrets.
    for item in (ROOT / 'corner').rglob('*.py'):
        target = stage / 'app/corner' / item.relative_to(ROOT / 'corner')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(item, target)
    shutil.copyfile(ROOT / 'acceptance/scm_service_probe.py', stage / 'app/scm_service_probe.py')
    binary = stage / (name + '.exe')
    shutil.copyfile(winsw, binary)
    from host_preflight import artifact_check
    pinned = artifact_check(binary)
    require(pinned['sha256_matches'] and pinned['size_matches'], 'staged WinSW pin mismatch')
    (stage / (name + '.xml')).write_text(service_xml(name, stage, sid), encoding='utf-8')
    write_json(stage / 'staged-source-sha256.json', {
        str(p.relative_to(stage)): digest(p) for p in (stage / 'app').rglob('*.py')})
    return binary


class Harness:
    report_format = 'corner.installed-host-acceptance/1'
    scope = 'one exact wrapped execution process; no descendants; no credential rotation'
    work_kinds = ['ensure_occurrence']

    def __init__(self, stage, account, service, fixture, report):
        self.stage, self.account, self.service, self.fixture, self.report = stage, account, service, fixture, report
        self.offset = 0
        self.extra_secrets = []

    def events(self):
        result = []
        path = self.stage / 'logs' / (self.service.name + '.out.log')
        if path.exists():
            for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
                try: result.append(json.loads(line))
                except ValueError: pass  # WinSW may interleave non-JSON diagnostics.
        return result

    def event(self, name):
        def find():
            events = self.events()[self.offset:]
            require(not any(e.get('event') in ('host_adapter_error', 'acceptance_probe_error') for e in events),
                    'service adapter reported failure; inspect private logs')
            return next((e for e in events if e.get('event') == name), None)
        return wait_for(find)

    def mode(self, value):
        write_json(self.stage / 'app/mode.json', {'mode': value})

    def record(self):
        from corner import windows_shutdown as shutdown
        kernel, advapi = shutdown.api()
        with self.account.impersonate():
            handle = kernel.CreateFileW(str(self.stage / 'runtime/instance.json'), 0x80000000, 7, None, 3, 0x00200000, None)
            require(handle != shutdown.INVALID_HANDLE, 'runtime record missing')
            try:
                shutdown.verify_record_acl(kernel, advapi, handle, self.account.sid)
                record = shutdown.read_record(kernel, handle, 'execution', self.account.sid)
            finally: kernel.CloseHandle(handle)
        require(Path(record['executable']).resolve() == (self.stage / 'python/python.exe').resolve(), 'wrong wrapped executable')
        process = kernel.OpenProcess(0x100000 | 0x1000 | 1, False, record['pid'])
        require(process, 'cannot open exact wrapped process')
        try: shutdown.verify_process(kernel, process, record)
        finally: kernel.CloseHandle(process)
        self.report['processes'].append({k: v for k, v in record.items() if k not in ('instance_token', 'stop_event')})
        return record

    def start(self, mode):
        self.offset = len(self.events())
        self.mode(mode)
        self.service.start()
        wait_for(lambda: self.service.status()['state'] == 4)
        self.event('ready')
        record = self.record()
        self.report['scm_states'].append(dict(self.service.status(), event='started', mode=mode))
        return record

    def stop(self, expected):
        log = self.stage / 'logs/stop-results.jsonl'
        before = len(log.read_text().splitlines()) if log.exists() else 0
        started = time.monotonic()
        self.service.stop()  # Real ControlService(SERVICE_CONTROL_STOP), not direct app IPC.
        wait_for(lambda: self.service.status()['state'] == 1, 20)
        outcomes = [json.loads(line) for line in log.read_text().splitlines()[before:]]
        require(len(outcomes) == 1 and outcomes[0]['event'] == expected, 'unexpected stop helper outcome')
        require(outcomes[0]['helper_elapsed_seconds'] < 10, 'helper exceeded grace/verification allowance')
        elapsed = time.monotonic() - started
        require(elapsed < 20, 'SCM stop exceeded outer verification bound')
        require(not (self.stage / 'runtime/instance.json').exists(), 'stale runtime identity remains')
        self.report['scm_states'].append(dict(self.service.status(), event='stopped', stop_result=expected, elapsed_seconds=elapsed))

    def request(self):
        q = self.fixture.qualify(self.fixture.evaluation)
        request = self.fixture.enqueue(sources={'qualification_decision_id': q['id']})
        self.fixture.conn.commit()
        return request

    def prepared(self, request):
        from psycopg2.extras import RealDictCursor
        from corner.versioned_dispatch import prepared
        with self.fixture.conn.cursor(cursor_factory=RealDictCursor) as cur:
            result = prepared(cur, request['id'])
        self.fixture.conn.commit()
        require(result, 'preparation did not commit')
        return result['id']

    def completed(self, request, prepared_id):
        def read():
            row = self.fixture.execution(request)
            self.fixture.conn.commit()
            require(row['status'] not in ('blocked', 'waiting'), 'work failed to complete')
            return row if row['status'] == 'completed' else None
        row = wait_for(read, 45)
        require(row['prepared_command_id'] == prepared_id, 'frozen preparation changed')
        with self.fixture.conn.cursor() as cur:
            cur.execute('SELECT id FROM corner.opportunity_occurrences WHERE qualification_decision_id=%s',
                        (request['qualification_decision_id'],))
            ids = cur.fetchall()
        self.fixture.conn.commit()
        require(len(ids) == 1, 'expected exactly one authoritative occurrence')
        self.report['work'].append({'request_id': request['id'], 'preparation_id': prepared_id,
            'execution_work_request_id': row['work_request_id'], 'result_id': ids[0][0], 'claim_count': row['claim_count'], 'status': row['status']})
        return row

    def run(self):
        self.report['phase'] = 'repeat_stop_start'
        for _ in range(2):
            self.start('normal'); self.stop('graceful_exit')
        self.report['checks']['repeat_scm_graceful_stop_start'] = 'passed'
        self.report['phase'] = 'drain_active_completion'
        request = self.request()
        self.start('drain'); self.event('acceptance_checkpoint')
        frozen = self.prepared(request)
        self.stop('graceful_exit'); self.completed(request, frozen)
        self.report['checks']['scm_drains_active_completion'] = 'passed'

        self.report['phase'] = 'force_stop_transaction'
        request = self.request()
        self.start('hang_transaction'); self.event('acceptance_checkpoint')
        frozen = self.prepared(request)
        self.stop('forced_exit')
        with self.fixture.conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout='5s'")
            cur.execute('SELECT status,completed_at FROM corner.work_executions WHERE work_request_id=%s FOR UPDATE', (request['id'],))
            require(cur.fetchone() == ('leased', None), 'partial completion committed')
            cur.execute('SELECT count(*) FROM corner.opportunity_occurrences WHERE qualification_decision_id=%s',
                        (request['qualification_decision_id'],))
            require(cur.fetchone()[0] == 0, 'partial domain result committed')
        self.fixture.conn.commit()
        self.start('normal')
        require(self.completed(request, frozen)['claim_count'] >= 2, 'lease was not reclaimed')
        self.stop('graceful_exit')
        self.report['checks']['scm_force_stop_rollback_and_frozen_reclaim'] = 'passed'

        self.report['phase'] = 'abrupt_death_supervisor_restart'
        request = self.request()
        old = self.start('hang_prepared'); self.event('acceptance_checkpoint')
        frozen = self.prepared(request)
        previous_wrapper = self.service.status()['pid']
        self.offset = len(self.events())
        self.mode('normal')  # Only the restarted process reads the new fault mode.
        from corner import windows_shutdown as shutdown
        kernel, _ = shutdown.api()
        process = kernel.OpenProcess(0x100000 | 0x1000 | 1, False, old['pid'])
        require(process, 'cannot open instance for crash test')
        try:
            shutdown.verify_process(kernel, process, old)
            require(kernel.TerminateProcess(process, 137), 'crash injection failed')
            require(shutdown.wait_until(kernel, process, time.monotonic() + 5), 'crash not confirmed')
        finally: kernel.CloseHandle(process)
        wait_for(lambda: self.service.status()['state'] == 4 and self.service.status()['pid'] != previous_wrapper, 45)
        self.event('ready')
        new = self.record()
        require(old['instance_token'] != new['instance_token'], 'restart reused process identity')
        require(self.completed(request, frozen)['claim_count'] >= 2, 'restart did not reclaim frozen work')
        self.stop('graceful_exit')
        self.report['checks']['scm_supervisor_restart_and_exactly_once_recovery'] = 'passed'


def retain_scm_events(stage, name):
    # Unique disposable name bounds this query; never export unrelated logs.
    query = "*[System[Provider[@Name='Service Control Manager']] and EventData[Data='" + name + "']]"
    result = subprocess.run([str(Path(os.environ['SystemRoot']) / 'System32/wevtutil.exe'),
        'qe', 'System', '/q:' + query, '/f:xml', '/e:Events', '/c:100', '/uni:true'],
        capture_output=True, timeout=15)
    require(result.returncode == 0, 'SCM event query failed')
    text = result.stdout.decode('utf-16')
    root = ET.fromstring(text)
    require(len(root) > 0, 'no matching SCM events retained')
    (stage / 'scm-events.xml').write_text(text, encoding='utf-8')
    return {'count': len(root), 'sha256': digest(stage / 'scm-events.xml')}


def safe_error(error):
    from scm_native import NativeError
    result = {'error_type': type(error).__name__}
    if isinstance(error, NativeError):
        result.update(operation=error.operation, code=error.code)
    tb = error.__traceback__
    while tb is not None:
        # Code locations only: never locals, source lines or exception messages.
        result['location'] = {'file': Path(tb.tb_frame.f_code.co_filename).name,
                              'function': tb.tb_frame.f_code.co_name, 'line': tb.tb_lineno}
        tb = tb.tb_next
    # Never stringify arbitrary DB/credential exceptions.
    return result


def main(argv=None, *, harness_class=Harness):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--winsw', required=True, type=Path)
    parser.add_argument('--execute', action='store_true', help='Consent to disposable service/account/database creation and fault tests')
    args = parser.parse_args(argv)
    if not args.execute:
        parser.error('--execute is required; no resources were created')
    from host_preflight import collect
    preflight = collect(args.winsw)
    if not preflight['preflight_ok']:
        print(json.dumps(preflight, indent=2)); return 2
    from scm_native import Account, Service
    from test_host_adapter_database import HostDatabaseTests
    from corner import deployment as d
    suffix = uuid4().hex[:12]
    stage = Path(os.environ['ProgramData']) / ('CornerHostAcceptance_' + suffix)
    account, service, fixture = Account(suffix), None, None
    report = {'format': harness_class.report_format, 'started_at': datetime.now(timezone.utc).isoformat(),
        'status': 'running', 'stage': str(stage), 'service': 'CornerHost' + suffix, 'account': account.name,
        'production_positive_authorization': False, 'preflight': preflight, 'checks': {}, 'processes': [],
        'scm_states': [], 'work': [], 'cleanup': {}, 'scope': harness_class.scope}
    database_setup = False
    try:
        report['phase'] = 'create_windows_identity'
        print('Creating fresh disposable account and private runtime; no existing service is modified.', flush=True)
        account.create()
        report['phase'] = 'stage_private_runtime'
        binary = stage_runtime(stage, account.sid, args.winsw.resolve(), report['service'])
        write_json(stage / 'report.json', report)
        database_setup = True
        report['phase'] = 'create_disposable_database'
        HostDatabaseTests.setUpClass()
        fixture = HostDatabaseTests(); fixture.setUp()
        report['database'] = fixture.database_name
        config = fixture.host_config('execution').value
        config['work_kinds'] = harness_class.work_kinds
        config['max_cycles'] = 10000
        config['worker'].update(lease_seconds=12, statement_timeout_seconds=1)
        config['polling'].update(operation_seconds=3, shutdown_grace=2, attempts_per_cycle=1,
                                 idle_initial=.1, idle_cap=.1)
        d.Configuration.parse(d.canonical(config), service='execution')
        write_json(stage / 'app/config.json', config)
        write_json(stage / 'app/approval.json', dict(fixture.approval_doc, windows_sids={'execution': account.sid}))
        report['phase'] = 'load_service_profile'
        account.load_profile()
        report['phase'] = 'write_service_credential'
        account.credential(fixture.logins['execution'], fixture.passwords['execution'])
        report['phase'] = 'unload_provisioning_profile'
        account.unload_profile()  # SCM must prove vault access without the harness holding the hive open.
        report['phase'] = 'install_test_service'
        service = Service(report['service']); service.install(binary, account)
        report['installed_configuration'] = service.configuration()
        require(report['installed_configuration']['account'].lower() == ('.\\' + account.name).lower(), 'wrong SCM service account')
        print('Installed disposable service. Running: ' + harness_class.scope, flush=True)
        harness = harness_class(stage, account, service, fixture, report)
        harness.run()
        report['phase'] = 'retain_and_check_evidence'
        report['scm_events'] = retain_scm_events(stage, report['service'])
        secret_values = [account.password, *fixture.passwords.values(), *harness.extra_secrets]
        evidence = [*stage.glob('*.xml'), *stage.glob('*.json'),
                    *(stage / 'app').glob('*.json'), *(stage / 'logs').glob('*')]
        for path in evidence:
            if not path.is_file(): continue
            raw = path.read_bytes()
            require(not any(secret.encode(encoding) in raw for secret in secret_values
                            for encoding in ('utf-8', 'utf-16-le')), 'secret found in acceptance evidence')
        report['checks']['retained_evidence_has_no_test_passwords'] = 'passed'
        report['status'] = 'passed'
    except (Exception, KeyboardInterrupt) as error:
        report['status'] = 'failed'; report['failure'] = safe_error(error)
    finally:
        # Never delete a running service/account or drop its DB out from underneath it.
        stopped = service is None or service.handle is None
        if service is not None:
            try:
                if service.handle:
                    service.disable_recovery()
                    if service.status()['state'] != 1:
                        service.stop(); wait_for(lambda: service.status()['state'] == 1, 25)
                service.delete(); stopped = True
                report['cleanup']['service'] = 'removed'
            except Exception as error:
                report['cleanup']['service'] = safe_error(error)
        if stopped:
            try:
                account.cleanup(); report['cleanup']['windows_account_profile_credential'] = 'removed'
            except Exception as error:
                report['cleanup']['windows_account_profile_credential'] = safe_error(error)
            if fixture is not None:
                if not fixture.doCleanups(): report['cleanup']['fixture'] = 'failed'
            if database_setup:
                HostDatabaseTests.doClassCleanups()
                errors = getattr(HostDatabaseTests, 'tearDown_exceptions', [])
                report['cleanup']['database_roles'] = [safe_error(e[1]) for e in errors] if errors else 'removed'
        else:
            report['cleanup']['remaining_resources'] = 'service/account/database retained; manual inspection required'
        if any(v != 'removed' for v in report['cleanup'].values()):
            report['status'] = 'failed_cleanup_required'
        if stage.exists():
            report['retained_log_sha256'] = {p.name: digest(p) for p in (stage / 'logs').glob('*') if p.is_file()}
            report['finished_at'] = datetime.now(timezone.utc).isoformat()
            write_json(stage / 'report.json', report)
        print(json.dumps(report, indent=2, default=str), flush=True)
    return 0 if report['status'] == 'passed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
