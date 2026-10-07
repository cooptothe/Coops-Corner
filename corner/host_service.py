"""Fixed-role Windows adapters over existing polling, readiness and health APIs.

No installation, combined runner, credential writes, or production evidence source.
"""
from dataclasses import asdict
from datetime import timedelta
from uuid import uuid4

from corner import deployment as d, polling, worker, channels, health
from corner import windows_control, windows_credentials


def forbidden_connection(**_):
    raise d.ReadinessError('connection outside fixed service responsibility')


class HealthRunner:
    def __init__(self, backend, connect, stop, process_id):
        self.backend, self.connect, self.stop = backend, connect, stop
        self.process_id = process_id

    def run(self, *, max_cycles, emit):
        if type(max_cycles) is not int or max_cycles < 1: raise ValueError('finite cycle count required')
        for index in range(max_cycles):
            if self.stop.is_set(): break
            try:
                with self.backend._operation(self.connect) as bounded_connect:
                    # read_health requests its connection timeout explicitly;
                    # _operation already enforces the same bound on its factory.
                    limits = health.HealthLimits(
                        connect_timeout_seconds=self.backend.settings.connect_timeout_seconds,
                        statement_timeout_ms=max(1, int(self.backend.worker_settings.statement_timeout.total_seconds() * 1000)))
                    snapshot = health.read_health(lambda *, connect_timeout: bounded_connect(), limits=limits)
                emit({'event': 'health', 'process_instance_id': self.process_id, 'snapshot': asdict(snapshot)})
            except polling.OperationAborted:
                if not self.stop.is_set(): emit({'event': 'health_error', 'reason': 'operation_budget_exceeded'})
            except Exception:
                # No fabricated zero snapshot or potentially credential-bearing exception.
                emit({'event': 'health_error', 'reason': 'read_failed'})
            if index + 1 < max_cycles and self.stop.wait(self.backend.settings.revisit_seconds): break


def build(service, config, approval, *, stop, secret_provider=None):
    d.require(config.service == service and service in d.SERVICES, 'entry point/configuration role mismatch')
    approved = approval.validate(config)
    expected_sid = approved['windows_sids'][service]
    windows_control.verify_identity(expected_sid)
    doc = config.value
    identity = doc['identities'][service]
    if secret_provider is None:
        secret_provider = lambda reference: windows_credentials.password(service, reference, identity['login'])
    factories = d.connections(config, approval, secret_provider)
    d.readiness(config, approval, factories)  # Only this role; never asks for another secret.
    settings = polling.PollSettings(**doc['polling'])
    process_id = str(uuid4())
    w = doc['worker']
    worker_settings = worker.WorkerSettings(process_id, channels.ChannelAuthority(**doc['authority']),
        timedelta(seconds=w['lease_seconds']), timedelta(seconds=w['retry_seconds']), w['max_retries'],
        timedelta(seconds=w['statement_timeout_seconds']))
    connect = factories[service]
    backend = polling.DatabaseBackend(
        discover_connect=connect if service == 'discovery' else forbidden_connection,
        execute_connect=connect if service == 'execution' else forbidden_connection,
        worker_settings=worker_settings, settings=settings, stop=stop)
    if service == 'health':
        return HealthRunner(backend, connect, stop, process_id), process_id
    runner = polling.Poller(backend, settings=settings, stop=stop, kinds=doc['work_kinds'],
                            partitions=[polling.Partition(**p) for p in doc['partitions']])
    return runner, process_id
