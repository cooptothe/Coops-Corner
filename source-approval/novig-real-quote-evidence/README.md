# Live Novig NBA mapping evidence — October 2, 2026

**Result: real response retained, but no Novig quote obtained. No approval.**

At 2026-10-02T11:12:08Z (06:12:08 America/Chicago), one authenticated request to
The Odds API's NBA odds endpoint returned HTTP 200 and 44 event objects. Every
`bookmakers` array was empty. There are consequently no Novig market/outcome
objects, source IDs, prices or links to map in this response. Event IDs and
scheduled times are retained; they are not positive phase authority.

Request scope: `basketball_nba`, `bookmakers=novig`, `markets=h2h`, decimal prices,
ISO dates, `includeLinks=true`, `includeSids=true`. There were no redirects,
automatic retries, alternate books or database writes. The provider reported one
quota credit consumed and 499 remaining at response time; this is not a claim
about the current account balance.

## Retained bundle

[Capture directory](captures/20261002T111208373869Z/):

- `response.body`: full, unmodified 9,182-byte HTTP entity body.
- `manifest.json`: request scope without API key, receipt times, allowed HTTP
  metadata, quota headers, body/summary/script SHA-256 digests.
- `mapping-summary.json`: derivative reporting 44 events and zero Novig markets.
- `capture_script.py`: frozen research-only capture implementation.

Body SHA-256:
`0b15f91aee95bf156407dd51f2f68dd9b7ed26a2f67f3972fa514d6ad07263ef`.

The credential remained in memory. Exception URLs and credential-bearing request
metadata were not retained. Selected response headers and body were checked for
the key before writing. Hashes prove retained-byte consistency, not an operator
signature or product applicability.

## Interpretation and next action

This proves only the contents returned for this request at this time. It does
not establish whether the absence reflects market availability, coverage,
entitlement, provider behavior or another cause. It does not reject Novig,
establish FVS applicability, or authorize substituting another reference.

The existing Novig v1/v2 reviews remain unchanged. Status remains **insufficient
evidence / material compatibility concern**. Use the separate
[clarification supplement](CLARIFICATION_SUPPLEMENT.md) with the existing v2
questions. No provider message has been sent. The lack of a connected sending
account is an independent blocker, not a provider non-response.

Do not automatically poll or repeat the paid API request. A later authorized
capture must create a new timestamped bundle, not replace this one.
