"""Test-only child process, NOT a deployable service or supervisor.

Fault checkpoints are deliberately confined to this harness. Secrets arrive in
the child environment, never argv, configuration files or emitted reports.
"""
import json
from pathlib import Path
import signal
import sys
import threading
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from corner import deployment as d, health, polling, versioned_dispatch as dispatch


def emit(event, **fields):
    print(json.dumps({'event': event, **fields}, default=str), flush=True)


def main():
    config = d.Configuration.parse(Path(sys.argv[1]).read_text())
    approval = d.TargetApproval(Path(sys.argv[2]).read_text())
    mode = sys.argv[3]
    if mode not in ('bounded', 'drain', 'crash_prepared', 'idle'):
        raise d.ReadinessError('unknown probe mode')
    stop = polling.Stop()
    signal.signal(signal.SIGTERM, lambda *_: stop.request())
    signal.signal(signal.SIGINT, lambda *_: stop.request())

    def control():
        for line in sys.stdin:
            if line.strip() == 'stop': stop.request()
    threading.Thread(target=control, daemon=True).start()
    poller, instance = d.build_poller(config, approval, stop=stop)
    emit('ready', process_instance_id=instance,
         telemetry=health.process_telemetry(poller, process_instance_id=instance).__dict__)
    original = dispatch.complete

    def checkpoint(conn, **kwargs):
        if mode == 'crash_prepared':
            emit('prepared')
            if not stop.wait(30): raise RuntimeError('probe checkpoint timeout')
            raise polling.OperationAborted()
        result = original(conn, **kwargs)
        if mode == 'drain':
            emit('completion_uncommitted')
            if not stop.wait(10): raise RuntimeError('probe checkpoint timeout')
        return result

    with patch.object(dispatch, 'complete', checkpoint):
        totals = poller.run(max_cycles=config.value['max_cycles'], emit=lambda report: emit('cycle', report=report))
    emit('done', process_instance_id=instance, totals=totals)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Only a category is exported. No exception/DSN/secret serialization.
        emit('startup_or_process_error', category=type(error).__name__)
        sys.exit(2)
