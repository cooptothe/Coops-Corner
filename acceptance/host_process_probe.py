"""Test-only failure checkpoints; real fixed-role adapter + native stop IPC.

Passwords injected by disposable fixture only; never a deployed service entry.
"""
import json
import os
from pathlib import Path
import sys
import threading
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from corner import deployment as d, host_service, windows_shutdown, polling, versioned_dispatch
from corner.host_entry import emit


def main():
    config = d.Configuration.parse(Path(sys.argv[1]).read_text(), service='execution')
    approval = d.TargetApproval(Path(sys.argv[2]).read_text())
    mode = sys.argv[3]
    if mode not in ('drain', 'force_transaction', 'bounded'): raise ValueError('unknown test mode')
    stop = polling.Stop()
    with windows_shutdown.ServiceInstance('execution', json.loads(approval.document)['windows_sids']['execution'], stop,
                                         Path(sys.argv[1]).parent / 'instance.json'):
        runner, process_id = host_service.build('execution', config, approval, stop=stop,
                                              secret_provider=lambda _: os.environ['CORNER_HOST_TEST_PASSWORD'])
        complete = versioned_dispatch.complete
        def drain(*args, **kwargs):
            result = complete(*args, **kwargs)
            emit({'event': 'completion_uncommitted'})
            if mode == 'force_transaction':
                threading.Event().wait(30)  # Deliberately ignore stop; test helper must force this process.
                raise RuntimeError('force checkpoint timed out')
            if not stop.wait(10): raise RuntimeError('test stop never arrived')
            return result
        emit({'event': 'ready', 'process_instance_id': process_id})
        with patch.object(versioned_dispatch, 'complete', side_effect=drain if mode != 'bounded' else complete):
            totals = runner.run(max_cycles=config.value['max_cycles'], emit=emit)
        emit({'event': 'done', 'totals': totals})
    return 0


if __name__ == '__main__':
    try: raise SystemExit(main())
    except Exception:
        emit({'event': 'probe_error'})
        raise SystemExit(2)
