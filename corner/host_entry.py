"""CLI shared plumbing; role is a literal in each module, never an argument.

Stop mode deliberately imports neither PostgreSQL nor domain/runtime modules.
"""
import argparse
from datetime import date, datetime
import json
from pathlib import Path

from corner import windows_control, windows_shutdown


def json_value(value):
    if isinstance(value, (datetime, date)): return value.isoformat()
    raise TypeError('unsupported telemetry value')


def emit(value):
    print(json.dumps(value, default=json_value, allow_nan=False), flush=True)


def main(service, argv=None):
    parser = argparse.ArgumentParser(prog='corner-' + service)
    commands = parser.add_subparsers(dest='command', required=True)
    run = commands.add_parser('run')
    run.add_argument('--config', required=True)
    run.add_argument('--approval', required=True)
    run.add_argument('--runtime-record', required=True)
    stop_parser = commands.add_parser('stop')
    stop_parser.add_argument('--expected-sid', required=True)
    stop_parser.add_argument('--runtime-record', required=True)
    stop_parser.add_argument('--graceful-drain-timeout', type=float, required=True)
    stop_parser.add_argument('--hard-stop-verification-timeout', type=float, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'stop':
            result = windows_shutdown.stop_instance(service, args.expected_sid, args.runtime_record,
                graceful_drain_timeout=args.graceful_drain_timeout,
                hard_stop_verification_timeout=args.hard_stop_verification_timeout)
            emit({'event': result, 'service': service})
            return 0
        # Local stop listener comes up BEFORE readiness/connecting to PostgreSQL.
        from corner import deployment as d, polling, host_service, health
        config = d.Configuration.parse(Path(args.config).read_text(encoding='utf-8'), service=service)
        approval = d.TargetApproval(Path(args.approval).read_text(encoding='utf-8'))
        approved = approval.validate(config)
        stop = polling.Stop()
        with windows_shutdown.ServiceInstance(service, approved['windows_sids'][service], stop, args.runtime_record) as endpoint:
            runner, process_id = host_service.build(service, config, approval, stop=stop)
            emit({'event': 'ready', 'service': service, 'process_instance_id': process_id,
                  'mode': 'isolated_nonproduction', 'production_positive_authorization': False})
            def report(value):
                emit(value)
                if isinstance(runner, polling.Poller):
                    from dataclasses import asdict
                    emit({'event': 'telemetry', 'service': service,
                          'runtime': asdict(health.process_telemetry(runner, process_instance_id=process_id))})
            runner.run(max_cycles=config.value['max_cycles'], emit=report)
            if endpoint.failed: raise windows_control.HostControlError('stop listener failed')
            emit({'event': 'stopped', 'service': service, 'process_instance_id': process_id})
        return 0
    except Exception:
        # Never stringify DB/vault exceptions into supervisor logs.
        emit({'event': 'host_adapter_error', 'service': service})
        return 2
