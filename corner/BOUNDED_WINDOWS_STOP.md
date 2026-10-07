# Host Integration Decision 4 — application-owned bounded stop

The WinSW 2.12.0 custom-stop branch does not enforce `StopTimeout`. Corner's stop
helper now owns graceful waiting, exact-process forced termination and bounded
termination verification. No wrapper switch, service installation, credential
change or domain/lease behavior change is introduced.

## Runtime identity and authority

Each fixed-role entry point takes an explicit absolute `--runtime-record` path
on a fixed local volume. The deployment must reserve its parent directory for
that service account and administrators. UNC paths, alternate data streams and
relative paths are rejected. Provisioning/parent-directory ACLs are not created
by the adapter and remain installation acceptance requirements.

At startup, `ServiceInstance` holds the existing role/SID singleton event and
creates an additional **instance-specific** stop event. It publishes:

```text
format = corner.windows-instance/1
service, sid
pid, creation_time (exact Windows FILETIME integer encoded as a string)
instance_token (fresh random UUID token)
stop_event (role + SID + PID + creation time + token)
executable (actual process image path)
```

Publication uses `CREATE_NEW`, explicit owner and protected DACL (service SID and
LocalSystem only), non-inherited handles, no writable sharing and delete-on-close.
Existing records are never overwritten or automatically deleted as "stale."
The owning handle remains open for the service lifetime; a helper opens with
read access and compatible sharing, checks owner/DACL and rejects reparse-point
or directory records. A held helper handle can delay final record deletion.
That fails restart safely until handles close instead of retargeting the helper.

This is a disposable runtime record, not database authority or retained audit
history. It is protected against other accounts, not malicious code running under
the same account or administrators. The instance token binds artifacts; it is
not a substitute for ACLs or a secret credential.

## Stop sequence

The fixed-role stop entry point:

1. Validates explicit positive, finite shutdown durations and the Windows SID.
2. Opens the exact record; verifies its format, owner, ACL, role and event binding.
3. Opens the recorded process with query/synchronize/terminate rights and retains
   **that same handle** through the operation. Checks creation time, executable
   and account; refuses self-termination. PID alone never authorizes a kill.
4. Opens and signals the exact instance event. Waits using a monotonic graceful
   deadline, independent of database time, lease expiry and poller backoff.
5. If the process remains alive, rereads the held record and rechecks identity
   through the same process handle; calls `TerminateProcess` on that handle only.
6. Waits for process termination through the separate verification deadline.
   An unconfirmed termination is failure, not a successful stop receipt.

Windows exposes creation time through `GetProcessTimes`. `TerminateProcess` is
asynchronous when called on another process, so waiting on the retained handle
is required to establish exit. [Process times](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes),
[termination semantics](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-terminateprocess).

The controller targets **one exact worker process and all its threads**, not a
PID-enumerated process tree. Current workers do not spawn child processes. A
future child-process workload requires a separately designed containment/job
boundary; do not add `taskkill /T` or broad process-name matching here.

Successful results distinguish `graceful_exit`, `forced_exit`, and
`already_exited`. Forced exit uses code 137, not a claim of orderly shutdown.
Two helpers that acquire the same live instance can safely signal/wait together.
After record deletion, a further stop attempt lacks verifiable authority and
fails safely; it does not invent a process or claim that all service state is gone.

## Invocation and deployment pinning

All three modules use the same shape, with the role fixed by the module:

```text
python -m corner.services.execution run --config <config.json> --approval <approval.json> --runtime-record <absolute-instance.json>
python -m corner.services.execution stop --expected-sid <SID> --runtime-record <absolute-instance.json> --graceful-drain-timeout 45 --hard-stop-verification-timeout 5
```

45/5 seconds is an explicit suggested acceptance configuration, not a product
default; CLI arguments are required. Pin both values with the deployment. The
grace allowance should exceed the configured application drain plus bounded
cleanup; tests deliberately use shorter allowances for synthetic hangs. Changing
these values does not change lease duration, SQL semantics or frozen work.

The WinSW stop command needs no DB configuration, credential, stdin or database
driver. Its record path/SID must match the start command. Configure the exact
approved interpreter/module/path rather than searching PATH or process names.

## Failure boundary — do not hide it

Missing/corrupt/partially published identity, changed creation time, wrong token,
wrong role/account/image, missing exact event, access denial or unexpected ACL
means **refuse termination**. There is no PID-only fallback, record overwrite,
automatic privilege escalation or broad cleanup. Host errors are redacted.

The waits are bounded, not a hard-real-time OS guarantee against kernel/storage
failure. A helper error or unverifiable target can still leave WinSW waiting on
its child: the wrapper's unbounded branch has not changed. Operators must inspect
the identity/failure evidence and use a separately authorized recovery procedure.
Do not promise that SCM always reaches Stopped merely because the helper exits.
Helper crash/hang and installed SCM behavior remain actual-host acceptance cases.

## Local proof and remaining host proof

Reverified on 2026-10-01: **12/12 bounded-stop tests**, **22/22 host-adapter
tests**, and **507/507 application regression tests**, including forced
transaction rollback and natural lease reclaim of the
original preparation. These are foreground-child tests under the current Windows
test identity; no service, Windows account or vault entry was provisioned.

Verified locally on Windows, 2026-09-30: **12/12 bounded-stop tests**, **22/22
host-adapter tests**, **14/14 deployment DB tests**, **8 portable process/config
tests passed with 1 Windows SIGTERM skip**. Separately, **507/507 application
regression tests passed**. The skipped signal case remains unexercised.

The local suite launches only disposable foreground children, never an installed
service. It proves graceful exit without force; hung-drain force and exit code;
creation-time/token/role/image/ACL refusal; same-handle revalidation; duplicate
helpers; stale-record safety; database-independent CLI control; and failure when
termination confirmation is unavailable.

The DB adapter case kills a deliberately hung worker **after** domain writes and
work completion execute but **before** their transaction commits. It verifies the
row lock is released, both writes rolled back, the committed preparation remains,
natural DB-clock lease expiry permits reclaim, and restart produces one result
using that same preparation. No expiry timestamp is advanced by test SQL.

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:CORNER_DEPLOYMENT_ACCEPTANCE='1'
python -m unittest discover -s acceptance -p test_windows_shutdown.py -v
python -m unittest discover -s acceptance -p 'test_host_adapt*.py' -v
```

These are not proof of WinSW/SCM reaching Stopped, service-account vault access,
cross-account denial, supervisor restart, installation ACLs or credential rotation.
Repeat the rollback/reclaim and timeout scenarios under the actual service before
declaring host acceptance. Production authorization remains unchanged.
