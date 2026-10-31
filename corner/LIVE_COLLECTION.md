# Guarded live worker candidate — October 16

Based on 99faef7. Source patch only: no key, credential, service installation,
approval file, live ledger, feed-source flag or staging configuration is changed.
Local manual fetching and the deployed manual-fetch denial remain unchanged.

## Implemented

`pipelines.collection_live` connects the existing serial Runner, guarded Provider,
durable governor and MainPublisher. Inventory response costs are recorded before
discovery continues. Odds publication follows successful quota reconciliation.
All provider calls remain prohibited before October 19 Central and outside
06:00–22:00 Central. Each request checks explicit activation approval, current
Git commit, reviewed book grouping, pause controls and a live worker lease.
Shutdown intent prevents the next provider request after an in-progress call.

`corner.collection_quota.LiveGovernor` requires a one-time explicit cycle/key
binding. The key is represented by SHA256 identity, never written to its ledger.
All preexisting provider usage must be explicitly allocated to the reviewed
main/props/metadata pools. Claims and status include those offsets. Pool limits
remain 8M/5M/0.5M with the separate 1.5M reserve protected.

Every response must have numeric used, remaining and last-charge headers and
used+remaining must equal the purchased 15M. Used must advance exactly by that
response's charge. Drift or ambiguous evidence pauses, never rebases silently.
Metadata has a durable permit before dispatch: zero cost settles it, unexpected
cost is accounted to metadata and pauses, uncertainty holds a minimum one-credit
reservation and blocks ALL further dispatch until actual cost is established.
Unknown odds retain their full reservation. An expired inventory/odds owner
cannot settle or publish; conservative takeover requires operator recovery.

Header semantics checked against official documentation October 16:
https://the-odds-api.com/liveapi/guides/v4/
Sports/events discovery is documented zero-cost; any observed exception is a
stop condition, not permission to continue buying odds.

## Explicit activation gates

The root-owned, non-symlink approval file is fixed at
`/etc/corner/collection-activation.json` with a root-controlled parent. All nine
evidence fields from the prepared worker bundle must be populated and approved
must be true. It must match the full deployed commit and current billing dates.
At startup its verified quota must be under five minutes old and match the
bound ledger. A changed release, stale approval or mismatch prevents startup.
This intentionally requires operator reconciliation/renewed approval after a
restart when recorded quota has changed; automatic systemd retries cannot bypass
the gate. Improved unattended restart behavior is a later acceptance decision.

Worker configuration uses only CORNER_COLLECTION_DB_* writer credentials, never
DB_CONFIG or postgres/owner fallbacks. Database identity, elevated role attributes,
owner membership, schema CREATE, ledger DELETE and active quote-state seed are
checked before the loop. Provisioned grants must still be independently reviewed;
these startup checks are not a complete privilege audit.

The command `--check` validates activation evidence and state-file presence only;
it performs NO HTTP, DB writes or writer connection. Its success is not a complete
runtime acceptance. Actual startup checks ledger binding and the restricted
writer as well. Current disabled staging must return nonzero/blocked.

## Offline verification on the VPS after source deployment

Keep all current staging configuration unchanged. Do not install the draft unit.

```bash
cd /srv/corner/app
.venv-api/bin/python -m unittest tests.test_collection_live tests.test_collection_runner tests.test_collection_adapters tests.test_collection_worker tests.test_scheduled_only tests.test_refresh_service tests.test_props_refresh tests.test_beta_access tests.test_accounts tests.test_database_catalog
.venv-api/bin/python -m pipelines.collection_live --check
```

The check must report blocked with worker_entered_loop false and exit 1. That is
the expected disabled result. Tests use fake HTTP and disposable SQLite only.
The new tests cover quota drift, baseline allocations, protected reserve, missing
headers, discovery charge/timeout/crash, stale quota, key/cycle changes, shutdown,
audited recovery and root-controlled commit-specific approval.

## Operator commands — prepared, NOT an instruction to activate today

`pipelines.collection_admin` does no HTTP and never starts a worker. It accepts
only an explicitly named collection-live.sqlite3, refusing account/simulation
filenames. status is read-only; missing state is never implicitly created.

- init --state PATH --request PRIVATE_JSON: creates a NEW ledger, prompts privately
  for provider key identity and requires explicit current provider cycle and
  quota. It cannot overwrite/rebind/reset an existing ledger. Initial state is
  paused. A failed initialization may leave a partial setup ledger; do not delete
  it automatically or substitute it for an existing accounting history.
- pause --state PATH --evidence REFERENCE: durable audited pause; stop service
  first for the immediate kill switch. An already dispatched call can be charged.
- recover-lease --state PATH --evidence REFERENCE: refuses an active lease;
  conservatively converts expired inflight requests to unknown and stays paused.
- reconcile --state PATH --request PRIVATE_JSON: offline only, refuses inflight
  or active workers, settles only explicitly identified unknown requests against
  externally verified costs, allocates external usage explicitly, and requires
  exact equality of provider used and total ledger usage. Existing external
  offsets cannot decrease. All unresolved requests must be addressed together.
  It records an audit and remains paused; it NEVER reconstructs successful odds.
- resume --state PATH --evidence REFERENCE: requires a just-completed audited
  reconciliation, no uncertain requests, fresh quota and intact pool/reserve
  limits. It clears only blocked job/pause state; no missed-tick replay and no
  provider calls. Deployment approval is still independently required to run.

Private init JSON fields: cycle_id, cycle_start, cycle_end, provider_used,
provider_remaining, offsets {main,props,metadata}, evidence. Reconcile JSON:
provider_used, provider_remaining, offsets, settlements {odds_token: actual_cost},
inventory {metadata_token: actual_cost}, evidence. Use UTC timestamps with offsets.
Never put keys/passwords or raw provider responses in evidence or these JSONs.
Unknown cost is NOT zero because a response is absent. Save provider/operator
evidence before entering verified settlements; the tool cannot independently
prove operator-supplied values. Pool overrun or reset/mismatched cycle requires
separate review; there is no automatic new-month rollover command.

## Remaining funded/deployment gates

No real provider request, funded quota, actual dedicated staging-writer login,
live unit restart, full-slate cadence/throughput, automatic encrypted off-server
backup/restore, or root-owned activation installation has been verified by these
tests. Those gates remain open. Source integration is not live acceptance.
Recorded main/props integration already passed in isolated VPS data stores.
The previous worker-preparation backup checklist still applies: include the new
quota bindings, inventory permits, offsets and immutable audit history in the
SQLite online backup and coordinated PostgreSQL/retained-capture checkpoint.
Restore must remain paused until CURRENT provider usage is reconciled; an old
backup must never refund costs incurred since its checkpoint.
