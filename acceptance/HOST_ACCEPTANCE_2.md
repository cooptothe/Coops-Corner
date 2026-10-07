# Host Acceptance Decision 2 — installed WinSW/SCM lifecycle

Scope approved: one disposable WinSW 2.12.0 test service, one dedicated test
Windows account and disposable PostgreSQL credentials against an isolated
non-production database. Credential rotation and production authorization are
outside this slice. No EV, lifecycle, polling or orchestration changes are planned.

## Preflight result — 2026-10-01

**Blocked before provisioning. Installed-service acceptance not performed.**

- Windows host architecture: x64.
- Official WinSW 2.12.0 x64 download is present; SHA-256 rechecked against
  `winsw-artifact.json`:
  `05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da`.
- Outside the sandbox, the actual Windows token is not elevated.
- A read-only native SCM probe successfully opened `SC_MANAGER_CONNECT`.
- The same probe requesting `SC_MANAGER_CREATE_SERVICE` failed with Win32
  **5 / ERROR_ACCESS_DENIED**. It did not call `CreateService`.
- An initial PowerShell interop probe returned error 123 from incorrect null
  handling. That result was discarded; the corrected native probe above is the
  permission evidence.

No service/account/vault credential was created; WinSW was not executed.
No isolated database was provisioned for this attempted host run. No existing
service, database, credential or runtime permission was changed.

Tool sandbox approval does not supply a Windows administrator token. An
administrator-approved execution/provisioning path is needed before continuing.
Do not weaken SCM ACLs, switch the test to LocalSystem, or treat the existing
foreground-process tests as installed-service proof to bypass this blocker.

## Acceptance cases still required

An administrator can now run `host_preflight.py --winsw <absolute-pinned-exe>`
with the project's Python interpreter. It checks SCM create-service access,
binary hash/size, imports and read-only PostgreSQL setup privileges. Its output
is redacted JSON; `preflight_ok` is not an installed-service acceptance result.
This script contains no installation/account/vault/database creation operation.
The privileged provisioning and installed-service scenario harness is still to
be prepared; do not infer that a successful preflight performs those cases.

1. Install the pinned wrapper and fixed execution entry point under the dedicated
   test account. Verify effective Windows SID, PG runtime role, readiness and the
   protected process-instance record. Use approved local installation/runtime/log
   directories and per-account Credential Manager access; no secrets in XML/argv.
2. Issue real SCM stop. Retain the chain from SCM through WinSW and the bounded
   helper to cooperative exit and SCM `STOPPED`.
3. Exercise a deliberate hung drain. Verify the helper forcibly terminates the
   exact original PID/creation-time/token-bound instance within its two explicit
   timeout budgets, then SCM reaches `STOPPED`.
4. Abruptly terminate only the verified acceptance worker process. Verify actual
   supervisor restart, natural lease reclaim, original preparation identity and
   one authoritative result.
5. Force termination during a real uncommitted domain/completion transaction.
   Verify rollback and subsequent exactly-once recovery through the installed
   topology, not a foreground stand-in.
6. Repeat stop/start and duplicate-stop cases; verify no stale event/record is
   inherited and no unrelated process is targeted.

Retain redacted SCM event evidence, WinSW/application logs, wrapper and worker
PID/creation identities, readiness results, request/preparation/execution IDs,
final domain result and exact installed configuration/build hashes. Test-only
fault checkpoints must be identified explicitly. Record cleanup of the exact
disposable service/account/credentials after the run, without broad deletion.

**Scope limitation:** bounded stop guarantees termination of the exact wrapped
service process only. Descendant-process-tree cleanup is not proven. Current
entry points must not spawn long-lived child processes; adding them requires a
new containment design.

The helper intentionally refuses unverifiable identity. Such refusal can leave
WinSW waiting on its child; report that failure and require authorized recovery,
never a PID-only kill fallback. `STOPPED` must be observed from SCM, not inferred
from helper exit or a log message.

## Result classification

Current result: **preflight blocked / zero installed-service cases exercised**.
Existing local and application test results remain separate. Credential rotation
comes after installed lifecycle acceptance; real approved production evidence
remains independently required for production-positive opportunities.
