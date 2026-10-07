# Immutable evaluation ledger (format corner.ev.snapshot/1)

Migration 007 stores completed domain evaluations separately from future
qualification and Opportunities. A synchronous call returns an estimate or an
engine non-evaluation result. Selection failures and runtime exceptions are not
EngineEvaluation rows. No job orchestration or retention policy is introduced.

## Write API

```python
command = EvaluationCommand(selection.snapshot, selection.configuration,
                            context_json='{"ticket":"EV-42"}')
row = record_evaluation(conn, authority=trusted_authority,
                        evaluation_key=issuer_key, command=command)
conn.commit()
```

Authority is supplied separately by trusted execution context. The API accepts no
independently specified metric columns, result JSON, input links, or hashes.
It canonicalizes the command, validates supplied quotes against observation rows,
executes the engine, and derives all persisted representations. Quoted values,
states and observation timestamps must agree with the referenced evidence. Phase
and settlement validation still belongs to the trusted upstream adapter.

The caller owns the transaction. An internal savepoint makes the header and all
input rows atomic even if the caller catches a write failure and later commits.
Use READ COMMITTED; retry serialization errors at stronger isolation levels.

The unique key is `(authority_kind, authority_id, evaluation_key)`. Identical retry
returns the original row without recalculation. Changed commands conflict. A new
key is a new evaluation even with identical content/digests. If concurrent callers
both compute, the losing insert checks the complete command and result against the
winner and raises DeterminismFailure on divergent results. This provides one stored
record, not exactly-once computation or durable receipt before commit.

## Canonical serialization

- UTF-8 JSON, sorted object keys, compact separators, Unicode preserved (no Unicode
  normalization). Known nullable fields always appear as null.
- Decimal values are base-10 strings without exponent, insignificant fractional
  zeros, or signed zero. Binary float conversion is rejected.
- UUIDs are lowercase, hyphenated; timestamps are UTC with six fractional digits
  and explicit `Z`. Durations are exact integer microseconds.
- Quotes sort by observation ID; contract outcomes sort by Outcome ID; configured
  reference books sort by ID. Reference estimates/exclusions sort by book ID;
  their observation IDs and outcome/probability pairs are sorted deterministically.
- Caller context must be a JSON object. Its arrays retain order. Encode fractional
  context values as strings; JSON floating-point values are rejected to avoid
  lossy conversion or collapsing numbers and strings into the same command.
- Command/result SHA-256 digests cover the canonical UTF-8 serialization, not
  PostgreSQL's JSONB text formatting. Neither digest is unique. Retry equality
  checks both digest and full serialized semantics.

Engine revision identifies the SHA-256 of the engine source plus Python and
Decimal runtime versions in the retained build manifest. It is computed when the
persistence module loads. Deployments must use immutable application files and
archive the matching source/runtime artifact; the digest does not archive code.
Deserialization rejects incompatible engine builds instead of replaying a mutable
release label against today's code.

Typed probability/EV columns use NUMERIC(12,10)/NUMERIC(12,8), explicitly rounded
half-even at persistence. The result JSON retains calculation precision. A failed
evaluation has null metrics and an extensible text reason. `reference_book_count`
counts actual contributing reference estimates; it is zero when the engine returns
without calculating them, even if some input books passed earlier eligibility checks.

Every supplied observation receives a target/reference input link, including quotes
later excluded by the engine. Missing expectations receive no invented link.
Snapshot contract/configuration values are preserved for replay rather than rebuilt
from mutable current domain records. Target count/completeness and agreement of the
four representations are enforced by the API; the database adds uniqueness, foreign
keys, result-shape checks and immutable-row triggers. Direct arbitrary SQL writes
are outside this validated construction boundary.

Runtime roles should have only SELECT/INSERT on both ledger tables, plus the reads
required to validate input evidence. Owners and migration roles must be separate.
PUBLIC gets no privileges; role provisioning remains deployment work. No current
Opportunity, qualification rule, or display threshold is inferred from these rows.
