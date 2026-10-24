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
