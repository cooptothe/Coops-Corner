# Scheduled collection adapters - prepared October 16

Based on deployed commit 1ff6a9c. This patch does not enable live collection,
configure a writer credential, purchase credits, or change the VPS configuration.
The current simulation worker remains offline. Local non-beta manual fetching
remains unchanged.

## Added and tested

- Provider transport defaults disabled, requires an explicit key/authorization,
  refuses dates before October 19 Central and all After Hours requests, and
  requires an inflight credit reservation plus the current worker lease.
- A reservation permits only one dispatch. Expired/stale reservations, started
  events and paused collection cannot dispatch. Actual dispatch timing updates
  the cadence floor. Exchange requests additionally require explicit cadence/
  classification verification. There is no implicit fallback to an all-book call.
- Requests use only the fixed official HTTPS host, bounded validated path IDs,
  TLS verification, no proxy environment, no redirects or automatic retries,
  connection/read deadlines and response-size checks. Errors suppress URL/key
  details. Event/market/outcome native IDs and links are requested.
- Discovery uses documented zero-credit sports and events endpoints. It expands
  actual active ATP/WTA tournament keys and includes uncapped configured events
  within 24 hours. The entire inventory must succeed; nonzero/missing last-charge
  headers stop discovery. Durable discovery caching/accounting is a remaining gate.
- Main-line publication is a durable outbox appended atomically with successful
  snapshot/accounting commit. Publishing does not call the provider. Failed DB
  publication remains pending. Retained manifests/bodies use atomic writes and
  stable hashes/timestamps so existing canonical ingest can recognize a replay.
- MainPublisher requires a separately supplied writer connection factory. It does
  not change the API reader credentials or create DB roles at runtime. Actual
  PostgreSQL publication with that writer still needs disposable-DB validation.
- Props can be read directly from a shared transactional snapshot database,
  preserving each book group's timestamp and other events without a JSON writer.
  Simulation stores are refused as member feed sources.
- Main reader optionally checks canonical observations against current scheduler
  book/market/event scopes. It keeps both groups, suppresses withdrawn scopes and
  old observation versions, and enforces source age rather than only receipt age.
- Scheduled reads activate only with BOTH CORNER_PRIVATE_BETA=1 and an explicitly
  configured CORNER_COLLECTION_DB. Without that path, current staging remains on
  its existing source. No path or flag is set by applying this source patch.
- In scheduled-source mode catalog TTL is 15s and rebuild failures fail closed.
  Beta browsers read retained snapshots after a 15s delay when visible and not
  already loading. Props also reload retained data. These reads buy no odds.
  Local accounts without beta roles do not start this polling workflow.

## Validation

124 backend tests passed: adapters, scope readers, scheduler, manual-fetch denial,
main/props refresh, beta access, accounts and database-catalog regressions.
141 frontend tests and TypeScript passed. Network transport tests use fake HTTP;
publication tests use a fake writer callback plus real disposable SQLite. The
existing simulated DB-outage test deliberately logs failures while passing.
Existing Starlette deprecation and test connection ResourceWarnings remain.
No live provider call, funded transfer, real PostgreSQL writer integration, VPS
production build or browser poll acceptance is claimed by these local results.

## Deployment order - keep the existing private staging configuration

1. Apply/review/commit/push this patch from the authoritative Windows checkout.
2. Stop the three staging services, preserve the generated next-env file, pull
   the reviewed commit, run backend tests and frontend checks/build, restart.
3. Do NOT add an API key or CORNER_COLLECTION_DB yet. No worker live flag or
   service is introduced by this patch. Existing private account access persists.
4. Run adapter tests on the VPS; they use fake HTTP and disposable files.
5. Next prepare the continuous worker, durable inventory/backoff and status/pause/
   reconciliation controls. Configure a dedicated writer with reviewed minimal
   privileges, including quote_links; never reuse postgres or corner_owner.
6. Before activating scheduled main reads, grant the API login SELECT on
   corner.event_provider_identities. The new conditional provenance join needs
   this public provider-ID mapping. No raw provider_payloads grant is required.
7. Verify a complete recorded capture -> PostgreSQL -> main feed and transactional
   props -> feed path in an isolated DB. Test missing/withdrawn markets, two-group
   timestamps, replay, cancellations/reschedules, freshness and reader outages.
8. Configure a separate live collection DB only after verification; never point
   member reads at collection-simulation.sqlite3. Add it to backup/restore coverage.
9. On/after October 19, confirm the actual provider billing period, quota and
   exchange grouping; provision the funded key and explicit authorization only
   after passing the gates. Keep the 15M pools and 1.5M reserve protected.

## Remaining release work

The deployed site still has no automatic live worker after this patch. Required:
continuous scheduling with bounded concurrency and current clocks, persisted
inventory and per-sport backoff, billing/quota synchronization and operator
reconciliation, authenticated collection status and kill switches, supervised
worker recovery, PostgreSQL least-privilege integration and browser acceptance.
Then measure actual slate costs, disk/retention and ten-member load. Payment/
receipt lifecycle, scheduled encrypted off-server backups, protected public HTTPS
and final launch evidence also remain open. October 20 is conditional on passing.

Provider documentation checked October 16:
https://the-odds-api.com/liveapi/guides/v4/
https://the-odds-api.com/sports-odds-data/update-intervals.html
