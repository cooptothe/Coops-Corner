# Host Integration Decision 3 — fixed roles and local stop bridge

Implemented adapters only. No installed service, new account, credential write,
rotation, production authority or domain changes. Runs remain explicitly finite
through `max_cycles`; persistent supervision is gated on host acceptance.

## Fixed entry points

| Module | Responsibility | Only credential target |
| --- | --- | --- |
| `corner.services.discovery` | Reconciliation pages only | `Corner/Postgres/Discovery` |
| `corner.services.execution` | Claim/prepare/execute only | `Corner/Postgres/Execution` |
| `corner.services.health` | Read-only health JSON export | `Corner/Postgres/Health` |

The module fixes the role. There is no `--role` option. Each accepts:

```text
python -m corner.services.execution run --config <nonsecret.json> --approval <trusted-target.json> --runtime-record <absolute-instance.json>
python -m corner.services.execution stop --expected-sid <service-account-SID> --runtime-record <absolute-instance.json> --graceful-drain-timeout 45 --hard-stop-verification-timeout 5
```

Use the matching discovery/health module for those services. Absolute interpreter,
configuration/approval paths and a pinned working directory remain installation
requirements, not values learned from PATH at service startup.

`corner.host-service/1` reuses the explicit bounds/database/authority fields of
`corner.deployment.acceptance/1`, but `identities` has **exactly one** entry named
for the module. Its `secret_ref` must match the table. Discovery requires nonempty
`partitions` and empty `work_kinds`; execution requires nonempty `work_kinds` and
empty `partitions`; health requires both empty. All retain explicit worker/poll
bounds, finite `max_cycles`, isolated-nonproduction target and disabled positive
production authorization. Unknown fields, including a role flag, are rejected.

The trusted target approval additionally supplies `windows_sids` by service.
Startup verifies the actual Windows SID, then the one authenticated database
session's effective identity, memberships, privileges, schema and handler pins.
Other services' logins can appear in the **nonsecret approval**, but no other
credential factory is created or secret retrieved. The old combined runner
rejects host configurations; host connections reject its environment-secret
default. Library dependency injection is for tests, not a CLI fallback.

The native vault reader uses exact-target `CredReadW`, generic credentials,
`CRED_PERSIST_LOCAL_MACHINE`, approved PostgreSQL username and strictly decoded
UTF-16LE password bytes without a NUL terminator. It never writes/enumerates the
vault. Actual service-logon vault access remains a host acceptance requirement.
That persistence constant applies across local sessions **of the same user**, not
machine-scope DPAPI. [Microsoft credential contract](https://learn.microsoft.com/en-us/windows/win32/api/wincred/ns-wincred-credentialw).

## Local stop protocol (Decision 3 foundation)

Decision 4 now layers a restricted runtime identity, exact-instance event and
grace-then-force controller over this event foundation. The `stop` CLI uses that
controller, not the old signal-only function. See
[bounded Windows stop](BOUNDED_WINDOWS_STOP.md) for the current contract.

The running process creates a manual-reset, initially nonsignaled Windows event
before database readiness. Its name is:

```text
Global\Corner.<fixed-service>.<approved-Windows-SID>.Stop
```

The protected DACL allows only that account and LocalSystem. Handles are not
inheritable. A listener calls only the existing `Stop.request()`; it does not
connect to PostgreSQL or modify leases/commands. Native listener failure requests
drain and produces a failed process exit, not continued unattended execution.

The matching stop helper verifies its Windows identity, opens the event with only
`EVENT_MODIFY_STATE`, signals it and closes its handle. It imports no database
driver/runtime, loads no service configuration or credentials, and needs no stdin.
An absent event is an idempotent `not_running` result; access denial is failure.
The helper reports a **stop request**, not proof that draining has completed.

Startup refuses an already-existing event rather than opening/resetting it.
Consequently an old helper retaining a signaled handle prevents a new instance
from starting; it cannot pass a latched stop flag into that instance. Once all
handles close, restart creates a fresh nonsignaled object. Duplicate signals to
one live instance are harmless. There is no persistent stop file to clear.
Windows destroys the object after its last handle closes, and ignores the new
initial-state/ACL arguments when opening an existing event; this is why reset-on-
startup would be unsafe. [Microsoft CreateEventW](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-createeventw).

This is lifecycle-bound signaling, not a secret token. Another process under the
same account is inside the trust boundary; object precreation can cause a safe
startup denial. A stale helper that keeps a handle must exit before restart.
Actual cross-account access denial and service-session operation remain host
acceptance work; the local suite inspects the native DACL under the current user.

Discovery-only operation uses the existing Poller with no execution kinds;
execution-only operation has no discovery partitions. The opposite connection
path raises rather than borrowing credentials. Health exports through the existing
read-only health API and bounded connection/cancellation wrapper. All use the same
stop signal and existing operation/drain deadlines. No current-evidence recapture,
domain interpretation or lease release is added during shutdown.

## WinSW 2.12.0 timeout limitation

Inspection of the **pinned version's source**, rather than the v3 documentation,
found a material distinction: `DoStop()` passes `StopTimeout` to `StopProcessTree`
only when `StopArguments` is absent. With custom stop arguments it starts the
helper and calls `WaitForProcessToExit` for both processes; that loop has no
overall timeout. [WinSW 2.12.0 WrapperService.cs](https://github.com/winsw/winsw/blob/v2.12.0/src/WinSW/WrapperService.cs).

Therefore wiring these helpers into `<stoparguments>` does **not** establish that
`<stoptimeout>` will forcibly terminate a hung child. Do not register a persistent
service or claim the hung-process host test passes on that assumption. Decision 4
adds application-owned bounded termination without changing supervisor version;
the actual installed-host timeout and SCM tests still remain unperformed.

## Local proof vs. host proof

Verified on Windows, 2026-09-30: **22/22 local adapter tests passed**, plus the
**12/12 Decision 4 bounded-stop tests**. Separately
rerun: **507/507 application regression**, **14/14 deployment DB acceptance**,
and **8 portable process/config tests passed with 1 Windows SIGTERM skip**.
No installed-host acceptance result is implied by any of these counts.

Run separately from application regression:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:CORNER_DEPLOYMENT_ACCEPTANCE='1'
python -m unittest discover -s acceptance -p 'test_host_adapt*.py' -v
```

The local suite tests fixed-role configuration/factories, swapped real database
identities, native IPC without stdin/database dependency, duplicate stops, fresh
restart, retained-handle rejection, native DACL contents and actual completion
drain with no subsequent claim. A test-only child receives one disposable password
through its environment; the deployed entry points have no such option. Vault
decoding tests substitute an entry and do not create/read real service secrets.

These tests do not install WinSW, create Windows accounts, verify service-logon
Credential Manager availability, prove cross-account IPC denial, rotate credentials
or demonstrate wrapper termination/recovery. Keep those results unperformed until
the real host matrix is explicitly authorized and run.
