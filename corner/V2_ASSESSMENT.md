# V2 assessment capture: current authority over historical analytics

Implements V2 Assessment Capture Decision #1. Only synthetic approval fixtures
are supported. No production authority, source approval, polling, automatic
lifecycle application, or changes to the rejected DraftKings review are included.

## Versioned boundaries

- `actionability_v2.py`: pure authorization/conditioning and actionability policy.
- `assessments_v2.py`: coherent trusted-stream capture, immutable evidence
  validation, assessment persistence and versioned fact decoding.
- `assessment_worker_v2.py`: one explicitly routed `assess` work request, under
  the existing lease/preparation/completion machinery.
- `lifecycle_versions.py`: explicit v1/v2 evidence dispatch and journal replay.

Contracts are `corner.actionability/2`, `corner.actionability.capture/2`,
`corner.work.assessment/2`, and `corner.lifecycle.application/2`. Source-derived
implementation revisions are pinned. A new immutable channel generation uses
the existing configuration/3 representation with the v2 actionability identity;
an old generation never acquires the new policy implicitly.

Original engines, serializers, validators, assessment/lifecycle adapters and work
modules remain unchanged. The lifecycle journal algorithm is a versioned fork
of the existing adapter to preserve its pinned bytes. It shares the original
chronology, reducer context and episode helpers; only evidence dispatch and v2
assessment interpretation differ. Mixed history replays each receipt under its
declared reducer. Unknown versions or reasons are failures, never boolean-only
fallbacks or ordinary ignored receipts.

## Three independently frozen questions

1. Are today's trusted target and contributing reference observations exactly
   the observations used by the qualified evaluation?
2. Are phase, rules and approval authorities valid at `assessed_at`?
3. Do current settlement conditions agree with one another AND with the exact
   historical evaluation's conditioning and invalidation contracts?

The historical basis includes evaluation ID, command/result digests, conditional
probability/EV basis, decisive/push structure, conditioning/invalidation objects,
and historical assertion references. It is decoded from that evaluation, not
reconstructed from today's configuration. Qualification reads the immutable
evaluation result; assessment does not rerun EV.

Capture retains every expected target/contributing-reference stream, including
explicit missing-stream rows and retained rejection witnesses. Missing is not
an invented unavailable quote. Current quote selection is one MVCC statement;
subsequent execution validates its retained visibility and evidence witnesses,
not today's trusted view.

Fresh source acquisition freezes the complete synthetic loader catalog, exact
raw content/digests, inventories (including absent/adverse records), assertion
envelopes, approval artifacts and resolution receipts. Resolution at assessment
time records effective intervals, known withdrawals and the pinned approval
policy. Withdrawal knowledge must already be available at capture; a known
future-effective withdrawal may become effective by `assessed_at`.

This is a deployment-owned synthetic test repository, not a production trust
root. Digests prove integrity relative to that repository, not authenticity or
completeness of the real world. Caller-supplied WorkRequest JSON cannot install
a loader or grant an approval. `environment=production` has no installed path.

## Negative evidence versus failure

Validly verified negatives produce immutable `actionable=false` assessments:

| Assessment reason | Lifecycle closure reason |
| --- | --- |
| `target_unavailable` | same |
| `target_stale` | same |
| `analytical_evidence_stale` | same |
| `analytical_evidence_changed` | same |
| `unsupported_or_unknown_phase` | `unsupported_phase` |
| `approval_withdrawn` | same |
| `approval_expired_or_not_applicable` | same |
| `settlement_authority_unknown` | same |
| `current_settlement_incompatible` | same |
| `analytical_conditioning_changed` | same |

All reasons are retained; the table order is the deterministic primary-reason
priority. Current books agreeing on a *new* population produces
`analytical_conditioning_changed`, not approval of the historical calculation.

Corrupt content/digests, wrong bindings, unsupported formats/revisions, altered
assertions and incomplete manifests are failures: no assessment is written.
A complete inventory that proves a required source/authority is missing is
different from an unverifiable inventory: it yields a negative judgment. A
missing installed loader is an operational waiting prerequisite, not a fact.

All retained rules are validated, including old/adverse revisions. Only rules
whose intervals apply at assessment time govern the current classification;
expired revisions remain evidence but do not themselves require active grants.
Every currently applicable record needs authorization. Conflicting applicable
rules cannot be hidden by choosing the latest favorable record.

Quote freshness and phase expiry preserve their inclusive deadline semantics.
Rules and approval intervals are start-inclusive, end-exclusive. The result
retains these deadlines separately. Assessment is timed after capture, never
backdated to an expiry deadline. Missing target streams have no current target
deadline, while historical analytical deadlines remain in the result.

## Work and lifecycle are separate

Use `assessment_worker_v2.request_intent` to freeze watermark and optional basis
assessment IDs. The request's typed sources identify condition, generation and
qualified decision. `run_once` claims only that explicit `assess` request.

Capture occurs outside the execution-row lock. Preparation then rechecks the
wall-clock lease fence and persists exactly once; concurrent preparers return
the winning frozen command. Completion locks/fences execution, validates retained
evidence, writes the assessment and completion reference in one transaction.
A verified negative assessment is successful work completion.

After preparation, quote movement, phase expiry, withdrawal or rules changes
cannot alter the command. Retry reuses it without fetching current sources.
Failed domain/completion writes roll back together; a still-valid worker may
record operational failure in a new fenced transaction. Stale workers cannot
persist preparation or errors. Reclamation cannot overtake a valid completion
transaction holding the row fence.

Assessment work emits no lifecycle receipt or episode side effect. An explicit
call to `lifecycle_versions.apply_command` decides applicability using the
existing watermark, basis-assessment, chronology and generation rules. A valid
negative assessment with an obsolete binding remains historical/no-op. Replay
and rebuild use retained ledgers only, never current quotes or approvals.

## Migration and verification

Migration 013 extends only the existing transition evidence-shape CHECK for the
new closure reasons. It introduces no table, authority, grant or mutable history.
Apply after 012 before writing v2 authorization-closure transitions. Runtime
profiles use their existing assessment/lifecycle permissions; credentials remain
a deployment concern.

The focused suite uses disposable PostgreSQL databases and non-owner worker roles:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:CORNER_TEST_DATABASE = '1'
$env:CORNER_TEST_CONCURRENCY = '1'
python -m unittest discover -s tests -p test_corner_v2_assessments.py
```

Tests cover historical/current conditioning, authority timing, corruption,
missing streams, all reason categories, frozen retries, duplicate preparation,
lease loss, concurrent idempotency, atomic rollback/completion, explicit lifecycle
closure, obsolete assessments, mixed-version replay and projection rebuild.
