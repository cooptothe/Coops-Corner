# The Corner migrations

After 012, apply `013_corner_v2_actionability_reasons.sql` with
`psql -X -v ON_ERROR_STOP=1`. It extends the transition evidence-shape CHECK to
permit the explicit v2 authorization/conditioning closure reasons. Existing
history, projections, grants and table shapes are unchanged. The constraint is
validated transactionally. This migration does not authorize production sources
or start a worker. See `corner/V2_ASSESSMENT.md` for the versioned adapters.

After 011, apply `012_corner_work_ledger.sql` with `psql -X -v ON_ERROR_STOP=1`.
It creates immutable work requests/preparations and mutable fenced execution state,
not a polling/reconciliation worker. Provision non-owner profiles explicitly with
`corner/runtime_roles.py` and apply its work grants afterward. Role creation is a
separate cluster-level deployment action, not a schema migration side effect.
See `corner/WORK_LEDGER.md` and `corner/RUNTIME_ROLES.md`.

After 010, apply `011_corner_lifecycle_ledger.sql` with `psql -X -v ON_ERROR_STOP=1`.
It adds canonical conditions, append-only application/transition history and both
rebuildable projections. It adds no scheduler, activation fan-out or alert delivery.
See `corner/LIFECYCLE_LEDGER.md` for transactional locking, exact retries, incremental
context, canonical replay verification, recovery and disposable PostgreSQL tests.

After 009, apply `010_corner_actionability_assessments.sql` with
`psql -X -v ON_ERROR_STOP=1`. It creates immutable actionability assessments and
explicit selected/missing stream evidence. It introduces no lifecycle application,
transition, episode or activation fan-out. See `corner/ASSESSMENT_LEDGER.md` for
capture versus persistence, authority/key retries and disposable PostgreSQL tests.

After 008, apply `009_corner_channels_and_occurrences.sql` with
`psql -X -v ON_ERROR_STOP=1`. It creates stable qualification channels, immutable
configuration registrations and activation history, plus structurally qualified-only
occurrences. It does not create assessments, condition applications or episodes.
See `corner/CHANNEL_LEDGER.md` for writer serialization, privileges and disposable
PostgreSQL constraint/concurrency tests.

After 007, apply `008_corner_qualification_decisions.sql` using
`psql -X -v ON_ERROR_STOP=1`. It adds the evaluation/result-digest candidate key
and the immutable qualification ledger with a composite ON DELETE RESTRICT FK.
Grant the non-owner qualification writer SELECT on engine_evaluations and
SELECT/INSERT on qualification_decisions, plus schema USAGE. No UPDATE, DELETE,
TRUNCATE or ownership. See `corner/QUALIFICATION_LEDGER.md` for policy, retry and
test contracts. This migration does not create Opportunities.

After 006, apply `007_corner_engine_evaluations.sql` using `psql -X -v ON_ERROR_STOP=1`.
It creates the immutable evaluation and input ledgers. Grant only SELECT/INSERT
to the trusted runtime writer; deny UPDATE/DELETE/TRUNCATE and ownership. See
`corner/EVALUATION_LEDGER.md` for command identity, serialization and build retention.

After 005, apply `006_corner_trusted_current_quotes.sql` to create the ordinary
`corner.trusted_current_quotes` view. Grant approved consumers schema USAGE and
SELECT on this view during role provisioning. No view privileges are granted to
PUBLIC. The projection excludes rejected evidence before selecting the latest
observation and applies neither freshness nor quote-state filtering.

Migration `005_corner_observation_dispositions.sql` adds immutable eligibility
decisions, the rejected/reinstated reference vocabulary, authority-scoped command
uniqueness, and the `(observation_id, decided_at DESC, id DESC)` lookup index.
Apply it after 004 with `psql -X -v ON_ERROR_STOP=1 -f` and the same database options.
It does not create a trusted/current quote projection.

Runtime authority provisioning remains a deployment step: use a non-owner login,
grant schema USAGE, SELECT on disposition_types, and only SELECT/INSERT on
observation_dispositions. Do not grant UPDATE, DELETE, TRUNCATE, table ownership,
or membership in the migration-owner role. PUBLIC receives no table privileges.
Triggers reject UPDATE/DELETE and TRUNCATE on the decision ledger as additional protection.

The existing `public.sports`, `public.games`, and `public.odds` tables are the legacy pipeline and remain untouched by The Corner foundational migrations.

Apply migrations in lexical order:

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -d odds_data_pipeline -f db/migrations/001_append_only_odds.sql
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -d odds_data_pipeline -f db/migrations/002_corner_reference_foundations.sql
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -d odds_data_pipeline -f db/migrations/003_corner_events_markets_and_provider_identities.sql
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -d odds_data_pipeline -f db/migrations/004_corner_ingestion_and_observation_ledger.sql
```

`001_append_only_odds.sql` is only needed for databases created from the original legacy schema. It is retained as migration `001`; The Corner foundational schema therefore begins at `002`.

These migrations require PostgreSQL 18 because they use `uuidv7()` and `UNIQUE NULLS NOT DISTINCT`.
