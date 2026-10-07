# Novig exact-product mapping: research revision 2

**Disposition: still insufficient evidence. No production settlement approval.**
This is a new research revision under the existing conditional-EV contract, not
an engine version change. The preceding Novig review and DraftKings v1 rejection
remain unchanged. `review.json` binds the previous review's exact digest and four
new retained public sources. It inherits the prior FVS concern without assuming
that those terms govern a specific provider quote.

## What the additional evidence establishes

- The Odds API lists bookmaker key `novig` in `us_ex` and links to Novig's public
  site. This is brand/exchange routing evidence, not a contract-revision binding.
  [Bookmaker directory](https://the-odds-api.com/sports-odds-data/bookmaker-apis.html)
- Novig's sports help page lists NBA Winner markets. Its separate retained
  contract index lists WNBA contracts but no NBA Winner contract. These facts do
  not prove NBA is unavailable; they show that this public index did not supply
  the exact terms we need. [Sports coverage](https://support.novig.com/en/articles/10336189-what-sports-are-available-on-novig),
  [contract index](https://support.novig.com/en/articles/16083642-contracts)
- The Odds API documents `includeLinks` and `includeSids` for links/source IDs
  **when available**. A retained response using them could help identify an
  offering, but neither parameter guarantees a contract ID or governing-rule link.
  [API documentation](https://the-odds-api.com/liveapi/guides/v4/)

## What remains unproven

There is no current subscribed NBA response, source-market-to-contract mapping,
exact NBA Winner contract, governing effective period, fee/price conversion
confirmation, or provider clarification in this review. Consequently, whether FVS
applies to the routed NBA quote is still unknown. The public FVS concern cannot be
discarded, and it cannot be promoted into a proven incident or exact-product fact.

The public search and retained pages are bounded research, not proof that no such
contract or mapping exists elsewhere. An exchange/brand link is not authority to
join every historical and current product under the same rules.

## Next external action

Use `PROVIDER_QUESTIONS.md` for two separate requests: The Odds API identifies its
source product and IDs; Novig identifies the governing contract and settlement
economics. Both drafts are **unsent**. Preserve responses as new evidence with
sender/case provenance, receipt times, original bytes and digests. Credentials and
private entitlement details belong in controlled storage, not shared artifacts.

Once a bounded live odds capture is authorized, the candidate request is:

```text
GET /v4/sports/basketball_nba/odds/
bookmakers=novig
markets=h2h
oddsFormat=decimal
dateFormat=iso
includeLinks=true
includeSids=true
```

This is a capture specification only: **not executed**. Supply authentication
privately; never retain the raw credential-bearing request URL. Preserve response
bytes, receipt/provider times, event/book/market/outcome identifiers, source IDs,
links and missing fields. A sanitized metadata record must disclose redactions.
Inspect links for tokens before sharing. No automatic polling or quota use is
authorized by this document. An absent market is missing evidence, not permission
to substitute a different book. Catalog availability does not prove subscription
or event-level availability. Current source binding does not establish historical
binding across a product transition.

Only after the exact scope is proven can the reviewer decide FVS applicability.
If a non-zero-return FVS branch governs, the candidate cannot be admitted under
the current approved-refund assumptions/compatibility contract. Do not expand the
engine or automatically select BetOnline. No approvals presently exist.

## Verification

```powershell
python source-approval/capture_settlement_candidates.py novig-nba-fullgame-conditional-v2 --verify
python -m unittest discover -s tests -p '*dossier*.py' -v
```

These are offline byte-integrity/review-bookkeeping checks, not source approval.
The shared one-shot documentation tool now accepts this additional dossier; its
old capture scripts/plans remain frozen. No `corner` source, migration, runtime
grant, policy configuration or production authorization was changed.
