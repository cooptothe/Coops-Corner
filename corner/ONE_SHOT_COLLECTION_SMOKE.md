# One-shot funded collection commissioning

The owner has authorized one standard-book main-market request, requesting at
most three credits. Recurring activation, checkout, props, additional markets,
exchange classification and historical collection remain outside this test.
The October ledger and its encrypted isolated recovery have already passed.

`python -m pipelines.collection_smoke` checks the disabled configuration, paused
ledger, writer, restricted reader and in-process API authentication boundary.
It makes no provider requests. It may initialize additive ledger schema only.

`python -m pipelines.collection_smoke --execute-three-credit-smoke --sport icehockey_nhl`
also verifies fresh quota on the free sports endpoint and upcoming events on
the free league-events endpoint, then reserves exactly three credits for one
standard bookmaker group with h2h, spreads and totals. The standard group has
six bookmakers, within the provider's one-per-ten-bookmaker billing group.
The paid league request covers only the next 24 hours during the existing
06:00–22:00 Central collection window. No scheduled cadence is enabled.

The singleton commissioning record and attempt are committed before dispatch.
Dispatch is committed before HTTP; default transport has no retries, redirects
or proxy inheritance. A timeout, invalid response or interrupted dispatch must
be reconciled, never repurchased by deleting the singleton or ledger. A rerun
after settlement retries only retained publication and reader checks. If no
upcoming events exist, no paid request is made. Do not automatically substitute
another league. Provider charges come from response headers: an unexpected
charge above the reservation is recorded and blocks publication, not refunded
or hidden. The requested three-credit ceiling cannot control provider errors.

Successful settlement preserves the collector pause and stores the ordinary
snapshot authority and durable publication outbox. The restricted PostgreSQL
writer publishes the retained response twice; unchanged payload, observation
and link counts demonstrate replay safety. A database error leaves publication
pending; it never buys replacement odds. Feed validation uses the staging
reader with scheduled authority enabled only inside this process. Anonymous
API requests must fail and an isolated test session must succeed. This proves
the in-process authentication boundary, not a real member's public-proxy journey.
Production staging environment and services are not changed.

Fresh eligible quotes are required for a full smoke pass; an empty or expired
capture is explicitly incomplete and cannot authorize a second purchase.
There is no promise that any captured quote yields positive EV. Exchange,
props, full-slate throughput and scheduled-feed activation remain separate gates.

Safe results are retained at `/srv/corner/collection/smoke/result.json`.
All credentials stay in private configuration. Exceptions are reported by step
without their text or credential-bearing HTTP URLs. Take a fresh encrypted
checkpoint after the attempt, including if publication needs recovery. The
previous checkpoint retains the pre-purchase paused state.
