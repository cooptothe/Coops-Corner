# Funded API onboarding — October 20, 2026

The owner supplied a dashboard showing 15M credits, zero used, $249/month,
subscription started October 20, next invoice November 20, and quota reset on
the first at 00:00 UTC. Provider FAQ confirms calendar-month usage resets.
The current usage window is October 1–November 1 UTC; invoice dates are separate.
This does not authorize automatic November ledger rollover.

Run `python -m pipelines.collection_onboarding` on the VPS from /srv/corner/app.
It prompts privately for the key if absent, then performs exactly one fixed
GET https://api.the-odds-api.com/v4/sports request, documented zero-credit.
TLS verification is enabled; redirects/proxies and automatic retries are disabled.
Only quota numbers and a count of active keys are reported. Never print/copy
collection.env, its database password, API key, raw request URLs or exceptions.

It requires private mode-600 configs owned by corneradmin, collector flag 0,
private beta mode, staging refresh cap 0 and no staging key. Installed collector
units must be disabled/inactive. It refuses an existing live ledger or active
approval; those require their own audited reconciliation workflow. It cannot
initialize, resume, publish, start services or modify activation approval.

After verifying the 15M total and zero request cost, it atomically stores the key
in collection.env, preserving writer credentials and collector flag 0. It records
safe evidence under /srv/corner/collection/onboarding/quota-check.json, included
in the coordinated checkpoint along with the existing collection.env coverage.
Run the encrypted backup after setup. A failure is not a pass; preserve private
state and inspect without displaying secrets. No automatic key rotation occurs.

A stored worker key is now expected while the worker is disabled. Old scripts
that required all worker keys to be absent are superseded for this funded standby
phase; staging still must NOT contain a key. Do not run the old reboot baseline
again to manufacture new acceptance: its source/config fingerprints are historic.

Next gates, NOT performed by this helper: bind a dedicated live ledger PAUSED to
the actual calendar-month quota and allocate all prior key usage; implement the
reviewed budget policy; authorize one capped standard-book odds test; verify real
charges, restricted-writer publication, member reads, fresh checkpoint and
isolated recovery. Exchange classification, full-slate throughput and recurring
worker activation remain independent gates. Historical Lab requests stay off.

No odds are fetched and no data is published by onboarding. This first step
cannot be presented as completion of the funded provider/publication smoke.

References:
https://the-odds-api.com/manage/faqs.html
https://the-odds-api.com/liveapi/guides/v4/#get-sports
