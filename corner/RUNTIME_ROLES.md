# Non-owner runtime profiles

`corner/runtime_roles.py` is an explicit DBA provisioning utility, not an automatic
startup routine. `provision(conn, prefix='corner')` creates fresh NOLOGIN group roles,
refusing any existing matching name rather than silently adopting unknown privileges.
It does not create login credentials, change DB_CONFIG, assign existing users, take
object ownership, or change migration-owner privileges. Caller owns commit/rollback.

| Suffix | Capability |
| --- | --- |
| reader | Internal SELECT on current Corner domain evidence; schema USAGE |
| ingest | Canonical ingestion INSERT and only columns updated by existing normalization/upsert APIs |
| analysis | Evaluation, qualification, occurrence, assessment and lifecycle append; projection INSERT/UPDATE |
| channel_admin | Channel registration/activation and canonical display-name updates |
| disposition | Append observation trust decisions |
| recovery | Analysis plus DELETE on the two rebuildable projections |
| work_producer | Work request/execution creation, after work grants |
| worker | Analysis + producer + preparation INSERT and execution UPDATE |
| work_admin | Execution UPDATE for explicitly authorized recovery |

All groups are NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOREPLICATION, NOBYPASSRLS,
NOLOGIN and own no objects. No runtime group has domain ledger UPDATE/DELETE/TRUNCATE
or permission to disable triggers/CREATE in `corner`. The reader is an internal
evidence role, not a public/member PWA role: raw payloads and command context can be
sensitive. Future API read models need narrower authorization.

The condition lock requires a column UPDATE privilege; analysis receives UPDATE(id)
on opportunity_conditions, whose trigger rejects actual updates. Channel admin gets
UPDATE(display_name) on the canonical channel for its lock. These are not ledger
mutation grants. Ingestion's existing ON CONFLICT UPDATE statements require narrow
display-name, mapping, membership-role and audit-timestamp grants; price/history
fields remain immutable. Grant review must follow actual SQL, not method names.

After applying Migration 012, call `grant_work_privileges(conn, roles)` with the exact
mapping returned by provisioning. It verifies expected role attributes and adds the
explicit new-object grants. No broad default privileges are installed.

Provisioning roles is not switching a service off postgres. Deployment must separately
create/configure a **non-owner LOGIN** through its secret-management process, grant only
the appropriate group(s), and update the service's connection configuration. Never
grant migration-owner membership, ADMIN OPTION or superuser capabilities. The current
utility intentionally does not choose credentials or modify the user's existing login.

The DB grants guard append-only boundaries. Trusted Python APIs guard command validity,
lease fencing and administrative workflow; direct queue DML is not a capability-safe
RPC API. Do not expose these credentials or tables to arbitrary clients.

Tests use SET LOCAL ROLE so PostgreSQL executes actual adapter SQL with each non-owner
profile. They verify positive adapter operations and SQLSTATE 42501 denials (permissions,
not merely owner-trigger failures), no ownership and no privileged role attributes.
The elevated harness alone resets roles and manages disposable DB/role cleanup.

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:CORNER_TEST_DATABASE = '1'
$env:CORNER_TEST_CONCURRENCY = '1'
python -m unittest discover -s tests -p test_corner_runtime_roles.py -v
```

PostgreSQL grants are additive, including inherited/PUBLIC privileges; production
login memberships and any preexisting broad grants still require deployment review.
See [PostgreSQL 18 GRANT](https://www.postgresql.org/docs/18/sql-grant.html).
