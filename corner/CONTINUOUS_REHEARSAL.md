# Continuous collector rehearsal — October 16

Based on 2fb73fc. Adds a persistent, serial runner and offline command; does not
change accounts, frontend, service units, credentials, or local manual fetching.
No live CLI, automatic startup, API key, or provider purchase is enabled.

## Behavior

- Lease acquisition precedes discovery, planning and dispatch. Clock checks occur
  between requests. One request is outstanding at a time; at most four successful
  jobs per tick, with a persisted round-robin cursor across restarts.
- Inventory is stored transactionally. Refresh is due after five minutes; a
  failed refresh blocks purchases immediately, with 30/60/120/240/480/900-second
  capped retry delays. Only complete, validated discoveries are saved. Inventory
  older than ten minutes is refused; inventory capture cannot be over 60s old or
  in the future on receipt.
- Existing governor cadence and conservative credit reservations remain in use.
  Missing charges, timeouts and uncertain results pause further collection.
  An expired worker cannot settle or publish; takeover holds inflight costs and
  pauses for operator review. There is no automatic refund or resume command.
- An optional injected writer drains one durable outbox item per tick before new
  purchases. Backlog or a writer error blocks purchases. Rehearsal supplies no
  writer, and its snapshots cannot become member feed data.
- After Hours performs no discovery or odds requests. An injected writer can
  drain previously captured data; feed readers still enforce source expiry.

## VPS rehearsal after committing and pulling this patch

Use the existing simulation state, never the accounts database:

```bash
cd /srv/corner/app
.venv-api/bin/python -m unittest tests.test_collection_runner tests.test_collection_adapters tests.test_collection_worker tests.test_scheduled_only tests.test_refresh_service tests.test_props_refresh tests.test_beta_access tests.test_accounts tests.test_database_catalog
.venv-api/bin/python -m pipelines.collection_runner --manifest fixtures/collection/simulation.json --state /srv/corner/config/collection-simulation.sqlite3 --once
.venv-api/bin/python -m pipelines.collection_runner --manifest fixtures/collection/simulation.json --state /srv/corner/config/collection-simulation.sqlite3
```

The second command runs one tick; the third prints one result every five seconds.
Stop the loop with Ctrl+C, restart it, and inspect status:

```bash
.venv-api/bin/python -m pipelines.collection_runner --state /srv/corner/config/collection-simulation.sqlite3 --status
```

Every tick identifies mode simulation, provider_calls 0, feed_publication false.
Counts vary with clock and stored cadence; do not expect the fixed 40-job count
from the older fixed-time rehearsal. The fixture's October 16 fake events expire
normally, so later rehearsals can have main jobs only. No real event inventory
or actual provider quota is represented by these simulated figures.

## Remaining gates

This runner is prepared for adapter injection, but the shipped CLI is offline
only. Live wiring still requires separately reviewed writer credentials, real
PostgreSQL integration, supervised service setup, explicit billing/quota
synchronization, discovery charge reconciliation, authenticated status and
pause/reconciliation controls, and bounded real-provider acceptance on/after
October 19. Serial throughput must be measured against the full slate before
claiming 20/60-second coverage. Do not configure CORNER_COLLECTION_DB or add a
provider key on the strength of rehearsal success.
