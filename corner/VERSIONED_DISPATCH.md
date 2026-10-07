# Versioned Dispatch Decision 1 — explicit installed routing

Implemented without a schema migration, poller, production approval, or changes
to existing pinned modules. Use `versioned_reconciliation.sweep` and
`versioned_dispatch.run_once` as the version-aware discovery/execution boundary.
The original entry points remain the original implementations, not universal
dispatchers.

## Routing authority

A completed, explicitly routed evaluate WorkRequest remains the assignment of
an evaluation to a condition/generation. Compatibility never creates assignment.
The version-aware reconciler validates its request, exact frozen implementation,
completion ownership, evaluation and generation before requesting qualification.

New qualify, occurrence and lifecycle requests retain `intent.dispatch`:

- routing format `corner.work.routing/1`;
- exact installed handler, command format and implementation revision;
- generation ID/configuration digest, where the operation has a generation;
- source artifact ID, format and command/result digest.

The route is constructed from immutable records, not supplied as an arbitrary
handler name by the caller. Engine, qualifier, calculation basis and complete
generation configuration must agree. New downstream preparation freezes the
route with its domain command under `corner.work.dispatch/1`.

Generation formats /1, /2 and /3 are recognized explicitly. /2 supports the
conditional qualification path but does not acquire /3 capture authority.
V2 lifecycle/assessment require a generation the existing v2 adapters actually
support. A known generation is not permission to synthesize missing policy.

## Installed implementation paths

| Work | Explicit path |
| --- | --- |
| evaluate v1 | Existing v1 selector and engine, pinned selector/engine identities |
| evaluate v2 | Existing approval-backed conditional capture and engine |
| qualify v1 | Original full-precision v1 qualifier |
| qualify v2 | Conditional-basis qualifier with exact generation policy |
| ensure_occurrence | Native qualified-decision identity; qualified source format is retained |
| assess v1 | Original frozen v1 command and assessment interpreter |
| assess v2 | Existing fresh v2 capture or its original frozen command |
| apply_lifecycle v1 | Original application decoder/reducer |
| apply_lifecycle v2 | Version-aware application decoder/reducer |

An installed handler is an exact `(work_kind, command_format, revision)` match,
not a `latest` alias. Unknown/missing identities block; incompatible generation
or source bindings fail validation and block. None falls back to v1 or upgrades
a frozen command. Adding another handler does not retarget earlier commands;
the exact old implementation must remain installed. If it has been removed,
work blocks rather than pretending reproducibility is still available.

Native v1/v2 evaluation capture factories and the v2 assessment intent factory
already pin explicit selector/adapter revisions. Continue using them rather than
wrapping their intent in a different shape. A new automated v1 assessment capture
path is not introduced: only its already-frozen commands execute here. Missing
or unsupported capture identities block; no phase evidence is invented.

## API usage

For new static downstream work, the producer calls `request_intent` with a cursor,
work kind, typed sources and operation details, then `work.enqueue` using that
returned JSON. The factory supports `qualify`, `ensure_occurrence` and
`apply_lifecycle`. Lifecycle details name the exact command kind; sources name
the corresponding immutable evidence. Neither preparation time nor domain key
is allocated by discovery.

`run_once(connect, settings=..., request_id=..., source=...,
evaluation_validator=...)` processes one explicit request. The connection factory
must provide authenticated non-owner runtime authority. Source/validator objects
are trusted deployment dependencies, never arbitrary WorkRequest JSON. Only the
selected capture path uses them; frozen retries never invoke capture again.

Claim, preparation fencing, wall-clock lease semantics and bounded transactions
reuse the existing work APIs. Domain writes still use the existing authoritative
adapters. Completion holds the execution fence while persisting the domain result
and typed completion reference atomically. Failure recording occurs after rollback
in a fresh fenced transaction. Completed negative/non-evaluable outcomes remain
successful work. Lost-acknowledgment recovery verifies original preparation and
completion ownership before returning the committed result.

## Compatibility without defaulting

Previously prepared work can lack the new dispatch envelope: its existing exact
format/revision is itself an explicit identity. It is validated against its
immutable routed generation and executed by that installed version.

Specific older unprepared v1 intents also retain enough authority: a qualifier
intent carries its full versioned policy and known routing format; a lifecycle
intent names a command and exact validated v1 generation; occurrence intent
names a v1 qualified artifact and the fixed native operation. These shapes are
recognized explicitly and frozen with the resolved route without modifying the
WorkRequest. A generic qualify intent with no policy/version still blocks, even
when its generation happens to be v1. This is compatibility decoding, not an
absence-means-v1 rule.

## Discovery remains discovery-only

The version-aware reconciler covers the same three obligations as before:
evaluation to qualification, qualified decision to occurrence, and ordered
activation to condition application. It does not add assessment/deadline
discovery, market-dependency routing or lifecycle fan-out.

It keeps the original obligation namespaces/keys. Existing blocked or waiting
requests remain visible and are never bypassed by a new version namespace.
Repeated/concurrent scans converge on one request with deterministic route
metadata. Existing valid manually written qualifications can satisfy an explicit
assignment; contradictory authoritative judgments remain integrity failures.
Activation fulfillment still requires a verified receipt's resulting generation
and activation markers, not merely a matching source reference.

The original page size, transaction, cursor-wrap and late-commit rules remain.
The finite-pass ceiling proposed for polling has not been added in this slice.

## Verification and remaining boundary

The focused PostgreSQL suite exercises both families, mixed-family rejection,
missing/unknown frozen identities, original pinned retries, deterministic and
concurrent discovery, competing claims, non-evaluable completion, rollback,
v1 frozen assessments/evaluations and explicit v1/v2 lifecycle execution.

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:CORNER_TEST_DATABASE = '1'
$env:CORNER_TEST_CONCURRENCY = '1'
python -m unittest discover -s tests -p test_corner_versioned_dispatch.py
```

No new runtime grants or main-database migration are needed. Production-positive
authorization remains disabled. Polling still needs its own bounded cycle,
fairness, finite-pass traversal and shutdown acceptance tests before activation.
