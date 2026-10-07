# Sportradar NBA game phase: investigation v1

**Review disposition: insufficient evidence. No production approval.**

This dossier implements Production Phase Authority Decision #1 as research only.
It is not a validator assertion, executable policy, production loader, or source
grant. The engineering reviewer has no delegated production approval authority.
The requested assertion is `supported_pregame` for an exactly mapped NBA Event.
An acceptable provider verification-time/latency contract has not been established;
the admissible production phase remains unknown. No runtime assertion was emitted.

## Candidate scope

- Phase candidate: Sportradar NBA game-level REST feed; v8 play-by-play is the
  concrete documented endpoint investigated, not yet a selected subscribed product.
- Market proof context: DraftKings Louisiana, NBA full-game two-way moneyline,
  conditional decisive-settlement EV, fixed references Pinnacle and Novig.
- BetOnline is outside this attempt; substitution requires a new explicit scope.
- NBA season type and coverage eligibility remain to be approved; preseason must
  not silently stand in for regular-season coverage.
- No actual canonical Event, provider crosswalk or live book availability is proven.
- Settlement approval remains separate for all three books. The rejected
  `draftkings-la-nba-fullgame-2way-moneyline-v1` dossier is unchanged.
- SportsDataIO is a fallback candidate, not a supporting authority in this dossier.

## Evidence retained

`review.json` binds four exact public-document responses from capture
`20261001T212645424674Z`. The manifest retains response bytes and SHA-256,
credential-free URLs, request/receipt timestamps, HTTP metadata and hashed readable
derivatives. Raw bodies are authoritative for what was retrieved; derived text is
only a reading aid. Hashes establish integrity, not completeness or approval.

| Evidence class | Current evidence | Missing |
| --- | --- | --- |
| Published semantics | Workflow, REST cache documentation, push limitations | Provider clarification of positive verification and failure behavior |
| Access/applicability | General trial/production description | Actual NBA entitlement, exact endpoint/version, allowed retention/use, applicable guarantees |
| Real transitions | None | Several real games, complete acquisition windows and trusted event mapping |
| Adverse cases | Documented cases and investigation checklist | Real incidents/observations or retained provider answers; no fabricated incidents |

### Published findings, not approval

The workflow associates pregame/preload with `scheduled`/`created` and moves to
`inprogress` after jump ball. Game and schedule feeds may disagree temporarily.
`delayed` can apply before or during play. Postponement creates a replacement ID
without an API link to the original. Preseason coverage can differ.
[Status workflow](https://developer.sportradar.com/basketball/docs/nba-ig-game-status-workflow)

The candidate REST endpoint is
`/nba/{access_level}/v8/{language_code}/games/{game_id}/pbp.{format}`.
Its documented cache interval is 60 seconds while scheduled and three seconds in
progress. Neither establishes a maximum jump-ball recognition delay or a
positive-verification timestamp; `created` cache behavior needs clarification.
[Play-by-play reference](https://developer.sportradar.com/basketball/reference/nba-play-by-play)

General account documentation describes a 30-day trial with real-world data,
lower quotas and exceptions to equivalence. This does not establish our access,
NBA-specific equivalence, entitlement or permission to retain/use data.
[Account documentation](https://developer.sportradar.com/getting-started/docs/your-account)

Push documentation distinguishes event/statistics delivery from status updates.
Transport activity must not be treated as a positive phase verification heartbeat.
[Push guide](https://developer.sportradar.com/basketball/docs/nba-ig-push)

The captured documentation site's HTTP caching headers describe the documentation
site, **not the game API**. None is a runtime phase TTL. Successful examples,
HTTP Date, unchanged ETag, fresh receipt time, or future start time cannot substitute
for a defensible provider verification contract.

## Next gate

1. User obtains NBA access and retains package/entitlement/use confirmation without
   putting credentials into the dossier. No purchase or account creation performed.
2. Send the draft in `PROVIDER_QUESTIONS.md` through an authorized account/contact;
   retain the reply with provenance. It has not been sent.
3. Approve a bounded, quota-aware research acquisition plan using
   `CAPTURE_PLAN.md`; only then collect real transition evidence. No live collector
   or polling job is implemented here.
4. A designated reviewer issues a new explicit review revision considering all
   adverse evidence. Do not overwrite this insufficient-evidence review. If fresh
   verification cannot be established, no positive authorization is available.
5. Only after source approval, design a separately versioned authenticated loader.

Approval must bind source/product/version, permitted classifications, canonical
identity mapping, completeness universe, source/receipt freshness semantics,
coverage/failure rules, effective interval, reviewer identity and withdrawal rules.
Source change, lost entitlement, contradictory evidence or unprovable freshness
must prevent new positive captures without rewriting past frozen commands.

## Offline verification / optional new documentation capture

```powershell
python source-approval/sportradar-nba-game-phase-v1/capture_sources.py --verify
python -m unittest discover -s tests -p test_sportradar_phase_dossier.py -v
```

`--capture` is a separate, explicit one-shot retrieval of only the four public
documentation URLs. It creates a new directory, never updates review bindings,
uses no API key, and grants no approval. It reuses the existing retention helper
read-only and retains both implementations. Tests prove dossier integrity and
fail-closed bookkeeping, not provider reliability or production readiness.
