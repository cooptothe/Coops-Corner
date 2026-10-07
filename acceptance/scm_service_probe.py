"""Staged acceptance-only fault injection around the real execution entry point.

No secret injection or alternate credential provider: SCM's actual account must
read its own Credential Manager entry and pass normal runtime readiness.
"""
import json
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    from corner.services.execution import main as entry
    if sys.argv[1] == 'stop':
        # WinSW 2.12.0 starts the stop helper WITHOUT its normal log handler.
        # Retain helper output explicitly; still use the real DB-independent CLI.
        from corner import host_entry
        original_emit = host_entry.emit
        started = time.monotonic()
        def stop_emit(value):
            value = dict(value, helper_elapsed_seconds=time.monotonic() - started)
            with (Path(__file__).parent.parent / 'logs/stop-results.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(value) + '\n')
            original_emit(value)
        with patch.object(host_entry, 'emit', side_effect=stop_emit):
            return entry(sys.argv[1:])
    from corner import host_service, versioned_dispatch
    from corner.host_entry import emit
    mode = json.loads((Path(__file__).parent / 'mode.json').read_text())['mode']
    if mode not in ('normal', 'drain', 'hang_transaction', 'hang_prepared', 'stop_prepared'):
        raise ValueError('unsupported acceptance mode')
    original_build, original_complete = host_service.build, versioned_dispatch.complete
    stop = None

    def build(*args, **kwargs):
        nonlocal stop
        stop = kwargs['stop']
        return original_build(*args, **kwargs)

    def complete(*args, **kwargs):
        if mode == 'stop_prepared':
            emit({'event': 'acceptance_checkpoint', 'mode': mode})
            if not stop.wait(30): raise RuntimeError('acceptance stop did not arrive')
            # Acceptance-only checkpoint. Unwind the real transaction/context
            # managers without completing or reclassifying the frozen command.
            raise SystemExit(0)
        if mode == 'hang_prepared':
            emit({'event': 'acceptance_checkpoint', 'mode': mode})
            threading.Event().wait(120)
            raise RuntimeError('acceptance checkpoint timed out')
        result = original_complete(*args, **kwargs)
        if mode != 'normal':
            emit({'event': 'acceptance_checkpoint', 'mode': mode})
            if mode == 'hang_transaction':
                threading.Event().wait(120)
                raise RuntimeError('acceptance checkpoint timed out')
            if not stop.wait(30):
                raise RuntimeError('acceptance stop did not arrive')
        return result

    with patch.object(host_service, 'build', side_effect=build), patch.object(
            versioned_dispatch, 'complete', side_effect=complete):
        return entry(sys.argv[1:])


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        print('{"event":"acceptance_probe_error"}', flush=True)
        raise SystemExit(2)
