# October 2 live-capture clarification supplement — NOT SENT

Use with the two separate drafts in
`../novig-nba-fullgame-conditional-v2/PROVIDER_QUESTIONS.md`.
Do not send an API key, the credential-bearing request URL, or account secrets.

## The Odds API

Recipient: `team@the-odds-api.com`, published in the provider's
[FAQ](https://the-odds-api.com/manage/faqs.html), checked October 2, 2026.

Subject: Novig NBA h2h availability and exact source-product mapping

We made one authenticated NBA request at 2026-10-02T11:12:08Z:

```text
GET https://api.the-odds-api.com/v4/sports/basketball_nba/odds/
bookmakers=novig&markets=h2h&oddsFormat=decimal&dateFormat=iso
&includeLinks=true&includeSids=true
[authentication deliberately omitted]
```

The HTTP 200 response contains 44 NBA events, all with empty `bookmakers` arrays.
For example, event `26b036ff107f3c658258eaf4a6f26228` is labeled Boston Celtics at
Detroit Pistons with `commence_time=2026-10-20T19:00:00Z`. This is an API event ID,
not a Novig source identifier. We do not infer that Novig has no NBA product.

Can you identify why this request returned no Novig markets and whether this
subscription/endpoint is entitled to the relevant NBA h2h feed? What availability
window should we expect, and are there documented preseason/regular-season or
product-transition differences? We will not infer the cause from empty arrays.

Once quotes are available, please identify how source IDs/links map to the exact
Novig offering and controlling contract. Please also answer the five source,
price-semantics and FVS-mapping questions in the accompanying original draft.
The original draft's sentence saying no real response is available should be
replaced with: a real response is retained, but no Novig quote was present.

Available attachments, not yet sent: `response.body`, `manifest.json`,
`mapping-summary.json` from capture `20261002T111208373869Z`.
The raw-body SHA-256 is
`0b15f91aee95bf156407dd51f2f68dd9b7ed26a2f67f3972fa514d6ad07263ef`.

## Novig

Contact candidate: `support@novig.co`, published in Novig's
[account help page](https://support.novig.com/en/articles/13835919-managing-your-novig-account-login-profile-settings).
That is a support route, not proof the recipient can authoritatively interpret
rules. Request referral to the team responsible for the exact NBA product.

Subject: NBA full-game Winner contract, source mapping and FVS applicability

Please route the accompanying six-question rules request to the appropriate
product/rules team. We are investigating The Odds API's `novig` / `basketball_nba`
/ `h2h` source. Our October 2 request returned NBA events but no Novig prices,
so we cannot yet provide a concrete Novig contract/source ID. We do not claim
this establishes your product's unavailability or the API's governing terms.

Can you supply the current NBA full-game Winner contract and identify whether
and how that product is distributed through The Odds API? In particular, we need
the exact rules revision, effective scope, whether FVS applies, and net economic
treatment of each non-decisive outcome, including valuation versus stake return.
If exact feed mapping must come from The Odds API first, please say so explicitly.

Keep any reply/attachments as new evidence. No support reply automatically grants
approval; exact applicability and completeness still need separate review.
