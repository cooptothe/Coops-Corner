# Installed Windows acceptance — opt-in, isolated, disposable

This is an **administrator-run test harness**, not a production installer.
Installed lifecycle acceptance passed on 2026-10-01 for the one disposable
execution service. Cleanup initially hit a loaded-profile sharing violation;
after a normal reboot, the separate guarded cleanup completed. This was not an
entirely automatic clean run. See [the retained result references](HOST_ACCEPTANCE_RESULTS.md).
The command below reruns that lifecycle slice; it does not perform rotation.

## Run

Keep the elevated PowerShell window open for the entire run. Do not run this
through an unelevated editor terminal or start a second copy concurrently.

```powershell
Set-Location 'C:\Users\edwar\Documents\GitHub\odds_data_pipeline'
& 'C:\Users\edwar\AppData\Local\Python\pythoncore-3.14-64\python.exe' -B .\acceptance\run_scm_acceptance.py --winsw 'C:\Users\edwar\AppData\Local\Temp\corner-winsw-pin-70f31527689c46b78366c20375640f94\WinSW-x64.exe' --execute
```

Allow several minutes for runtime staging, database provisioning and bounded
service tests. `--execute` explicitly authorizes this disposable installation and
the intentional process crashes. Without it, the harness makes no changes.

## Resources and containment

- Fresh local standard Windows account `cah<random suffix>`, with service-logon
  right; no Administrators membership. Its random password goes directly to SCM
  through the native API, never into XML, command arguments or environment.
- One manual-start service `CornerHost<same suffix>`, pinned WinSW 2.12.0, plus its
  uniquely named Application event-log source. Recovery restarts are configured
  in SCM; this is not a Python subprocess pretending to be a supervisor.
- Private runtime and logs under `C:\ProgramData\CornerHostAcceptance_<suffix>`.
  The test account can read code/configuration and write only runtime/log paths.
  The repository, `.env`, setup credentials and user-profile Python installation
  are not granted to the service account. Python uses the private runtime with
  isolated mode and bytecode writes disabled.
- A fresh `corner_channels_test_<uuid>` PostgreSQL database and fixture roles.
  The existing setup connection is used only by the administrator harness to
  create/drop disposable resources. It is never handed to the service.
- Only the execution LOGIN password is provisioned in that Windows account's
  `Corner/Postgres/Execution` Credential Manager entry. The provisioning profile
  handle is unloaded before starting SCM: the service must demonstrate its own
  vault access, rather than depend on the harness holding the profile open.

The existing fixture creates three isolated PostgreSQL LOGIN profiles for its
release/privilege manifest, but this installed slice runs **only execution**.
It does not test installed discovery/health services or credential rotation.

## What a successful report establishes

1. Two real SCM start/stop cycles pass actual-account readiness and remove the
   protected runtime record without inheriting stale stop objects.
2. SCM stop drains a transaction already containing a domain result/completion.
3. Hung completion crosses the five-second grace period; the existing stop
   controller verifies and terminates the exact worker, with a separate
   three-second termination verification allowance. The killed DB transaction
   leaves neither a domain result nor completion. Restart naturally reclaims
   the lease and uses the original preparation, producing one occurrence.
4. Abrupt verified worker termination causes SCM/WinSW recovery to start a new
   process instance, which reclaims the original prepared command exactly once.
5. Redacted work IDs, readiness output, PID/creation identities, SCM state samples,
   matching SCM events, WinSW logs and explicit stop-helper outcomes are retained.

`scm_service_probe.py` is a test-only fault wrapper around the **real fixed-role
execution entry point**. It changes no worker, domain, lease or polling semantics.
It pauses immediately before completion or after the uncommitted completion
write. No secret-provider substitution is used in the installed process.

The helper's own measured deadline is checked separately from the outer SCM
verification window. In pinned WinSW 2.12.0, custom-stop waits are not bounded by
`stoptimeout`, and the stop process has no normal child-output log handler;
therefore the test retains its output separately in `logs/stop-results.jsonl`.
See [the pinned WinSW implementation](https://github.com/winsw/winsw/blob/v2.12.0/src/WinSW/WrapperService.cs).

## Cleanup and failures

On success or an ordinary failure, the harness disables recovery, stops and
removes its service, removes its event source, deletes its credential/profile/
Windows account, and drops the disposable PostgreSQL database/roles. It retains
the private runtime and redacted evidence directory for inspection; it never
recursively deletes a workspace or user-supplied path.

If SCM cannot reach `STOPPED`, the harness **does not delete the account or
database underneath a possibly running service**. It reports
`failed_cleanup_required` and exact resource names. Do not rerun or perform broad
cleanup. Share the final JSON first so the remaining service can be inspected
and safely stopped. Killing the administrator harness itself can interrupt its
cleanup; the retained `report.json` and unique directory identify that run.

Do not paste credential contents. Output deliberately excludes arbitrary
database/vault exception messages. On failure, share the final JSON; any requested
log excerpt should be reviewed for secrets before sharing.

## Explicit limits

- Exact wrapped process only; descendant-process-tree cleanup is not proven.
- One disposable installed execution service, not a persistent deployment.
- No credential rotation/revocation, production approvals, alerts, or polling changes.
- Local harness/unit/DB rehearsal success is **not** an installed SCM pass.
- A production-authorized positive opportunity remains outside this topology.
