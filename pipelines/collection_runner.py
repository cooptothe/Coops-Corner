"""Continuous collection control plane; no live transport is enabled by this CLI.

The injectable Runner is shared by offline rehearsal and future reviewed live
wiring. One request at a time bounds concurrency and preserves SQLite ownership.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import time

from corner.collection_policy import aware, open_now, parse, plan
from corner.credit_governor import Governor, Refused
from corner.featured_markets import FeaturedMarketError
from pipelines.collection_worker import fixture_transport


class Runner:
    def __init__(self, governor, discover, transport, *, clock=None, publisher=None,
                 owner=None, max_jobs=4, should_stop=None, additional=False, job_filter=None, live_jobs=None):
        if not 1 <= max_jobs <= 20:
            raise ValueError('max_jobs must be between 1 and 20')
        self.live_jobs = live_jobs
        self.job_filter = job_filter or (lambda job: True)
        self.additional = additional
        self.g = governor
        self.discover = discover
        self.transport = transport
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.publisher = publisher
        self.owner = owner or secrets.token_hex(16)
        self.max_jobs = max_jobs
        self.should_stop = should_stop or (lambda: False)
        self.g.db.executescript('''
          CREATE TABLE IF NOT EXISTS publication_failures (
            token TEXT PRIMARY KEY, failures INTEGER NOT NULL, retry_at REAL NOT NULL,
            quarantined INTEGER NOT NULL DEFAULT 0, error_type TEXT, sqlstate TEXT);
          CREATE TABLE IF NOT EXISTS runner_inventory (
            id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT, captured REAL,
            retry_at REAL NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0,
            cursor TEXT NOT NULL DEFAULT '');
          INSERT OR IGNORE INTO runner_inventory(id) VALUES(1);
        ''')

    def now(self):
        return aware(self.clock())

    def pause(self, reason):
        with self.g.transaction() as db:
            self.g._fence(db, self.owner, self.now().timestamp())
            db.execute('UPDATE controls SET paused=? WHERE id=1', (reason,))

    def tick(self):
        if self.should_stop():
            return {'state': 'stopping', 'executed': 0}
        now = self.now()
        if not self.g.acquire(self.owner, now):
            return {'state': 'another_worker', 'executed': 0}
        if self.g.status()['unknown_attempts']:
            self.pause('Uncertain collection request; operator review required')
        # Publication retries buy no odds. A failing writer stops new purchases.
        published = 0
        if self.publisher:
            row = None
            try:
                # One outbox item per tick bounds writer work and refreshes clocks.
                row = self.g.db.execute('SELECT token,payload FROM publication_outbox '
                                        'WHERE published_at IS NULL AND token NOT IN (SELECT token FROM publication_failures WHERE quarantined=1) ORDER BY rowid LIMIT 1').fetchone()
                if row:
                    failure = self.g.db.execute('SELECT retry_at FROM publication_failures WHERE token=?', (row['token'],)).fetchone()
                    if failure and failure[0] > self.now().timestamp():
                        return {'state': 'publication_backoff', 'executed': 0}
                    self.g._fence(self.g.db, self.owner, self.now().timestamp())
                    self.publisher(row['token'], json.loads(row['payload']))
                    with self.g.transaction() as db:
                        self.g._fence(db, self.owner, self.now().timestamp())
                        db.execute('UPDATE publication_outbox SET published_at=? WHERE token=?',
                                   (self.now().timestamp(), row['token']))
                    published = 1
                if self.g.db.execute('SELECT 1 FROM publication_outbox WHERE published_at IS NULL AND token NOT IN (SELECT token FROM publication_failures WHERE quarantined=1)').fetchone():
                    return {'state': 'publication_pending', 'executed': 0, 'published': published}
            except Exception as error:
                # Only a definitive provider-boundary rejection is isolated.
                # Database/configuration failures still block purchases.
                if row is None:
                    return {'state': 'publication_failed', 'executed': 0,
                            'error_type': type(error).__name__, 'sqlstate': getattr(error,'pgcode',None)}
                quarantined = isinstance(error, FeaturedMarketError)
                with self.g.transaction() as db:
                    self.g._fence(db, self.owner, self.now().timestamp())
                    prior = db.execute('SELECT failures FROM publication_failures WHERE token=?', (row['token'],)).fetchone()
                    failures = (prior[0] if prior else 0) + 1
                    db.execute('INSERT OR REPLACE INTO publication_failures VALUES(?,?,?,?,?,?)',
                               (row['token'], failures, self.now().timestamp()+min(300, 5*2**min(failures-1,6)),
                                int(quarantined), type(error).__name__, getattr(error,'pgcode',None)))
                    if quarantined:
                        record = json.loads(row['payload'])
                        # Do not serve the rejected capture from SQLite either.
                        job = record['job']
                        markets = tuple(job['markets']) + (('h2h_lay',) if job['kind'] == 'main' and job['group'] == 'exchange' else ())
                        for book in job['books']:
                            for market in markets:
                                db.execute('UPDATE snapshots SET expires_at=0 WHERE captured_at=? AND kind=? AND sport=? AND book=? AND market=?',
                                           (parse(record['captured_at']).timestamp(), job['kind'], job['sport'], book, market))
                if quarantined:
                    return {'state': 'publication_quarantined', 'executed': 0,
                            'error_type': type(error).__name__}
                # Class and SQLSTATE are safe diagnostics; never log raw SQL,
                # connection strings, response bodies or exception messages.
                return {'state': 'publication_failed', 'executed': 0,
                        'error_type': type(error).__name__,
                        'sqlstate': getattr(error, 'pgcode', None)}
        if self.g.status()['paused']:
            return {'state': 'paused', 'executed': 0}
        if not open_now(now):
            return {'state': 'after_hours', 'executed': 0}
        row = self.g.db.execute('SELECT * FROM runner_inventory WHERE id=1').fetchone()
        if row['retry_at'] > now.timestamp():
            return {'state': 'discovery_backoff', 'executed': 0}
        if row['captured'] is None or now.timestamp() - row['captured'] >= 300:
            try:
                inventory = self.discover()
                captured = parse(inventory['discovered_at'])
                current = self.now()
                if not 0 <= (current - captured).total_seconds() <= 60:
                    raise ValueError('Stale inventory')
                plan(current, inventory['active_sport_keys'], inventory['events'], additional=self.additional)
                with self.g.transaction() as db:
                    self.g._fence(db, self.owner, current.timestamp())
                    db.execute('UPDATE runner_inventory SET payload=?,captured=?,failures=0,retry_at=0 WHERE id=1',
                               (json.dumps(inventory), captured.timestamp()))
            except Exception:
                # Never log discovery exceptions: provider errors can contain keys.
                with self.g.transaction() as db:
                    self.g._fence(db, self.owner, self.now().timestamp())
                    failures = row['failures'] + 1
                    db.execute('UPDATE runner_inventory SET failures=?,retry_at=? WHERE id=1',
                               (failures, self.now().timestamp() + min(900, 30 * 2 ** min(failures - 1, 5))))
                return {'state': 'discovery_failed', 'executed': 0}
            row = self.g.db.execute('SELECT * FROM runner_inventory WHERE id=1').fetchone()
        if self.now().timestamp() - row['captured'] > 600:
            return {'state': 'inventory_expired', 'executed': 0}
        inventory = json.loads(row['payload'])
        jobs = sorted((job for job in plan(self.now(), inventory['active_sport_keys'], inventory['events'], additional=self.additional) if self.job_filter(job)), key=lambda j: j.key)
        if self.live_jobs:
            jobs += [job for job in self.live_jobs(self.now(),inventory) if self.job_filter(job)]
            jobs.sort(key=lambda j:j.key)
        # Persist a round-robin cursor so a restart cannot starve later events.
        jobs = [j for j in jobs if j.key > row['cursor']] + [j for j in jobs if j.key <= row['cursor']]
        executed = 0
        for job in jobs:
            now = self.now()
            if self.should_stop() or executed >= self.max_jobs or not open_now(now):
                break
            if not self.g.acquire(self.owner, now):
                break
            with self.g.transaction() as db:
                self.g._fence(db, self.owner, now.timestamp())
                db.execute('UPDATE runner_inventory SET cursor=? WHERE id=1', (job.key,))
            if not self.g.ready(job, now):
                continue
            try:
                self.g.prepare_due(job, self.owner, now)
                token = self.g.claim(job, self.owner, now)
            except Refused:
                continue
            try:
                phase = 'transport'
                status, payload, headers, received = self.transport(self.g, job, token, self.owner)
                current = self.now()
                if abs((current - aware(received)).total_seconds()) > 5:
                    raise ValueError('Invalid receipt clock')
                phase = 'settlement_and_snapshot'
                result = self.g.finish(job, token, self.owner, current, headers, payload, status)
                if result == 'quarantined':
                    executed += 1
                    continue
                if result != 'published':
                    self.pause('Uncertain or rejected collection response; operator review required')
                    break
            except Exception as error:
                try:
                    self.g.unknown(token, self.owner, self.now())
                    self.pause('Uncertain collection request; operator review required')
                    detail = {'phase': phase, 'error_type': type(error).__name__,
                              'job_key': job.key, 'kind': job.kind, 'sport': job.sport, 'token': token}
                    if hasattr(self.g, '_audit'):
                        with self.g.transaction() as db:
                            self.g._audit(db, self.now(), 'request-failed', 'Sanitized worker failure', detail)
                    print(json.dumps({'state': 'request_failed', **detail}), flush=True)
                except Refused:
                    # Do not mutate another owner's state. Expiry recovery holds
                    # this attempt as unknown before a successor may buy odds.
                    return {'state': 'lease_lost', 'executed': executed}
                break
            executed += 1
        return {'state': 'ready', 'executed': executed, 'published': published}


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True)
    parser.add_argument('--manifest')
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    path = Path(args.state)
    if 'simulation' not in path.name.lower():
        parser.error('Only a separate simulation state file is supported in this release')
    if args.status and not path.is_file():
        parser.error('State file does not exist')
    g = Governor(path)
    runner = None
    try:
        if args.status:
            print(json.dumps(g.status(), sort_keys=True))
            return
        if not args.manifest:
            parser.error('--manifest is required for rehearsal')
        manifest = json.loads(Path(args.manifest).read_text(encoding='utf-8'))
        if manifest.get('format') != 'corner.collection_simulation/1':
            parser.error('Explicit simulation manifest required')
        g.configure_cycle('simulation-' + manifest['cycle_id'], parse(manifest['cycle_start']), parse(manifest['cycle_end']))
        def discover():
            return {**manifest, 'discovered_at': datetime.now(timezone.utc).isoformat()}
        fixture = fixture_transport(manifest)
        def transport(governor, job, token, owner):
            now = datetime.now(timezone.utc)
            return (*fixture(job, now), now)
        runner = Runner(g, discover, transport)
        while True:
            print(json.dumps({**runner.tick(), 'mode': 'simulation', 'provider_calls': 0,
                              'feed_publication': False}, sort_keys=True), flush=True)
            if args.once:
                break
            time.sleep(5)
    except KeyboardInterrupt:
        pass
    finally:
        if runner:
            g.release(runner.owner)
        g.close()


if __name__ == '__main__':
    main()
