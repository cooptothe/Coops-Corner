# Immutable qualification ledger

Migration 008 adds policy judgments over persisted EngineEvaluations. It does not
create Opportunities, query current quotes, recalculate EV, or reevaluate freshness.
A judgment made today about yesterday's evaluation remains about yesterday's result.

## Policy and precision

The v1 `minimum_ev` policy requires an explicit finite, strictly positive Decimal
threshold. There is no production default. Its comparison is `>=`:

| Persisted evaluation | Decision | Reason |
| --- | --- | --- |
| Evaluated EV >= threshold | qualified | ev_threshold_met |
| Evaluated EV < threshold, including zero/negative | not_qualified | below_minimum_ev |
| Valid not_evaluable result | not_qualifiable | evaluation_not_evaluable |

`qualify_evaluation` verifies the persisted result SHA-256 and dispatches through
the evaluation snapshot-format decoder before reading full-precision EV. It never
uses the rounded NUMERIC projection to decide qualification. For example,
`0.009999999` fails a `0.01` threshold even when the typed EV column is `0.01000000`.
Missing/malformed metrics, unsupported formats and digest mismatches raise validation
errors; they do not produce `not_qualifiable` judgments. The decision/reason matrix
belongs to the constructor, not a database CHECK tying every future reason to v1.

## Write API

```python
from decimal import Decimal
from corner.qualifications import (
    MinimumEVPolicy, QualificationCommand, record_qualification,
)

command = QualificationCommand(
    engine_evaluation_id=evaluation_id,
    policy=MinimumEVPolicy('policy-release-1', Decimal('0.01')),
    decided_at=decision_time,  # timezone-aware; generated once for this command
    context_json='{"ticket":"QUAL-42"}',
)
row = record_qualification(
    conn, authority=trusted_authority, qualification_key=issuer_key, command=command,
)
conn.commit()
```

The threshold above is illustrative, not a recommended product setting. Authority
must come from trusted execution context, never untrusted request JSON. Authentication
and runtime-role provisioning are deployment responsibilities, not implemented here.
The API accepts no independently supplied decision, result snapshot, projection, or
digest. It derives these from the command and verified persisted evaluation.

Callers own READ COMMITTED commit/rollback. An internal savepoint prevents partial
writes if a caller catches a write failure. Stronger isolation may require retrying
the whole transaction on serialization errors. Return from the function is not
durable receipt until the caller commits.

## Identity, snapshots and retries

Record `id` is database-generated UUIDv7. Command identity is
`(authority_kind, authority_id, qualification_key)`, not the evaluation, policy, or
digest. A new key can intentionally repeat the same judgment without overwriting it.

An identical retry returns the original record, including `id`, `decided_at` and
`created_at`. Reusing a key with changed evaluation, policy version/revision/threshold,
caller context, or `decided_at` raises `QualificationConflict`. Callers must preserve
both their key and decision time across retries. The retry checks both the command
digest and canonical command semantics. A sequential retry returns the recorded
judgment without reexecuting qualification. Concurrent callers may both compute;
the unique key admits one row and the losing writer compares both outputs. Divergent
outputs raise `QualificationDeterminismFailure`; the original remains authoritative.

Format `corner.qualification.snapshot/1` uses the evaluation serializer conventions:
canonical UTF-8 JSON, sorted object keys, Decimal base-10 strings, canonical UUIDs,
UTC timestamps with six fractional digits and `Z`, explicit nulls for nullable
results. Context must be an object; key order and whitespace are irrelevant, arrays
remain ordered, fractional values must be strings rather than JSON floats.

The command contains the evaluation ID, evaluation format/result digest, complete
policy snapshot and policy digest, decision time and context. The result preserves
the exact compared EV (null for not_evaluable), threshold, comparison, decision,
reason, policy identity and evaluation/result linkage. Command/result digests are
SHA-256 over canonical serialization, not JSONB textual output; neither is unique.

`policy_version` names a policy release; `policy_revision` identifies the qualification
and serializer source hashes plus Python/Decimal runtime versions in `policy_build`.
Deploy immutable application files and retain the matching source/runtime artifacts.
The digest identifies an implementation; it does not archive it for you.

## Database guarantees and boundaries

`UNIQUE (id, result_sha256)` on EngineEvaluation supports the qualification's composite
`(engine_evaluation_id, evaluation_result_sha256)` foreign key with ON DELETE RESTRICT.
It is an intentional extra candidate-key index enforcing exact result attribution.

Qualification rows have required/nonblank identity and reason fields, constrained
decision kinds, JSONB object snapshots, 32-byte digests, caller-supplied decision
time and database-created persistence time. There is no `updated_at`. Triggers reject
UPDATE, DELETE and TRUNCATE; PUBLIC has no privileges. Provision a non-owner writer
with SELECT on evaluations and SELECT/INSERT on qualifications only, plus schema
USAGE. Do not grant destructive privileges or migration-owner membership. Owners
can bypass protections and are not a supported runtime identity.

The validated API owns agreement between snapshot content and typed projections;
arbitrary SQL inserts are not a substitute for that boundary. The database enforces
the result-digest relationship, uniqueness and structural invariants independently.

## Verification

Apply migrations through 008. Pure policy tests run without database access.
`CORNER_TEST_DATABASE=1` enables rollback-only persistence tests. They cover precision,
corruption, conflicts, multiple judgments, restrictions and failed-write atomicity.

Real two-connection tests additionally require `CORNER_TEST_CONCURRENCY=1` and CREATEDB
on the configured local PostgreSQL account. They create an empty uniquely named
`corner_qualification_test_<uuid>` database, apply 002-008, commit synthetic evidence
there, and drop only that database during cleanup. They do not commit fixture data
to the application database. If the test process is forcibly terminated, its temporary
database may need explicit cleanup after verifying the generated name.

```powershell
$env:CORNER_TEST_DATABASE = '1'
$env:CORNER_TEST_CONCURRENCY = '1'
python -m unittest discover -s tests -v
Remove-Item Env:CORNER_TEST_CONCURRENCY
Remove-Item Env:CORNER_TEST_DATABASE
```

Opportunity creation/lifecycle, stake sizing, display policy and alert throttling
remain outside this migration and module.
