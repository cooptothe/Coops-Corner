# Host Deployment Decision 2 — Windows stack

Status: component selection locked; host acceptance **not performed**. This is
not authorization to create accounts, write vault entries, install/start services,
or change PostgreSQL authentication. No domain or orchestration semantics change.

## Supervisor and identity boundary

Use WinSW 2.12.0, x64, from the official tagged release, with an exact binary
SHA-256 pin. Use the **2.12.0 documentation**, not the 3.x XML contract. The
artifact manifest is [winsw-artifact.json](../acceptance/winsw-artifact.json);
an absent or mismatching digest
must block installation/startup. Never resolve "latest" during deployment.

The 2026-09-30 official HTTPS download was 18,243,033 bytes; SHA-256:
`05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da`.
It was hashed, not executed. Authenticode reports `NotSigned`, and the release
API supplies no asset digest. This is an observed exact-byte pin, **not** an
independently verified publisher checksum/signature or installation approval.
Retain this provenance limitation for deployment review.
[Official release](https://github.com/winsw/winsw/releases/tag/v2.12.0).

| Windows service | Local Windows account | Credential Manager target | Direct PostgreSQL membership |
| --- | --- | --- | --- |
| `corner-discovery` | `.\corner-discovery-svc` | `Corner/Postgres/Discovery` | `corner_work_producer` |
| `corner-execution` | `.\corner-execution-svc` | `Corner/Postgres/Execution` | `corner_worker` |
| `corner-health` | `.\corner-health-svc` | `Corner/Postgres/Health` | `corner_reader` |

Separate processes receive only their own database credential. Check actual
Windows token SID against the approved account SID, not just an environment
variable or account-name string. Database readiness still checks actual roles,
effective inherited privileges and the approved isolated non-production target.
Keep `production_positive_authorization=false`; the database boundary supplies
containment, not that flag alone.

Install only through a separately approved administrative workflow. Supply the
Windows account password directly to SCM through a secure provisioning path,
never XML, argv, environment, transcript or repository. Verify the configured
service account before the first start; do not launch under default LocalSystem.
First acceptance uses manual start, not boot-time activation. Pin interpreter,
dependencies, application revision, configuration and working directory as well
as the wrapper. Runtime accounts may read but not replace executable/configuration
artifacts; separate writable, access-controlled log directories are required.

WinSW v2 supports stop and restart configuration, but those features alone do
not prove Corner's drain or recovery behavior. Use a bounded recovery policy
(restart delays, then stop for intervention); never reboot the host. Validate
the effective SCM settings and actual behavior during host acceptance.
[WinSW 2.12.0 XML contract](https://github.com/winsw/winsw/blob/v2.12.0/doc/xmlConfigFile.md).

## Vault contract

Use generic Credential Manager entries under each dedicated account. The
application reads only its configured exact target; no vault enumeration, owner
credential fallback, environment-password fallback or machine-scoped DPAPI.
The entry's PostgreSQL username must match the approved LOGIN identity.
Define one explicit blob encoding in the adapter/provisioner; malformed, absent
or inaccessible credentials fail closed without logging their contents.

Use `CRED_PERSIST_LOCAL_MACHINE` for persistence across this user's subsequent
logon sessions on this computer. Despite its name, this is **not** DPAPI's
machine-wide protection scope. Generic credential blob interpretation belongs to
the application. [Microsoft CREDENTIALW](https://learn.microsoft.com/en-us/windows/win32/api/wincred/ns-wincred-credentialw).

`CredReadW` uses the current token's logon-session credential set. Provisioning
from an interactive session is not proof of service-logon access: verify access
after a real SCM start, stop/start and host restart under the intended identity.
An unavailable credential set is a readiness failure, not permission to copy the
secret into XML. [Microsoft CredReadW](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credreadw).

Account separation is the isolation boundary, not the credential target name.
This does not claim protection from administrators or arbitrary code executing
under the same service account. Credential APIs necessarily expose plaintext to
the authorized process; do not claim Python guarantees secret-memory erasure.

Re-read the vault at new-connection boundaries. Rotation changes authentication,
not domain authority, work identity, preparation or leases. Test old-password
rejection on a **new authenticated connection** separately from existing-session
drain/termination. Do not silently terminate unrelated PostgreSQL sessions.

## Host adapters required before acceptance

Repository inspection identified two concrete gaps, now addressed by the local
[Host Integration Decision 3 adapters](HOST_INTEGRATION.md). Installed-host proof
remains outstanding:

1. `deployment.build_poller()` is a combined acceptance runner. Its configuration,
   connection factory and readiness paths require all three service identities.
   It must not be deployed unchanged under the one-account/one-credential model.
   Role-specific host entry points and readiness scopes now reuse the existing
   finite discovery, execution and read-only health APIs. Do not give each process
   all three vault credentials to satisfy the old harness.
2. `acceptance/process_probe.py` uses stdin for its passing Windows drain test.
   That is not SCM stop integration. The new native event bridge calls
   `Stop.request()` without stdin. For the separate stop helper, authenticate/ACL its
   local IPC and bind it to the exact service instance; it cannot be a world-
   writable stop file or an unauthenticated global control endpoint.

No secret provider or stop bridge may modify frozen commands or introduce a
second worker/reducer. Existing portable acceptance remains independent and
does not become host acceptance merely by renaming its tests.

## Host Acceptance 1 — required executable cases

Run only after explicit provisioning approval, against the isolated database.
Use dedicated acceptance identities/services and exact-target cleanup. Retain
redacted evidence even on failure; missing prerequisites are **not exercised**,
never a passing substitute.

| Case | Required proof |
| --- | --- |
| Artifact/startup | Pinned binary/build hashes; actual OS SID and service configuration; catalog/privilege readiness; production target rejected before work |
| Vault separation | Each actual service logon reads its own fixture secret; other accounts' entries unavailable; no environment/XML fallback |
| Graceful stop | Real WinSW/SCM stop while idle, capturing, prepared and completing; no new claims; bounded transaction drains/rolls back; exit before hard timeout |
| Abrupt death | Kill only recorded acceptance worker PID; supervisor restarts; natural lease expiry/reclaim; original committed preparation and domain command retained |
| Failure policy | Verify child and wrapper failures separately; bounded restart behavior, no restart storm, no automatic restart after intentional stop |
| Rotation | New vault credential accepted on reconnect/restart; old credential rejected for new connections; existing sessions identified and drained/terminated separately |
| Readiness failure | Wrong Windows identity, extra PG memberships, missing secret/schema/implementation or unapproved target admits no work |
| Telemetry | New process instance resets local counters explicitly; database history persists; failed health reads remain errors |

Do not accelerate lease expiry with fixture SQL in the host reclaim proof: that
shortcut remains useful in portable tests, but does not prove host timing.
For graceful shutdown, a hard-stop bound must exceed application drain and bounded
cleanup, then be measured. **WinSW 2.12.0's custom-stop path does not enforce
`stoptimeout`**: see the source-backed gate in Host Integration Decision 3 and
the [Decision 4 application-owned controller](BOUNDED_WINDOWS_STOP.md). Actual
installed-host timeout acceptance remains unperformed. Forced kill is not a
successful drain.

Retained evidence includes run ID, OS/build/wrapper hashes, service/account SID,
wrapper and child PIDs, effective recovery/stop settings, readiness verdicts,
redacted supervisor/application logs, original and restarted process IDs,
work/preparation/result IDs and database invariants before/after. Never retain
passwords, vault blobs, lease tokens or full connection strings. Restrict access
to logs and review redaction before export.

## Reporting boundary

Previous results remain: application 507 passed; deployment database 14 passed;
portable process/config 8 passed and 1 Windows SIGTERM case skipped. Those are
previously recorded results, not a rerun for this decision.

Host acceptance, real service-session vault access, credential rotation and SCM
stop/restart remain **unproven**. Successful host acceptance would establish an
operable non-production service only, not approved production market evidence.
