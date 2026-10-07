# Novig NBA full-game conditional-settlement investigation v1

**Disposition: insufficient evidence; material compatibility concern. No approval.**
This is the first research revision under EV v2, not an executable assertion.

## Candidate scope and evidence

Novig is a fixed reference candidate alongside Pinnacle for the DraftKings
Louisiana NBA full-game two-way moneyline proof. The exact Novig product,
jurisdiction/rules context, current Odds API offering and canonical binding are
unproven. Do not equate an older feed label with a current exchange contract.

`review.json` binds four public responses in `20261001T214305855075Z`, with original
bodies, digests, HTTP/receipt metadata and hashed derivatives. They establish what
these pages published at capture, not which rules govern a particular quote.

## Material adverse evidence

The [settlement help page](https://support.novig.com/en/articles/10336135-how-settlement-works-grading-disputes-and-voided-trades)
directs voids and pushes to fair-value settlement and points to contract-specific
conditions. The separate
[FVS explanation](https://support.novig.com/en/articles/16163706-what-is-fair-value-settlement-fvs)
states that valuation replaces a refund: payout can differ from entry cost.

If these terms govern the candidate NBA quote, treating exceptional settlement as
zero-net-return stake refund would be wrong. Conditional win/loss mathematics does
not establish that these prices express the same conditioning population as the
target. No approved matching conditioning/invalidation contract exists. This
finding is a compatibility warning, **not** proof that an identified NBA wager
actually settled this way or that the current Odds API quote uses this product.

The retained [contract index](https://support.novig.com/en/articles/16083642-contracts)
lists WNBA basketball contracts, but no NBA winner contract was found there. That
is a gap in this retained index, not a claim that no NBA offering exists. WNBA
contracts cannot stand in for NBA rules.

The [product/compliance page](https://support.novig.com/en/articles/15124242-rules-legal-restrictions-compliance)
describes an exchange and links governing documents. This is an operator statement,
not independent regulatory certification or provider-feed product mapping. The
rulebook/member agreement and exact NBA contract are not retained/reviewed here.
Relative page-update labels do not supply the governing effective period.

## Required evidence / questions — not sent

1. Ask The Odds API and Novig to identify the exact product behind the current NBA
   `novig` quotes, including effective dates of any product/rules changes.
2. Obtain the exact NBA full-game winner contract, governing rulebook/member
   agreement, precedence and effective revision. Confirm overtime, ties, interrupted
   games, cancellations, postponement windows, source failure and corrections.
3. Does FVS apply to that contract? Which triggering conditions, valuation basis,
   fees and payout rules govern each side? Do any branches return original stake?
4. How are provider decimal odds derived from contract prices? Preserve applicable
   fees/price semantics and evidence needed to interpret a two-price reference.
5. Compare the complete conditioning and invalidation rules with the other approved
   books. Do not relabel FVS as refund, ignore adverse branches or drop Novig from a
   prepared model to obtain a successful calculation.

If the exact candidate contract proves incompatible, issue a new explicit rejected
review for this engine contract. A switch to BetOnline requires a deliberate new
scope and its own review; no automatic substitution is performed.

No source grant, runtime configuration, phase approval or loader is changed. The
DraftKings v1 rejection is untouched. Future approvals/rejections are new review
revisions; this insufficient-evidence record remains historical.

Offline integrity check:

```powershell
python source-approval/capture_settlement_candidates.py novig-nba-fullgame-conditional-v1 --verify
```

`--capture` is an explicit new public-document capture only, not live market capture
or a runtime loader. Complete applicable evidence and source authenticity are not
proven merely because retained file hashes verify.
