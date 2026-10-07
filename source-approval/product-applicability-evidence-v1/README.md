# Applicability Evidence Decision #1 — live candidate capture

Captured October 2, 2026 at 11:40:12 UTC (06:40:12 America/Chicago).
**Insufficient evidence; no approval, routing change or production authority.**

One request for `basketball_nba / h2h`, with exactly `draftkings,pinnacle,novig`,
decimal prices, ISO dates, `includeLinks=true` and `includeSids=true`, returned
HTTP 200. The full 36,779-byte payload contains 44 NBA events.

| Requested book | Complete two-team price sets returned | Exact offering/rules binding |
| --- | ---: | --- |
| DraftKings | 44 | Not established; generic links do not establish Louisiana applicability |
| Pinnacle | 12 | Not established; jurisdiction/product variant and effective rules unknown |
| Novig | 0 | No quote/source identifier to map; cause of absence unknown |

The provider reported one credit used for this request and 498 remaining at
response time. No automatic retry, replacement book or database write occurred.
The API key was loaded in memory and omitted from retained request metadata;
the response was checked for key echoes before retention.

## Concrete shared-event mapping leads

Provider event `26b036ff107f3c658258eaf4a6f26228`: Boston Celtics at Detroit Pistons;
provider `commence_time=2026-10-20T19:00:00Z`. This event label and scheduled time
are not approved phase evidence, a season-type certification or a league ID.

DraftKings at `/0/bookmakers/0/markets/0`:

- Bookmaker-level `sid=34510070`; supplied event link:
  `https://sportsbook.draftkings.com/event/34510070`.
- Celtics decimal 2.05, outcome `sid=0ML85841510_3`.
- Pistons decimal 1.80, outcome `sid=0ML85841510_1`.
- Outcome links also returned; market-level `sid` and `link` are null.
- `last_update=2026-10-02T11:39:30Z` at book and market levels.

Pinnacle at `/0/bookmakers/1/markets/0`:

- Bookmaker-level `sid=1633801637`; supplied event link:
  `https://www.pinnacle.com/en/basketball/nba/boston-celtics-vs-detroit-pistons/1633801637/`.
- Celtics decimal 2.12; Pistons decimal 1.79.
- Market and outcome `sid`/`link` fields are null.
- `last_update=2026-10-02T11:40:03Z` at book and market levels.

These are provider-supplied identifiers. Their appearance in event links is a
mapping lead, not verification of which operator contract they denote. No link
was used to add selections to a bet slip or place a wager. The prices are reported
API values, not a guarantee of execution or net fee treatment.

## Remaining chain

`real API quote -> reported source IDs/links` is now evidenced for DraftKings and
Pinnacle. The next links remain unproven for both:

`exact operator product/market -> jurisdiction/product variant -> effective governing rules`.

For Novig, even the live source-quote link remains absent. Do not infer permanent
unavailability or FVS applicability from this response. Reference scope stays
DraftKings Louisiana target with Pinnacle + Novig candidates.

The retained calendar-day-versus-12-hour non-start difference must be addressed
for these exact products. If both offerings inherit the different conditioning
rules, they fail the current compatibility policy; the engine will not be changed
to conceal that difference. Market-specific overrides require retained proof.

## Integrity and correspondence

Raw body, allowed HTTP/receipt metadata, summary and frozen capture script are in
`captures/20261002T114012500161Z/`. Raw SHA-256:
`5c511830ed84155624d36e8865da4097551e4a709854e858c88119560c4ee034`.
`mapping-summary.json` is a derivative; the complete raw payload is authoritative
for what was received. Prior captures and reviews remain unchanged.

New targeted requests/dispatch receipts are tracked separately under
`provider-correspondence/applicability-2026-10-02/`. The user's new request explicitly
included outreach after previously skipping it. A prepared request is not proof
of sending; only its tool receipt establishes submission. No provider confirmation
or phase entitlement is assumed. Existing comparison dossiers are not expanded.
