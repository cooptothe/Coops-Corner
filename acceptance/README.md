# Deployment Acceptance 1

The concrete next host target is defined in
[Host Deployment Decision 2](../corner/WINDOWS_HOST.md): WinSW 2.12.0 and three
dedicated Windows accounts with separate Credential Manager entries. This
harness is not that installed-host proof; its combined runner and stdin stop
probe must not be represented as the final three-service deployment.

[Host Integration Decision 3](../corner/HOST_INTEGRATION.md) now adds separate
fixed-role entry points and native local stop signaling. Its adapter tests are
reported separately below; the installed WinSW lifecycle remains untested.

This harness is separate from `tests/`. It creates disposable local databases and
temporary password-authenticated LOGIN roles; it does **not** register a service,
provision permanent credentials, change authentication configuration, run against
a production target or approve real market evidence. Existing migration-owner
test credentials are used only by the parent fixture to create/clean up the
disposable environment, never supplied to runtime children.

## Separate results

The 2026-10-01 [installed-service preflight](HOST_ACCEPTANCE_2.md) is blocked:
the actual host token lacks `SC_MANAGER_CREATE_SERVICE` access (Win32 error 5).
No service/account/credential was provisioned and no installed case was exercised.

On Windows, 2026-09-30:

| Proof layer | Result | Scope |
| --- | --- | --- |
| Application regression | 507 passed | Existing suite in `tests/`, run separately |
| Deployment DB acceptance | 14 passed | Actual password logins and effective readiness/permission checks |
| Portable process/config acceptance | 8 passed, 1 skipped | Child startup, injection, cooperative drain, kill/restart and counter reset |
| Local host adapters | 22 passed | Native event IPC/current-user ACL, fixed-role entry points, disposable DB drain and force/rollback/reclaim; not SCM |
| Bounded Windows stop | 12 passed | Exact-instance graceful/forced exit, refusal cases and concurrent helpers against disposable foreground children |
| Host/supervisor acceptance | Not performed | Windows service stop bridge, service registration, supervisor policy, OS identity, secret-store rotation |

The skipped test sends POSIX SIGTERM. Windows process termination is abrupt and
must not be reported as graceful signal handling. The passing Windows drain test
uses an explicit stdin control message to call the same `Stop.request()` hook;
that proves application drain, not an installed Windows service-control bridge.

Run independently (Python must have the existing PostgreSQL dependencies):

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:CORNER_DEPLOYMENT_ACCEPTANCE='1'
python -m unittest discover -s acceptance -p test_deployment_database.py
python -m unittest discover -s acceptance -p test_deployment_process.py
```

Password-authentication acceptance deliberately attempts a wrong password and
requires rejection. A trust-only local authentication rule is **not** a passing
substitute. The harness does not modify `pg_hba.conf` to make this test pass.
Temporary roles have the `corner_login_test_` prefix; databases/profiles use the
existing disposable fixture prefixes. Cleanup targets only those resolved test
identities. Fault-injection grants/trigger changes are restored in `finally`.

## Implemented acceptance-stage APIs

`corner/deployment.py` supplies:

- Strict, nonsecret `Configuration.parse()` with explicit local target, roles,
  secret references, bounds, partitions, authority and finite run count.
- `TargetApproval` supplied by a trusted deployment authority, separately from
  runtime configuration/work. It pins target classification, exact database,
  service logins, domain authority, role profiles, schema/privilege fingerprints
  and installed implementation manifest. Production classification or enablement
  fails before credentials are requested or a connection is attempted.
- Real-login connection factories with no `DB_CONFIG` or owner fallback. The
  environment secret provider is an **acceptance-only injection mechanism**, not
  an implemented production vault or rotation service.
- Read-only readiness over actual `session_user` and `current_user`, transitive
  role memberships and membership options, role attributes, ownership and
  effective privileges. Privilege fingerprints include grant options, columns,
  schemas, database, sequences, and system/user function execution privileges.
  Additional inherited roles fail even when the expected membership is present.
- Actual catalog-definition checks for the approved migration contract, including
  validated constraints and enabled immutability triggers. No startup migration.
- `build_poller()` runs readiness and an initial read-only health check before
  returning an opt-in finite poller. It supplies no implicit evidence catalog.

The trusted expected manifest is built from the freshly migrated release fixture
**before** faults are injected, not by accepting the candidate database's current
state at startup. A real deployment needs a separately reviewed, access-controlled
target approval/release manifest. This harness does not implement signing or a
production approval registry. A caller able to forge the trusted approval input
is outside this boundary; a database name/Boolean alone cannot establish isolation.

The implementation is intentionally loopback-only for this acceptance stage.
Remote transport/identity policy and immutable installation packaging remain host
deployment work. Readiness is a point-in-time proof: privileged administrators
can change grants/schema afterward. It does not certify a hostile administrator
or provide continuous permission-drift surveillance.

## What the database proofs do and do not mean

Discovery can enqueue, but cannot claim/prepare or insert analytical/lifecycle
results. Health can read, but cannot enqueue or mutate. Execution can use existing
adapters and inherits work-producer authority intentionally; it cannot provision
channels, rebuild projections by deletion, change dispositions, mutate/truncate
immutable ledgers, alter schema or manage roles.

The worker's INSERT grants are not an SQL-level proof that a caller used a Python
adapter. Structural constraints and append-only protections remain database
responsibilities; semantic construction remains a trusted versioned-adapter
responsibility. Do not describe these tests as preventing every fabricated direct
INSERT from a compromised worker process.

Readiness tests inject added direct/inherited memberships, extra ordinary grants,
grant options, system-function privileges, removed required grants, a missing
013 constraint, disabled ledger triggers, an owner connection, incompatible
implementation manifest and production classification. Unsupported individual
frozen commands are blocked by dispatch rather than upgraded.

## Child-process proofs

`process_probe.py` is a test-only runner with fault checkpoints, not an installable
service entry point. Configuration/target approval live in temporary files without
passwords. Random credentials are injected into the child environment, not argv or
repo files; emitted output/config files are checked for credential leakage.

- Missing secrets fail startup before any work claim.
- Stop during uncommitted completion drains that transaction and admits no new
  claim. It does not fabricate a failure or clear a lease on shutdown.
- Forced process death after committed preparation leaves a lease; a restarted
  authenticated child reclaims and completes the original prepared command.
  Expiry is advanced by test-fixture SQL to avoid sleeping through the lease;
  this is not a runtime lease-release operation.
- Restart emits a new process ID and zeroed process-local counters, while persisted
  work state and preparation remain authoritative.

Production-positive paths are not installed. Credential rotation, operating-system
secret-store permissions, SIGTERM on a POSIX host, the eventual Windows stop
bridge, supervisor hard deadlines/restart rate limiting, and real telemetry
transport still require environment-specific acceptance. Passing these harnesses
does not authorize persistent-service startup or production promotion.

## Local Windows adapter acceptance

Reverified on 2026-10-01: **22/22 local host-adapter tests** and **12/12 bounded
Windows stop tests** passed. Installed WinSW/SCM acceptance remains unperformed.
The separate application regression also passed **507/507** on this rerun.

Run `python -m unittest discover -s acceptance -p 'test_host_adapt*.py'` with the
same explicit disposable acceptance opt-in. These tests exercise native Windows
events under the **current test user**, not newly provisioned service accounts.
Vault entries are substituted in tests; no actual service credential is stored.
Temporary DB logins/databases are cleaned up by the existing fixture.

Stop-helper tests require neither stdin nor PostgreSQL, and the database test
drains an already-started completion through that helper without claiming the
next item. Restart tests refuse retained old event handles, then prove a fresh
event is nonsignaled. DACL inspection is not a substitute for future cross-user
denial and service-logon testing.

Do not assume the custom helper inherits WinSW's hard timeout: pinned 2.12.0
source waits without an overall deadline when `stoparguments` is configured.
The [Decision 4 controller](../corner/BOUNDED_WINDOWS_STOP.md) now owns bounded
grace/force/verification locally. Installed SCM behavior remains unperformed.

The runtime record is protected and delete-on-close; tests never overwrite it to
retarget a live worker. The force/rollback test uses a new qualified decision,
verifies no occurrence or completion survived the killed transaction, waits for
natural lease expiry and checks exactly one result from the original preparation.
The separate `test_windows_shutdown.py` suite kills only its own probe children.
No Windows account, vault credential or WinSW service is provisioned.

## Installed SCM harness (separate, explicitly opted in)

The next acceptance command and resource/cleanup contract are documented in
[INSTALLED_SCM_ACCEPTANCE.md](INSTALLED_SCM_ACCEPTANCE.md). It installs one disposable
execution service only when an administrator explicitly passes `--execute`.
The local tests above do not install it and do not establish a host-acceptance pass.

The actual lifecycle host result and subsequent successful profile cleanup are
recorded in [HOST_ACCEPTANCE_RESULTS.md](HOST_ACCEPTANCE_RESULTS.md). The next
independent slice is [Credential Rotation/Revocation](CREDENTIAL_ROTATION.md):
same role/authority/frozen command, new secret, and explicit old-session handling.
