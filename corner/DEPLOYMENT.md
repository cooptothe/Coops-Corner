# Deployment Decision 1 — locked service contract

Status: contract locked; acceptance-stage configuration/readiness and a separate
disposable harness are implemented. No persistent service runner is registered.
No permanent LOGIN roles, credentials, migrations or production approvals are
created by this document. The application baseline is 507 tests. See
[dedicated deployment acceptance](../acceptance/README.md) for separately reported
database, portable process and unproven host/supervisor boundaries.

Starting coordination must not grant production-positive authorization.

## First deployment boundary

The first runner targets an explicitly approved, isolated **non-production
database**, containing synthetic fixtures or deliberately imported historical
evidence. It must not connect to a mixed production/synthetic work queue.
The database target, environment identity and enabled routes are deployment
configuration, not values inferred from whichever connection happens to succeed.

Require `production_positive_authorization = false`. In this first runner,
`true`, a missing mode, a production target or an unapproved target is a startup
error, not an opt-in shortcut. No production-positive evidence loader is installed.
An approved synthetic catalog must be explicitly supplied for fresh v2 capture;
absence of that catalog remains a prerequisite failure under existing adapters.

This isolation is necessary: the existing worker profile can append applications
and transitions. Its permissions do not distinguish synthetic episode openings
from production episode openings. A flag, queue label or channel filter alone is
not a database security boundary. In particular, occurrence discovery is global,
and current execution traversal is partitioned by kind, not environment/channel.

Historical frozen work still executes through its pinned implementation. Do not
rewrite its command, upgrade its version, recheck historical approval against
today's state, or alter reducer semantics to implement a deployment mode.
Synthetic/historical episodes may be reproduced inside the isolated environment;
they are not published as production-authorized opportunities.

Production promotion is a separate reviewed deployment revision requiring real
approved phase/settlement paths, a tested authorization/admission boundary and
current assessment/lifecycle compatibility. Setting a Boolean is insufficient.
No alert delivery or member-facing publication is enabled in this deployment.

## Service identities

Proposed LOGIN names below are examples scoped to an environment; they do not yet
exist. Each receives only its listed direct NOLOGIN membership, without ADMIN
OPTION. Effective inherited privileges must also be checked.

| Connection identity | Direct membership | Purpose |
| --- | --- | --- |
| `corner_<env>_discovery_login` | `corner_work_producer` | Read evidence and create/recover work requests |
| `corner_<env>_execution_login` | `corner_worker` | Claim, prepare and execute supported work |
| `corner_<env>_health_login` | `corner_reader` | Read-only health snapshots |

The worker already inherits analysis, work-producer and reader access. Do not
grant those again as independent deployment privileges. Separate connection
factories help avoid accidental authority use; credentials in one process do not
isolate one component from a compromised process. Health export can be hosted
separately with reader credentials only.

The remaining profiles are not service memberships in this slice:

- `ingest`: reserved for a separately deployed ingestion identity.
- `analysis`: inherited by the worker; no additional LOGIN identity required here.
- `channel_admin`, `disposition`, `recovery`, `work_admin`: explicit administrative
  identities/workflows, never automatic worker privilege escalation.

All service logins must be non-owner, non-superuser, and lack database/role
creation, replication and RLS-bypass authority. They must not inherit migration
ownership or administrative profiles, including indirectly. Check PUBLIC/direct
grants and role-switch privileges as well as declared membership.
An OS service identity is separate from a database login. Its filesystem access
is limited to the installed build, nonsecret configuration and approved secret
access; it must not obtain migration-owner credentials.

## Credentials and rotation

Load credentials from an explicitly configured OS/deployment secret provider.
Configuration contains secret references, never passwords. Do not import the
legacy `config.DB_CONFIG`, fall back to an owner connection, accept credentials
in command-line arguments, or log full connection strings/configuration dumps.
Remote database transport must use verified encryption/identity settings defined
by the deployment; no automatic downgrade on failure.

A new short-lived connection resolves the selected credential revision at a
transaction boundary. Rotation does not rewrite WorkRequests, authority IDs,
prepared commands or lease tokens. Existing bounded transactions finish normally;
subsequent connections use the new credential. Authentication failure is an
operational error with bounded backoff, never a reason to retry as an owner.
Test rotation and revocation before persistent operation.

Keep three identities distinct:

- Stable authenticated domain authority: attribution and idempotency scope.
- Unique worker/process-instance identity: lease owner and telemetry reset scope.
- Credential revision: authentication material, not a new domain authority.

## Versioned startup configuration

Use a validated, nonsecret configuration document with an explicit format version.
Reject unknown keys, missing required values and incompatible combinations.
Log its redacted digest, deployment/build identity and enabled coverage. No hot
reload in v1: changed operational configuration requires a controlled restart.

Require explicit database/environment targets, secret references, authenticated
authority, installed handler manifest, enabled work kinds, discovery partitions,
worker settings, poll settings, health limits and reporting interval.
Never load domain freshness/qualification rules from this service configuration;
those remain in immutable generations and commands.

Initial **controlled-test** profile, not a production throughput/SLO promise:

| Setting | Value |
| --- | --- |
| Work kinds | apply_lifecycle, qualify, ensure_occurrence, evaluate, assess |
| Discovery | activation and qualification with explicit channel partitions; global occurrence |
| Concurrency | 1 in-flight work attempt per process |
| Candidates / partition visit | 25 / one page |
| Attempts / cycle; admission budget | 5; 10 seconds |
| Revisit interval | 5 seconds |
| Idle backoff | 0.25 to 5 seconds, jitter fraction 0.1 |
| Infrastructure backoff | 1 to 30 seconds |
| Connection / lock / statement timeout | 5 / 2 / 5 seconds |
| Whole operation budget | 30 seconds |
| Lease duration | 90 seconds; no added heartbeat loop |
| Work retry delay / max retries | 5 seconds / 3, through existing worker policy |
| Shutdown grace | 30 seconds |
| Health | 5-minute completion window; existing explicit HealthLimits |
| First launch | foreground, bounded, 100 cycles |

Validate timeout relationships, including an operation budget below lease duration
with margin. Supervisor hard-stop allowance must exceed drain grace plus bounded
connection/cancellation cleanup. Capture callbacks must bound external I/O;
Python cannot safely interrupt arbitrary callback code. Never claim that a SQL
statement timeout bounds a whole capture or health replay.

Keep unsupported coverage explicit: assessment deadline discovery, market
dependency reevaluation, evaluation/qualification arrival discovery and automatic
waiting/blocked resumption are not supplied by this runner.

## Startup readiness

Before the first discovery pass or claim, perform read-only checks:

1. Validate configuration, isolated target and disabled production-positive mode.
2. Authenticate each connection identity; verify actual session role, effective
   privileges, ownership exclusions and read/write boundaries.
3. Verify PostgreSQL 18 and the required canonical schema through Migration 013.
   Check a versioned catalog contract covering required columns, constraints,
   indexes, immutability triggers and grants; filenames alone are not migration
   application proof. Startup never applies migrations or provisions roles.
4. Verify the exact installed format/revision manifest against the immutable build
   and configured generation routes. Missing required handlers prevent readiness.
   Unsupported individual queued commands remain blocked by existing dispatch;
   their presence does not justify a default-to-v1/latest fallback.
5. Verify explicitly configured evidence loaders/catalogs are admissible for the
   non-production mode. Missing capture authority cannot become positive authority.
6. Perform a reader health check within configured limits; failure is unknown/error,
   not a zero-valued ready snapshot. Report known coverage gaps and initial backlog.

Blocked work or lag is not itself proof that the process cannot start safely.
Distinguish startup safety/readiness, process liveness, and operational/domain
health. Never restart continuously merely because an existing request is blocked.

## Supervision and shutdown

First prove the foreground bounded runner under actual non-owner credentials.
Only then register a persistent service through an explicitly approved host
supervisor. The deployment must pin executable/build path, working directory,
OS identity, configuration path, secret access, stop mechanism and restart policy.
The subsequent [Windows host decision](WINDOWS_HOST.md) selects WinSW 2.12.0,
dedicated local accounts and per-service Credential Manager entries. Host
adapters and acceptance remain separate; no automatic-start registration or
persistent service installation is authorized by this contract.

Persistent mode, when implemented, may invoke finite poller runs repeatedly using
the **same** Poller instance and stop signal. It does not introduce another queue
or domain scheduler. Bounded-mode completion exits successfully and is not a crash;
normal stop does not trigger restart. Unexpected failures use capped restart
backoff and a restart-rate limit; invalid configuration/permissions/build state
requires intervention instead of a restart storm.

The stop handler calls only `Stop.request()`. Stop new claims/captures, wake idle
sleep, and drain already-started bounded work. Preserve atomic domain completion
under its row fence. At grace expiry cancel/roll back where supported; a supervisor
provides the final process bound. Never fabricate completion, clear another
worker's lease, or regenerate preparation during shutdown. Restart recovers from
the existing completion/preparation/lease state and eventually revisits partitions.

## Telemetry export

Export current database health and ephemeral process telemetry as separate
records, with schema/build/environment and sampling identity. Each process start
gets a fresh instance ID. Counters reset visibly; monotonic partition ages do not
become invented system-wide UTC scan timestamps. Scrape errors are errors, not
replacement zero gauges. Preserve coverage metadata in every export.

Use bounded export queues/timeouts so an unavailable collector cannot hold a
database transaction or block lease completion. Dropped telemetry is reported
locally and does not alter domain results. Do not log secrets, lease tokens, raw
payloads, complete approval documents or unredacted exception connection strings.
Retained incidents, historical trends and SLOs require a separately chosen retained
telemetry destination; none is implied by exporting current snapshots.

## Proof required before service registration

- Real non-owner LOGIN authentication, effective permission checks and denied
  owner/admin/mutation paths; missing secret or wrong target fails before work.
- Configuration/build/schema failures admit no work; disabled mode rejects
  production targets and positive-authority enablement, including attempted bypass.
- Required installed handlers route exactly; unsupported frozen work blocks.
- Credential rotation preserves in-flight command identity and future connectivity.
- Stop during idle, capture, preparation and atomic completion drains or leaves
  reclaimable state; forced death/restart reuses committed preparation.
- Process restart visibly resets runtime telemetry, not database health/history.
- Collector failure cannot stall domain transactions or turn health errors green.

These are deployment acceptance tests to implement, not assertions that the
current library suite already proves OS supervision, credential rotation or
production isolation. Approval of this contract does not authorize creating
logins, importing live evidence, starting a service or enabling production output.
