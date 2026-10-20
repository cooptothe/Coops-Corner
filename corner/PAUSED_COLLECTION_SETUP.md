# First funded ledger binding — October 20, 2026

Owner supplied successful quota onboarding: 15M total, zero used/charged,
next quota reset November 1 at 00:00 UTC; next invoice November 20. The key is
stored only in the private disabled worker configuration. No live ledger existed.

`python -m pipelines.collection_setup` is the next standalone VPS action.
It does NOT run the paid smoke or recurring collector. It performs:

1. The existing disabled/no-approved-activation preflight, refusing any existing
   live ledger (including partial state). Private key is read from collection.env.
2. Dedicated writer authentication/role checks through SELECTs and rollback only.
   No writer/owner fallback and no PostgreSQL odds publication.
3. One documented zero-credit sports-list request for fresh 15M/zero-used evidence.
   Nonzero prior usage, stale proof or invoice-anniversary quota dates are refused.
4. Exclusive creation of mode-600 collection-live.sqlite3, monthly quota binding
   October 1–November 1 UTC, hashed key identity and a paused control record.
5. Versioned budget policy: main 7.9M, props 5M, operations 500K, Lab history 100K,
   protected reserve 1.5M; total 15M. History remains unavailable to ordinary jobs.
6. Private setup evidence in /srv/corner/collection/onboarding/paused-setup.json.
   Existing coordinated backup copies the complete ledger and retained directory,
   so the new policy table and setup evidence are included in the next checkpoint.

`python -m pipelines.collection_setup --status` is read-only and needs no network.
It reports paused state, cycle dates and policy, without credentials or key hash.
If setup fails, preserve the ledger; do NOT delete it or rerun an init to hide the
failure. Existing cycles without the exact versioned policy cannot authorize
provider calls. There is no automatic migration, budget transfer or month reset.

After successful setup, create a fresh encrypted checkpoint and confirm backup
service success. Isolated restoration must verify the complete ledger, policy,
paused controls and pending publications when present. Historical Lab adapters
and the prior-release rollback gate remain separate unfinished work.

The next PAID smoke must be a separately authorized, durable one-shot scope:
maximum three credits total, one standard-book h2h/spreads/totals request for one
reviewed supported league, no exchange fast-group approval inferred. Reserve
before dispatch, settle provider headers exactly, retain raw data and publish
idempotently with the restricted writer. Timeout/crash must block another paid
request until reconciled; publication replay must not refetch. An empty payload
is not proof of feed freshness. Readback must use the restricted reader and
confirm exact published event/quote identity. One standard group may not provide
enough independent references for EV rows: no positive bets may be invented.

That one-shot smoke is NOT implemented/authorized by the paused initializer.
It must leave the ledger paused and keep CORNER_COLLECTION_ENABLED=0 and all
recurring services disabled. Recurring activation still requires all root-owned
commit-specific evidence, source classification and full-slate throughput.
