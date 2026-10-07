# Host acceptance evidence

## Installed lifecycle — 2026-10-01

The administrator-run report for `CornerHost8211034cc246` records all five checks
passed: repeated SCM graceful stop/start, active completion drain, forced-stop
rollback/frozen reclaim, supervisor restart/exactly-once recovery, and no test
passwords found in retained evidence. Forced SCM stop took approximately 5.73 s.

Original report (preserved, not rewritten as an automatic success):
`C:\ProgramData\CornerHostAcceptance_8211034cc246\report.json`

SHA-256: `d2cb90d6ada63a3169e174b02eea418c3ec99560c70ce766b3d1681d3f889656`

Its overall status was `failed_cleanup_required`: Windows profile deletion
returned sharing violation 32 after the service and database/roles were removed.
The test account/profile remained. After the user's normal reboot, the guarded
cleanup reported service/profile/account absent at 2026-10-01 16:20:13 UTC.

Cleanup receipt, bound to the original report digest:
`C:\ProgramData\CornerHostAcceptance_8211034cc246\cleanup-0d2366ee837d477aaab310817f965bd3.json`

These paths/digests/results were supplied by the administrator running the
harness. The redacted logs remain in that private evidence directory.

## Boundaries

- One disposable execution service, WinSW 2.12.0, actual SCM and user-bound vault.
- Lifecycle host proof complete; cleanup required reboot/manual recovery.
- Descendant-process cleanup is not proven.
- Production-positive authorization remains disabled.
- Credential rotation is a separate acceptance run; it is not inferred from
  the lifecycle result. See [the rotation contract](CREDENTIAL_ROTATION.md).
