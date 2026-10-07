"""Opt-in, single-threaded scheduling of existing versioned adapters.

No database connection, thread, signal handler or loop is started on import.
Sources must themselves bound external I/O; Python cannot safely interrupt an
arbitrary capture callback. A service supervisor remains the hard process bound.
"""
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
import math
import random
import threading
import time

from corner import versioned_dispatch as dispatch, versioned_reconciliation as reconciliation
from corner import work, worker


KINDS = ('apply_lifecycle', 'qualify', 'ensure_occurrence', 'evaluate', 'assess')
DISCOVERY = ('activation', 'qualification', 'occurrence')
COUNTERS = ('discovered', 'claimed', 'completed', 'retryable', 'waiting', 'blocked',
            'reclaimed', 'reconciliation_invalid', 'reconciliation_blocked',
            'reconciliation_pending', 'reconciliation_fulfilled', 'pages', 'candidates',
            'lease_lost', 'idle_claims', 'infrastructure_errors', 'stopped')


@dataclass(frozen=True)
class Partition:
    obligation: str
    channel_id: str | None = None

    def __post_init__(self):
        if self.obligation not in DISCOVERY: raise ValueError('unknown obligation')
        if self.channel_id is not None:
            dispatch.ch._uuid(self.channel_id)
            if self.obligation == 'occurrence': raise ValueError('occurrences are not channel scoped')


@dataclass(frozen=True)
class PollSettings:
    page_size: int = 25
    attempts_per_cycle: int = 5
    cycle_seconds: float = 10
    revisit_seconds: float = 5
    idle_initial: float = .25
    idle_cap: float = 5
    error_initial: float = 1
    error_cap: float = 30
    jitter_fraction: float = .1
    shutdown_grace: float = 30
    operation_seconds: float = 30
    lock_timeout_seconds: float = 2
    connect_timeout_seconds: int = 5

    def __post_init__(self):
        for name in ('page_size', 'attempts_per_cycle', 'connect_timeout_seconds'):
            value = getattr(self, name)
            if type(value) is not int or value < 1: raise ValueError(name)
        if self.page_size > 1000: raise ValueError('page_size exceeds sweep limit')
        for name in ('cycle_seconds', 'revisit_seconds', 'idle_initial', 'idle_cap',
                     'error_initial', 'error_cap', 'shutdown_grace', 'operation_seconds', 'lock_timeout_seconds'):
            value = getattr(self, name)
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0: raise ValueError(name)
        if not 0 <= self.jitter_fraction <= 1: raise ValueError('jitter_fraction')
        if self.idle_initial > self.idle_cap or self.error_initial > self.error_cap: raise ValueError('backoff bounds')
        if self.lock_timeout_seconds < .001: raise ValueError('lock timeout must be at least 1ms')


class Stop:
    """Signal handlers may call request(); they must not perform database work."""
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.event = threading.Event()
        self.requested_at = None

    def request(self):
        if self.requested_at is None: self.requested_at = self.clock()
        self.event.set()

    def is_set(self): return self.event.is_set()
    def wait(self, seconds): return self.event.wait(seconds)


class OperationAborted(BaseException):
    """Rollback/leave lease, never translate cancellation into a domain result."""


@dataclass
class Traversal:
    after: str | None = None
    ceiling: str | None = None
    due: float = 0
    errors: int = 0
    passes: int = 0
    last_visit: float | None = None
    last_pass: float | None = None


class Poller:
    """Testable coordinator. Backend methods return only after transaction commit.

    discover(partition, traversal, limit) -> (report, pass_ceiling)
    execute(kind, traversal, claimed_callback) -> (result, next_cursor, ceiling)
    """
    def __init__(self, backend, *, settings=PollSettings(), kinds=KINDS,
                 partitions=None, stop=None, clock=time.monotonic, jitter=random.random):
        self.backend, self.settings, self.clock, self.jitter = backend, settings, clock, jitter
        backend_stop = getattr(backend, 'stop', None)
        self.stop = stop if stop is not None else (backend_stop if backend_stop is not None else Stop(clock))
        if backend_stop is not None and self.stop is not backend_stop:
            raise ValueError('scheduler and backend must share one shutdown signal')
        if getattr(backend, 'settings', settings) != settings:
            raise ValueError('scheduler and backend must share polling settings')
        self.kinds = tuple(kinds)
        self.partitions = tuple(partitions if partitions is not None else (Partition(x) for x in DISCOVERY))
        if (not self.kinds and not self.partitions) or len(set(self.kinds)) != len(self.kinds) or any(k not in KINDS for k in self.kinds):
            raise ValueError('unique supported work kinds required')
        if len(set(self.partitions)) != len(self.partitions): raise ValueError('duplicate discovery partition')
        self.discovery = {p: Traversal() for p in self.partitions}
        self.execution = {k: Traversal() for k in self.kinds}
        self.discovery_position = self.execution_position = self.cycles = self.idle_cycles = 0
        self.totals = Counter({k: 0 for k in COUNTERS})

    def _error(self, state):
        state.errors += 1
        state.due = self.clock() + min(self.settings.error_cap,
            self.settings.error_initial * 2 ** min(state.errors - 1, 30))

    def _advance(self, state, after, ceiling, delay):
        now = self.clock()
        state.after, state.ceiling = after, ceiling if after else None
        state.errors = 0
        state.last_visit = now
        state.due = now + delay
        if after is None:
            state.passes += 1
            state.last_pass = now

    def run_cycle(self):
        started = self.clock()
        counts = Counter({k: 0 for k in COUNTERS})
        inspected = attempts = 0
        # Alternate admission priority, then interleave pages and attempts. A
        # slow but bounded discovery page cannot starve execution across cycles.
        discovery_turn = self.cycles % 2 == 0
        self.cycles += 1
        while not self.stop.is_set() and self.clock() - started < self.settings.cycle_seconds:
            can_discover = inspected < len(self.partitions)
            can_execute = bool(self.kinds) and attempts < self.settings.attempts_per_cycle
            if not (can_discover or can_execute): break
            if can_discover and (discovery_turn or not can_execute):
                partition = self.partitions[self.discovery_position]
                self.discovery_position = (self.discovery_position + 1) % len(self.partitions)
                inspected += 1
                state = self.discovery[partition]
                if state.due <= self.clock():
                    try:
                        report, ceiling = self.backend.discover(partition, state, self.settings.page_size)
                        self._advance(state, report['next_cursor'], ceiling, self.settings.revisit_seconds)
                        counts['pages'] += 1
                        counts['candidates'] += len(report['items'])
                        for source, target in (('newly_requested', 'discovered'), ('invalid', 'reconciliation_invalid'),
                            ('blocked', 'reconciliation_blocked'), ('pending', 'reconciliation_pending'), ('fulfilled', 'reconciliation_fulfilled')):
                            counts[target] += report['counts'][source]
                    except OperationAborted:
                        counts['stopped' if self.stop.is_set() else 'infrastructure_errors'] += 1
                        self._error(state)
                    except Exception:
                        counts['infrastructure_errors'] += 1
                        self._error(state)
            else:
                kind = self.kinds[self.execution_position]
                self.execution_position = (self.execution_position + 1) % len(self.kinds)
                attempts += 1
                state = self.execution[kind]
                if state.due <= self.clock():
                    def claimed(reclaimed):
                        counts['claimed'] += 1
                        counts['reclaimed'] += int(reclaimed)
                    try:
                        result, after, ceiling = self.backend.execute(kind, state, claimed)
                        status = result['status']
                        metric = 'idle_claims' if status == 'idle' else status
                        if status not in ('idle', 'completed', 'retryable', 'waiting', 'blocked', 'lease_lost', 'stopped'):
                            raise ValueError('unknown worker outcome')
                        self._advance(state, after, ceiling, 0)
                        counts[metric] += 1
                    except OperationAborted:
                        counts['stopped' if self.stop.is_set() else 'infrastructure_errors'] += 1
                        self._error(state)
                    except Exception:
                        counts['infrastructure_errors'] += 1
                        self._error(state)
            discovery_turn = not discovery_turn
        self.totals.update(counts)
        productive = bool(counts['claimed'] or counts['discovered'])
        self.idle_cycles = 0 if productive else self.idle_cycles + 1
        base = .001 if productive else min(self.settings.idle_cap,
            self.settings.idle_initial * 2 ** min(self.idle_cycles - 1, 30))
        delay = min(self.settings.idle_cap, base * (1 + self.settings.jitter_fraction * self.jitter()))
        future = [s.due - self.clock() for s in self.discovery.values() if s.due > self.clock()]
        future += [s.due - self.clock() for s in self.execution.values() if s.due > self.clock()]
        if future: delay = min(delay, min(future))
        return {'cycle': self.cycles, 'counts': dict(counts), 'seconds': self.clock() - started,
                'sleep_seconds': 0 if self.stop.is_set() else delay,
                'coverage': {'work_kinds': self.kinds, 'discovery': tuple(p.obligation for p in self.partitions),
                    'deferred': ('market_dependency_reevaluation', 'evaluation_qualification_arrival', 'assessment_deadlines', 'automatic_resume')}}

    def run(self, *, max_cycles, emit=lambda report: None):
        """Finite opt-in loop. Event.wait wakes immediately on shutdown, no DB open."""
        if type(max_cycles) is not int or max_cycles < 1: raise ValueError('finite positive max_cycles required')
        for index in range(max_cycles):
            if self.stop.is_set(): break
            report = self.run_cycle()
            emit(report)
            if index + 1 < max_cycles and self.stop.wait(report['sleep_seconds']): break
        return dict(self.totals)


class _Cursor:
    def __init__(self, cursor, check): self.raw, self.check = cursor, check
    def __getattr__(self, name): return getattr(self.raw, name)
    def __enter__(self): self.raw.__enter__(); return self
    def __exit__(self, *args): return self.raw.__exit__(*args)
    def execute(self, *args, **kwargs): self.check(); return self.raw.execute(*args, **kwargs)
    def executemany(self, *args, **kwargs): self.check(); return self.raw.executemany(*args, **kwargs)


class _Connection:
    def __init__(self, raw, check): self.raw, self.check = raw, check
    def __getattr__(self, name): return getattr(self.raw, name)
    def cursor(self, *args, **kwargs): self.check(); return _Cursor(self.raw.cursor(*args, **kwargs), self.check)
    def commit(self): self.check(); return self.raw.commit()


class DatabaseBackend:
    """Uses NEW authenticated non-owner connections, supplied separately per role.

    Factories accept connect_timeout=seconds and must enforce that bound even
    during authentication. Capture callbacks must have their own I/O deadlines.
    No source or production approval is supplied implicitly.
    """
    def __init__(self, *, discover_connect, execute_connect, worker_settings, settings,
                 stop, source=None, evaluation_validator=None):
        self.discover_connect, self.execute_connect = discover_connect, execute_connect
        self.worker_settings, self.settings, self.stop = worker_settings, settings, stop
        self.source, self.evaluation_validator = source, evaluation_validator
        if worker_settings.statement_timeout.total_seconds() > settings.operation_seconds:
            raise ValueError('statement timeout exceeds operation budget')

    @contextmanager
    def _operation(self, factory):
        deadline = time.monotonic() + self.settings.operation_seconds
        done = threading.Event()
        lock = threading.Lock()
        connections = []

        def expired():
            return time.monotonic() >= deadline or (self.stop.is_set() and
                time.monotonic() >= self.stop.requested_at + self.settings.shutdown_grace)

        def check():
            if expired(): raise OperationAborted()

        def cancel():
            while not done.wait(.02):
                if expired():
                    with lock:
                        for conn in connections:
                            if not conn.closed:
                                try: conn.cancel()
                                except Exception: pass
                    return

        def connect():
            check()
            raw = factory(connect_timeout=self.settings.connect_timeout_seconds)
            with lock: connections.append(raw)
            try:
                check()
                with raw.cursor() as cur:
                    cur.execute("SELECT set_config('lock_timeout',%s,false)",
                                (str(int(self.settings.lock_timeout_seconds * 1000)),))
                raw.commit()
                return _Connection(raw, check)
            except BaseException:
                raw.close()
                raise

        watcher = threading.Thread(target=cancel, name='corner-operation-cancellation', daemon=True)
        watcher.start()
        try: yield connect
        finally:
            done.set()
            watcher.join(timeout=1)
            # Every adapter owns normal close; this also handles abort during
            # connection setup. Never write completion/failure during cleanup.
            for conn in connections:
                if not conn.closed: conn.close()

    def discover(self, partition, state, limit):
        with self._operation(self.discover_connect) as connect:
            with worker._transaction(connect, self.worker_settings) as conn:
                args = dict(obligation=partition.obligation, channel_id=partition.channel_id)
                ceiling = state.ceiling or reconciliation.pass_ceiling(conn, **args)
                if ceiling is None:
                    report = {'counts': dict.fromkeys(('fulfilled', 'pending', 'blocked', 'newly_requested', 'invalid'), 0),
                              'items': [], 'next_cursor': None}
                else:
                    report = reconciliation.sweep(conn, **args, after=state.after, through=ceiling, limit=limit)
            return report, ceiling

    def execute(self, kind, state, claimed):
        # Bounded finite traversal within each kind also gives old/new versions
        # claim opportunities without interpreting their semantic identities.
        with self._operation(self.execute_connect) as connect:
            with worker._transaction(connect, self.worker_settings, read_only=True) as conn:
                with conn.cursor() as cur:
                    query = '''SELECT work_request_id FROM corner.work_executions WHERE work_kind=%s
                        AND ((status IN ('ready','retryable') AND available_at<=clock_timestamp())
                          OR (status='leased' AND lease_expires_at<=clock_timestamp()))'''
                    ceiling = state.ceiling
                    if ceiling is None:
                        cur.execute(query + ' ORDER BY work_request_id DESC LIMIT 1', (kind,))
                        row = cur.fetchone()
                        ceiling = str(row[0]) if row else None
                    if ceiling is None: return {'status': 'idle'}, None, None
                    cur.execute(query + ''' AND (%s::uuid IS NULL OR work_request_id>%s::uuid)
                        AND work_request_id<=%s::uuid ORDER BY work_request_id LIMIT 2''',
                        (kind, state.after, state.after, ceiling))
                    rows = cur.fetchall()
            if not rows: return {'status': 'idle'}, None, None
            identity = str(rows[0][0])
            result = dispatch.run_once(connect, settings=self.worker_settings, request_id=identity,
                source=self.source, evaluation_validator=self.evaluation_validator,
                should_stop=self.stop.is_set, claim_observer=claimed)
            return result, identity if len(rows) > 1 else None, ceiling
