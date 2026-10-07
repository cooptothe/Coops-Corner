# V2 capture: retained authorization, not validated strings

This slice implements V2 Capture Decision #1 with **synthetic approval fixtures
only**. It adds no migration, assertion ledger, production approval, polling,
assessment capture, activation, or lifecycle processing. The rejected DraftKings
v1 dossier is unchanged.

## Version boundary

`capture_authority.py` assembles and reproduces the authorization proof.
`evaluation_capture_v2.py` registers capture-compatible generations and implements
one explicitly routed evaluation capture/preparation/completion attempt.

New contracts:

- `corner.channel.configuration/3` and `corner.channel.registration/3`;
- `corner.ev.selection/2`;
- `corner.capture.authorization/1`;
- `corner.decisive_rules/1` (new conditional rules, not relabeled v1 assertions);
- `corner.work.command/2`.

The engine remains the already-pinned `corner.ev.snapshot/2` implementation.
Existing v1/v2 engine, analytics, validator, capture, worker and work-ledger source
files remain byte-identical. Their source-derived revisions do not change.
Older generations lack capture authority and are rejected by the new capture
adapter; nothing is filled from global/current configuration.

Generation configuration explicitly retains the phase policy and validator
revision, settlement validation policy and validator revision, independently
versioned approval policies/references, loader identity, jurisdiction, offering,
and environment, alongside the existing engine/qualification/conditioning tuple.
Registration uses the existing generation table and registration idempotency.
Registration does not activate a generation or grant a source approval.

## Trust boundary and evidence universe

Only `SyntheticEvidenceStore` is installed. It is a trusted **test fixture
repository**, supplied by deployment/test code, never by WorkRequest JSON.
`environment=production`, a missing loader, or a different loader cannot obtain
a positive preparation. Synthetic authority cannot authorize a production scope.

The fixture repository captures its complete catalog: exact retained source bytes
(base64), content digests, source/revision identities, receipt times, scope,
approval artifacts and withdrawal records. Scope matching is exhaustive over this
snapshot: all matching revisions, including adverse/conflicting records, are
considered. There is no newest-positive-record preference or schedule inference.
Future receipt/withdrawal-knowledge timestamps are invalid, not a filtering trick.

Each phase/book stream gets a verifiable inventory with:

- loader name/version/revision and exact scope queried;
- source revisions considered and retained record identities;
- missing expected sources and adverse record identities;
- inventory capture time and catalog digest;
- its own canonical snapshot digest.

Verification reconstructs the inventory from the retained catalog and the pinned
policy/grants. Removing evidence from a manifest and recomputing its digest still
fails reproduction. A legitimately absent expected record remains explicit and
cannot authorize a required assertion.

**A catalog hash is not source authentication.** Completeness is proven relative
to the trusted loader's universe, not to every fact in the real world. An attacker
who controls the entire trusted repository/policy can invent a different universe.
No production trust root or authentication mechanism is claimed by this fixture
implementation. A future production loader needs its own reviewed, authenticated
inventory/approval-resolution contract and new pinned implementation; copying a
hand-picked JSON catalog or renaming a synthetic source does not supply it.

## Assertions and approval resolution

Phase uses the unchanged pure phase validator, exact canonical/provider Event
bindings and explicit source statuses. Future schedule time never authorizes
pregame state. Conditional settlement uses a separate versioned validator over
retained structured rules, exact Event/Market/Outcome/book/jurisdiction/offering
bindings and effective rules intervals. It does not reinterpret `no_push_two_way`.

Every required assertion preserves its complete command/result envelope, not
only an invented assertion ID/digest. The approved artifact is retained in the
catalog; each resolution also retains:

- approval artifact ID, revision and digest;
- authorized scope and assertion classes;
- effective interval;
- withdrawal state and the withdrawal evidence known at capture;
- approval policy identity/revision;
- resolution time, queried scope and result.

This first implementation requires approved authority for every retained record
in a required stream. It deliberately cannot ignore an adverse unapproved
revision to obtain a positive result. Multiple admissible conflicting meanings
fail closed. Rules/approval intervals are start-inclusive and end-exclusive;
the unchanged phase validator permits equality at its freshness deadline.

The target and reference participation are derived using the pinned engine's
eligibility/coverage kernel. Capture never removes a contributing book because its
authority is missing. If the kernel short-circuits before proving exclusions,
capture conservatively requires all configured candidates; that policy is explicit
rather than inferring nonparticipation. Candidate assertions/inventories are
retained even when engine policy excludes a book. Unknown/nonapproved evidence
for an engine-excluded book is not positive authorization and cannot contribute.

Target and participating references must match the pinned two-way decisive
structure, absent-push rule, conditioning contract and invalidation behavior.
Known incompatible conditional populations fail before preparation.

## Failure boundary

| Failure | Operational behavior |
| --- | --- |
| Missing authority/evidence, unknown assertion, ineffective/withdrawn approval | `waiting`, explicit unmet prerequisite |
| Approved but incompatible conditioning | `blocked`, `incompatible_decisive_settlement_conditions` |
| Corruption, wrong binding, unsupported format, inconsistent manifest | `blocked`, validation error |

None of these creates a PreparedWorkCommand or EngineEvaluation. Conversely, an
authorized frozen command may produce a legitimate engine `not_evaluable` result
(for example an unavailable target); that is successful work completion.

## Capture, lease fencing, and replay

The new worker is explicit-request only (`run_once(..., request_id=...)`). It
claims only `evaluate` work. It does not scan, fan out or dispatch assessment.

1. Claim; under the fence reuse existing preparation if present.
2. Release the execution lock and perform read-only quote/evidence capture.
3. Run validators, approval resolution and compatibility checks.
4. Reacquire and verify the database wall-clock lease fence.
5. Persist the complete prepared command once; a concurrent winner is reused.
6. In a separate bounded transaction, fence and verify the frozen proof, persist
   the evaluation and complete WorkExecution atomically.

Failure recovery runs in a fresh transaction. A stale token cannot persist
preparation, domain results, or error metadata. Expiry after a completion
transaction has acquired the fence does not allow reclamation during that commit.

The frozen command retains everything needed for interpretation. Execution
reproduces assertions, inventories and approval-resolution receipts **offline**;
it never fetches a source, approval, current quote or current withdrawal state.
Database reads verify immutable intent/generation/observation references, not
today's market authorization. Capture-time canonical identities are checked
before first preparation; provider reconciliation is not rerun on historical
execution. Later quote movement, phase expiry, withdrawal, rules updates and
conflicting evidence cannot alter the frozen command.

The essential regression is: approval valid -> preparation commits -> approval
withdrawn -> retry completes the original command -> new capture waits/does not
prepare. Historical evaluation remains distinct from present actionability.

## Scope and next boundary

Use the new module's `register_generation`, `request_intent`, `run_once`,
`load_prepared`, `prepare`, and `complete` for this explicit synthetic v2 path.
The old worker/work readers intentionally still accept only their pinned v1
formats; they are not a version-dispatch router for v2 requests. Existing
qualification reconciliation and lifecycle adapters also remain v1-only. Do not
activate these generations for those adapters or run broad v1 workers over a
mixed v1/v2 queue. Deployment routing/worker-version isolation is deferred.

All new tests use isolated synthetic approvals; database tests run on disposable
PostgreSQL with non-owner worker privileges. The existing JSONB snapshots hold
the full proof, so no schema migration or assertion table is necessary here.

```powershell
$env:CORNER_TEST_DATABASE='1'
$env:CORNER_TEST_CONCURRENCY='1'
python -m unittest discover -s tests -p test_corner_v2_capture.py -v
```
