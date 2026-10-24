# Exchange main-market collection repair

The Odds API v4 automatically includes `h2h_lay` with exchange `h2h`
responses. The collector previously rejected that companion as an unexpected
market and quarantined the entire exchange request. Standard odds were
unaffected. Main exchange responses now accept and retain both directions.

Requested markets, request cost, cadence, pools and the 1.5M reserve are unchanged.
Companion snapshots follow the same expiration, withdrawal and rejection rules.
Betfair remains excluded from player props.

Run `python -m pipelines.collection_exchange_repair` for a zero-call preview.
It lists remaining quarantine kinds/sports/codes, without private payloads.
`bash deploy/repair-collection.sh --exchange-lay-fix` performs existing quota
reconciliation first, then releases only verified settled main exchange
`market_mismatch` cases containing the automatic companion. Saved payloads must
pass both snapshot and featured normalization at their original timestamp.
Original quarantine evidence is archived; accounting and cadence are preserved.
Old captures are never republished or marked fresh. Normal scheduled requests
collect fresh odds after restart. Other quarantines remain blocked for review.

Public documentation: https://the-odds-api.com/liveapi/guides/v4/#parameters-2


## Reconciled zero-charge transport failures

Offline recovery now replaces permanent blocks for audited zero-charge unknown
requests with a 5-minute cooldown from recovery time. Repeated failures of the
same scope increase this cooldown up to one hour. Existing old blocks may
already have completed their cooldown. Normal job cadence and all quota gates
still apply; missed ticks are never replayed.

Release requires a settled zero-cost attempt in the current cycle, fresh offline quota reconciliation matching the entire settled ledger, and no
verified response, known HTTP scope error or settlement-phase failure. Historical
per-token audit fields may be absent. Unverified quota-header checks are superseded
by the fresh provider total. Original quarantines are archived in
`transport_quarantine_archive`. Nonzero costs and malformed captured responses
remain quarantined. Zero-charge reconciliation does not assert a response was
valid: no old quote is published; a future scheduled purchase gets new data.


Local transport gate refusals are now distinguished from network uncertainty.
The provider emits `RequestNotSent` only before the HTTP boundary; the runner
settles these attempts at zero and applies a five-minute scope cooldown without
pausing other jobs. Once HTTP begins, failures retain the existing unknown-charge
reconciliation path. Generic exceptions are never treated as proof of no charge.
