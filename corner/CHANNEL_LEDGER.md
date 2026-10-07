# Channel configuration, activation history and occurrences

Migration 009 is deliberately limited to four tables:

- `qualification_channels`: stable canonical identity, with durable unique code,
  descriptive metadata and active/retired capability. **No current-generation pointer.**
- `qualification_channel_generations`: append-only configuration registrations.
- `channel_generation_activations`: append-only channel activation facts.
- `opportunity_occurrences`: append-only detection of qualified decisions.

There are no assessments, condition applications, episode projections or fan-out in
this migration. Channel activation says which generation became authoritative; it
does not claim any condition processed that fact. Legacy ingestion is unchanged.

## Registration API and evidence

`corner.channels` exposes `create_channel`, `register_generation`,
`activate_generation`, and `create_occurrence`. All require an existing transaction;
the caller owns commit/rollback. Trusted execution context supplies `ChannelAuthority`
for registration and activation. This module does not authenticate request JSON.

`GenerationConfiguration` combines the existing typed `EVConfiguration`,
`MinimumEVPolicy`, `ActionabilityPolicy`, and implementation identities. Registration
accepts a `GenerationRegistration(channel_id, configuration, context_json)` and
derives all snapshots, typed identities and digests from it. It accepts no independent
hashes, snapshot JSON, or typed result columns.

The complete configuration includes engine eligibility/calculation settings,
qualification policy version/threshold/comparison, explicit actionability ages, and
each implementation's name/version/revision. Reference-book order is canonicalized.
Configuration identities must resolve to retained immutable implementations; supplying
a label does not archive or verify a build. Registration performs structural/domain
validation, not an external artifact-registry lookup or engine execution.

Configuration format is `corner.channel.configuration/1`; registration command format
is `corner.channel.registration/1`. The generation's `snapshot_format_version` names
the configuration format; the command also carries its own format identifier.
Both are canonical JSON using the existing exact serializer: decimal strings, UUID
normalization, UTC microsecond timestamps, integer-microsecond durations, sorted object
keys, explicit nulls, and no floating-point context values. Context arrays remain ordered.

The registration command preserves channel, full configuration, configuration digest,
and caller context. The authority-scoped key is:

```text
(registration_authority_kind, registration_authority_id, registration_key)
```

Same key and canonical command returns the original row/ID/created_at. Changed channel,
configuration, implementation revision, or context raises `ChannelConflict`. Comparison
checks digest **and** full command semantics. A new registration key can preserve a new
generation with identical configuration. Neither content digest is a unique identity.

`create_channel` is idempotent by canonical code and never overwrites metadata during
creation. A conflicting display name raises `ChannelConflict`; deliberate metadata
administration is separate. Generation registration does not activate anything.

## Activation serialization and retry order

`ActivationCommand` supplies channel, new generation, expected previous generation
(null for genesis), timezone-aware `activated_at`, and structured caller context.
Format is `corner.channel.activation/1`. The issuer preserves the complete command
and authority-scoped `activation_key` across retries.

The writer uses a row lock on the stable channel identity:

1. Acquire the channel lock.
2. Look up `(authority_kind, authority_id, activation_key)`.
3. If found, compare the canonical command and return the original row, or conflict.
4. Otherwise read the head by `activation_sequence`, validate predecessor equality,
   validate `activated_at >= predecessor.activated_at`, and reject reactivation.
5. Append head sequence + 1 (or 1 for genesis).
6. The caller commits; only then is the activation durable and the lock released.

Equal activation instants are valid. Sequence is the authoritative channel processing
order, not market chronology. `created_at` is a persistence timestamp and is not used
to select the head. This writer is not a scheduled-activation service: supplied
`activated_at` is command business time; delayed/future fan-out is not implemented.

Checking the existing key **before** current predecessor/time/reactivation checks
means an old successful command remains safely retryable after later activations.
Changed-key commands against a stale predecessor raise `ActivationConflict`, as do
backdated activations and generation reuse. Changed content under an existing key
raises `ChannelConflict`. New generations must exist in the specified channel.

At READ COMMITTED, competing writers for one channel serialize on its row. The
loser observes the winner's committed head and raises the stable `ActivationConflict`
rather than a raw uniqueness exception. Cross-channel reuse of a global authority/key
is resolved by the command-key unique constraint and canonical retry comparison.
Stricter isolation can produce serialization errors; retry the whole transaction
with the same command. Arbitrary SQL writers bypassing this API do not receive these
domain error guarantees.

## Structural database backstops

- `UNIQUE(id, channel_id)` on generations supports same-channel composite FKs for
  both new and expected previous generations.
- The predecessor FK uses MATCH SIMPLE: a null predecessor skips that check, while
  the nonnull channel itself is separately constrained. A nonnull predecessor cannot
  reference another channel.
- `UNIQUE NULLS NOT DISTINCT(channel_id, expected_previous_generation_id)` allows
  one genesis and one successor per predecessor.
- `UNIQUE(new_generation_id)` prohibits generation reactivation.
- `UNIQUE(channel_id, activation_sequence)` protects channel sequence identity.
- Sequences are positive; genesis has sequence 1 and null predecessor; a generation
  cannot name itself as predecessor.

The writer, not these row-local constraints alone, enforces that the predecessor was
the current activated head, that subsequent timestamps do not decrease, and that the
sequence advances contiguously. Direct inserts are not a supported alternative to the
serialized writer.

## Qualified-only occurrences

`create_occurrence(conn, qualification_decision_id=...)` reads a persisted qualified
decision and returns its detection. It does not rerun qualification or create an
opportunity episode. The table is just UUIDv7 ID, decision ID, constrained constant
`qualification_decision_kind='qualified'`, and database-created timestamp.

Migration 009 adds `UNIQUE(id, decision_kind)` on QualificationDecision. The occurrence's
composite FK binds its decision ID and constant kind to that pair. Non-qualified and
not-qualifiable decisions therefore fail even through direct SQL. Decision ID is also
unique on occurrences: concurrent requests return the winner's original row, including
ID and timestamp. No second authority/key system or copied observations are introduced.

## Atomicity, privileges and deletion

Internal savepoints roll failed writes back without forcing the caller to discard
unrelated preceding work. APIs never commit. An outer transaction can compose all
three ledger writes and roll them all back together. Locks acquired by a successful
activation remain until the outer transaction ends; keep transactions short and use
consistent channel-lock ordering if a caller composes operations across channels.

All historical FKs use ON DELETE RESTRICT. Ledger rows have no updated_at; triggers
reject UPDATE, DELETE and TRUNCATE. PUBLIC receives no privileges. Canonical channels
have created_at/updated_at and can later be retired without rewriting their history.

Provision runtime roles separately from schema owners. Writers need schema USAGE,
the relevant SELECT/INSERT privileges, and SELECT on upstream qualification decisions.
PostgreSQL row locking also requires UPDATE privilege on at least one channel column;
a narrow `UPDATE(display_name)` grant supports the activation lock without granting
mutation privileges on ledgers or authority over channel codes. Canonical metadata
mutation remains an administrative/application concern. Owners can disable triggers
and must not be used as production runtime identities. Role provisioning remains
deployment work; these tests do not certify production role configuration.

## Test commands

Pure serializer tests run without PostgreSQL; ordinary ledger tests are rollback-only
against the configured database after applying 009:

```powershell
$env:CORNER_TEST_DATABASE = '1'
python -m unittest discover -s tests -p test_corner_channels.py -v
```

The aggressive pass uses **only disposable databases** for this file. It applies
002-009, runs real two-connection races and the complete direct-SQL constraint matrix,
then drops the uniquely named databases it created. It requires CREATEDB locally.

```powershell
$env:CORNER_TEST_DATABASE = '1'
$env:CORNER_TEST_CONCURRENCY = '1'
python -m unittest discover -s tests -p test_corner_channel_concurrency.py -v
```

Coverage includes NULL-predecessor races, competing successors, retries after a newer
activation, changed-configuration registration conflicts, qualified-only occurrences,
cross-channel FKs, no reactivation, append-only enforcement, savepoint failures and
outer-transaction rollback. Test fixtures and build identities are synthetic. A forced
process termination can leave its `corner_channels_test_<uuid>` database behind;
verify the exact generated name before administrative cleanup.
