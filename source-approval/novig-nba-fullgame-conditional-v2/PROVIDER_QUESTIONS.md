# Exact-product clarification drafts — not sent

## To The Odds API support

Subject: Mapping basketball_nba / novig / h2h to governing Novig product and contract

We are reviewing whether Novig NBA head-to-head prices can be used as references
under a conditional decisive-settlement model. Your directory lists `novig` under
US Exchanges. Please help establish the exact source, rather than only the brand.

1. What legal/product entity and regional offering currently supplies
   `basketball_nba`, bookmaker `novig`, market `h2h`? Does it represent an exchange
   event contract, an older sweepstakes product, or another offering?
2. Has that source changed while retaining the same key? Please provide effective
   transition dates and the applicable distinction for historical responses.
3. For one real NBA full-game quote, how do event/market/outcome source IDs and
   links map to Novig's exact contract identifier and governing rules revision?
   Are `includeSids` and `includeLinks` supported for Novig on this endpoint? What
   should we retain if these fields are missing?
4. What does returned decimal price represent: executable ask, bid, last trade,
   midpoint or other derived quote? How are YES/NO sides transformed, and are
   fees, commissions, liquidity, rounding or stale quotes handled explicitly?
5. Can you confirm which Novig settlement product governs this source, including
   any applicable Fair Value Settlement, or identify the party who can confirm it?

We will supply a real sanitized response, request/receipt times and source IDs
once captured; none is attached or invented here. Please identify your response's
effective period, supported API version and relevant documentation revision.

## To Novig support / rules team

Subject: Exact NBA full-game Winner contract and FVS applicability

Your sports help page lists NBA Winner markets. The public contract index we
retained on October 1, 2026 listed WNBA but did not supply an NBA Winner contract.
Your FVS guidance describes valuation rather than return of entry cost. We need
to establish whether that applies to the exact NBA source offering, not assume it.

1. Please provide the complete NBA full-game Winner contract, contract ID/revision,
   effective period, governing rulebook/member agreement and precedence rules.
2. Can you identify or verify the product represented by The Odds API's `novig`
   NBA `h2h` quotes using their source IDs? If not, please say so explicitly.
3. Does FVS govern this exact NBA contract? List each trigger and any exceptions,
   including tied interruption, abandonment, delayed start, postponement,
   cancellation, forfeit and inability to verify an official outcome.
4. For each non-decisive branch, is original stake/entry cost returned, or is a
   valuation paid? Specify reference time, calculation window, price sources,
   fees, payout for both sides, and whether net profit/loss can be non-zero.
5. Confirm overtime inclusion, decisive outcome structure, tie/push treatment,
   completion windows/timezones, market-title overrides and correction/finality.
6. Identify product transitions, their effective dates and which prior terms
   continue to govern previously opened contracts. Which source authenticates
   revisions and notifies users of changes?

Please identify the responding team and cite the controlling retained documents.
An inability to confirm the mapping is useful evidence, not something we will
replace with an inferred match. No trading or account credentials are requested.

## Evidence handling

Do not send secrets or bearer URLs. Preserve each original response and attachments
with provenance, timestamps and digests in authorized storage; shared redactions
are separately identified derivatives. Neither a support reply nor a correct hash
itself grants Corner approval. Review must establish authority and exact scope.
