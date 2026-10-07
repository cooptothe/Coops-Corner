# Provider clarification dispatch — October 2, 2026

Sender verified through Gmail: `edcooper.dev@gmail.com` (Edward Cooper).
This is a new correspondence record; historical dossier reviews and their
original unsent drafts are unchanged.

| Request | Dispatch evidence |
| --- | --- |
| The Odds API / Novig mapping | Gmail returned SENT; message/thread `1a0fc5a5f3eecb6b` |
| Novig contract/FVS | Send permission declined; not sent; no retry attempted |
| Sportradar phase/access | Prepared locally; not attempted after the declined send |

Each `*-request.json` records the exact prepared MIME request. A separate
`*-receipt.json` retains the tool result where an attempt occurred. The preparation
status is historical; use the separate receipt for dispatch status. No Gmail
drafts were created. Gmail SENT confirms submission, not delivery, reading or a
provider's acceptance of the inquiry.

The Odds API message includes the original 9,182-byte response as a JSON attachment
and states accurately that all 44 NBA events had empty bookmaker lists. No API
credential was included. Local paths, database credentials and account secrets
were not sent. The request asks for coverage/product mapping, not a scope change.

No approval, purchase, subscription, production loader or routing change resulted.
Await explicit direction before any further sends. Do not automatically resend a
message whose tool receipt confirms SENT, and do not bypass the declined send.

Contact provenance checked during the investigation:

- The Odds API: https://the-odds-api.com/manage/faqs.html
- Novig support route: https://support.novig.com/en/articles/13835919-managing-your-novig-account-login-profile-settings
- Sportradar general support: https://apidocs.sportradar.com/resources/widgets/docs/tutorials/troubleshooting/support

Support routing does not establish the responder's authority to approve a rules
interpretation; that remains part of the later evidence review.
