"""Disposable child for local hard-stop proof. No database or service installation."""
from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.modules['psycopg2'] = None  # Prove database-independent startup/control.
from corner import windows_control as control, windows_shutdown as shutdown


class Stop:
    def __init__(self): self.event = threading.Event()
    def request(self): self.event.set()
    def wait(self, seconds): return self.event.wait(seconds)


if __name__ == '__main__':
    stop = Stop()
    with shutdown.ServiceInstance('health', control.current_sid(), stop, sys.argv[1]):
        print('ready', flush=True)
        if not stop.wait(30): raise RuntimeError('test stop did not arrive')
        if sys.argv[2] == 'hung': threading.Event().wait(30)
        elif sys.argv[2] == 'slow': threading.Event().wait(.5)
