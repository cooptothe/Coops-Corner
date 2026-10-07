# Credential rotation/revocation acceptance

This is a separate, explicitly opted-in test of one disposable execution service
on the isolated local PostgreSQL database. It does not rotate production accounts,
Windows service-account passwords, or domain identities.

## Session policy: stop, drain, revoke, restart

1. Start with the original vault credential and pass real SCM/runtime readiness.
2. Commit a versioned qualification preparation, then stop the service at the
   test-only pre-completion checkpoint. The transaction unwinds; the frozen
   command and reclaimable lease remain. SCM must confirm `STOPPED`.
3. Change only the PostgreSQL password for the **same LOGIN**. No renaming,
   membership, domain-authority, config, grant or command changes are permitted.
4. Reject the old password on fresh connections. Each of three negative probes
   is surrounded by successful new-password controls to the same endpoint. A
   connection outage is not evidence of revocation. Other transports/HBA paths
   are not covered by this configured-route test.
5. Keep one intentional, idle, old-authenticated harness session open across
   rotation. Demonstrate that it still works: reconnect failure does not imply
   session termination. The administrator then terminates this exact session,
   matched by PID, backend start time, database, LOGIN and application tag.
6. Verify the old connection is unusable and no sessions remain for this test
   LOGIN/database. Unknown residual sessions are a failure requiring inspection,
   **not** permission to terminate sessions broadly.
7. Attempt one SCM start while Credential Manager still contains the old secret.
   Disable automatic recovery for this deliberate failure. Readiness must fail,
   no work may be claimed, and the service must stop.
8. Replace only `Corner/Postgres/Execution`'s password under the same Windows
   account. Restart manually, pass readiness, and complete the original frozen
   qualification with the original authority/key and exactly one decision.
9. Stop and verify no test-role sessions remain; perform normal disposable cleanup.

This accepts downtime. Database password replacement and vault replacement are
not atomic. If either step fails, leave the service stopped, preserve the frozen
work, and report failure. Do not roll back to the revoked password or invent new
command identities to recover. Automatic emergency fleet-wide revocation is not
implemented by this test.

## Evidence and password handling

The report freezes the role/privilege fingerprint, held-session binding,
unchanged configuration hashes, preparation digest/ID, domain authority/key,
decision ID, and redacted SCM/readiness logs. The worker's process/lease owner can
change on restart; the frozen domain-command identity cannot.

No plaintext password is passed in XML, argv, files, or environment. Initial
disposable role creation and rotation send a client-generated SCRAM verifier
rather than cleartext SQL password literals; verifiers remain sensitive and must
not be exported. The setup credential stays in the administrator process.

PostgreSQL warns that plaintext `ALTER ROLE` password statements can appear in
logs; [ALTER ROLE documentation](https://www.postgresql.org/docs/18/sql-alterrole.html).
The harness uses the explicit backend-termination operation rather than assuming
authentication changes kill sessions; [server-signaling documentation](https://www.postgresql.org/docs/18/functions-admin.html#FUNCTIONS-ADMIN-SIGNAL).

## Proof levels

- `test_credential_rotation.py`: six checks covering disposable PostgreSQL password
  replacement, negative-auth controls, exact session revocation, fail-closed
  guards, and preserved frozen qualification identity. **Passed locally.**
- Installed Credential Manager/WinSW rotation: **not performed yet**. The six
  checks above do not stand in for this host proof.
- Production rotation, all service roles, external pools, multiple DB endpoints,
  and rotation of the Windows service-account password: outside this slice.

## Administrator-run command

No existing service is reused. This provisions one fresh disposable account,
service and database, then attempts cleanup and retains evidence.

```powershell
Set-Location 'C:\Users\edwar\Documents\GitHub\odds_data_pipeline'
& 'C:\Users\edwar\AppData\Local\Python\pythoncore-3.14-64\python.exe' -B .\acceptance\run_credential_rotation.py --winsw 'C:\Users\edwar\AppData\Local\Temp\corner-winsw-pin-70f31527689c46b78366c20375640f94\WinSW-x64.exe' --execute
```

Keep the elevated window open. Paste the final redacted JSON, not credentials.
If profile cleanup again reports sharing violation 32, preserve the original
report, restart Windows normally, and use `cleanup_scm_profile.ps1` with that
new report path. The helper understands both report versions but still refuses
loaded profiles or mismatched account/SID bindings. Do not force-unload hives.
