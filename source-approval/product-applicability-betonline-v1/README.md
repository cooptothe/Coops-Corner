# Revised candidate scope: DraftKings LA + Pinnacle + BetOnline

The user explicitly authorized replacing Novig with BetOnline for this approval
attempt on October 2, 2026. `scope-decision.json` records that research decision.
Novig is deferred, not rejected. Historical dossiers and frozen work are unchanged.
This is not activation of a runtime channel generation or a settlement approval.

## One live capture, no substitutions

At 2026-10-02T12:03:12Z (07:03:12 America/Chicago), one request to The Odds API
NBA odds endpoint specified `draftkings,pinnacle,betonlineag`, `h2h`, decimal odds,
ISO timestamps, `includeSids=true` and `includeLinks=true`.

| Book | Complete two-team price sets returned |
| --- | ---: |
| DraftKings | 44 |
| Pinnacle | 12 |
| BetOnline (`betonlineag`) | 0 |

HTTP 200 returned 44 NBA events and 36,779 bytes. The provider reported one quota
credit used and 497 remaining at that response time. The raw response, metadata,
summary and frozen script are retained in `captures/20261002T120312455406Z/`.
Raw SHA-256:
`07ac1832c51d1eedc4032cf38dd7f47270872b7f3711fd485b71b79acc4bc663`.

There is no BetOnline source event/market/outcome object in this response to bind
to an operator offering. The cause is unknown: this observation does not prove
subscription exclusion, permanent lack of NBA coverage, or contract incompatibility.
DraftKings/Pinnacle availability does not satisfy the requirement for two complete
reference books. No repeated odds polling or alternate book was used.

## Separate settlement dossier

`../betonline-nba-fullgame-conditional-v1/` records the public-document investigation.
The provider directory confirms the key and brand link, not the economic contract.
Raw operator rules could not yet be retained: the first attempt failed certificate
chain verification; a second attempt with the installed certifi CA bundle and both
certificate/hostname verification enabled returned HTTP 403 for both rule pages.
The errors/denial bodies are retained, not classified as substantive rules.

Public web-reader previews supplied preliminary rule-reading leads, but are not a
substitute for the missing complete retained applicable rules bundle. No emails
were sent, no login or bet slip was used, and no access restriction was bypassed.

## Next evidence needed (no further implementation)

1. A real `betonlineag` NBA full-game quote when available, preserving source IDs
   and links; a later capture must remain a separate record.
2. A permitted export/download of governing operator rules and offering-specific
   overrides, with provenance and effective revision. A user-supplied authentic
   source bundle can be reviewed without provider emailing.
3. Evidence connecting that quote to the product/rules variant; the provider's
   region label is not the wagering jurisdiction.
4. A compatibility decision covering all three books. The existing DraftKings–
   Pinnacle non-start-window concern remains; replacing Novig does not resolve it.
5. Independent phase approval before any production-authorized opportunity.

The current research disposition remains **insufficient evidence**. No production
loader, runtime routing, engine semantics, grants or approvals were changed.
