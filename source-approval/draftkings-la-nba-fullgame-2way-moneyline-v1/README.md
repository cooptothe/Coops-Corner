# DraftKings Louisiana / NBA full-game two-way moneyline

**Decision: REJECTED for production `no_push_two_way` approval.**

This is an engineering source-admissibility review, not a regulatory certification or a claim about a particular wager's actual settlement. No production authority, policy grant, assertion, or automation is enabled by this dossier.

## Decisive finding

Normal NBA completion requires overtime to resolve a tied fourth period. That does not guarantee a sportsbook always settles on a normally completed game. [NBA Rule 5, section IV](https://official.nba.com/rule-no-5-scoring-and-timing/)

The retained Louisiana basketball rules allow certain late-interrupted games to be treated as concluded using last-play statistics after the applicable completion window. A hypothetical tied score in that branch, combined with the general two-selection tie/push rule, creates a plausible push path. Therefore the required claim that a push is **impossible** is not established. This inference is the reason for rejection; it is not a reported historical incident. [Louisiana basketball rules, Schedule and Format Changes, third paragraph](https://sportsbook.draftkings.com/legal/contentstack-bucket/legal/sport_rules_dke/US-LA-SB_ent/basketball.json), [Louisiana general rules, II(C)(ii)](https://sportsbook.draftkings.com/legal/contentstack-bucket/legal/general_rules_dke/US-LA-SB_ent/generalRules.json)

The conservative review interpretation is `push_capable`, **not an approved production classification**. If the operator intends a different interaction between these clauses, retain authoritative clarification and review a new dossier version. Do not silently disregard the adverse branch.

## Retained authority chain

| Source ID | Role and review locator | Retention result |
| --- | --- | --- |
| `la_statute` | R.S. 27:607(C), operator rules obligations | Substantive official HTML retained; does not establish approval of this particular revision |
| `dk_la_terms` | Louisiana applicability and incorporation of house/sport rules | Substantive HTML retained; displayed terms date is not the house-rules effective date |
| `dk_la_general_json` | Louisiana introduction; rule hierarchy; I(N); II(C), II(D), II(G) | Complete public Louisiana JSON retained |
| `dk_la_market_json` | Two-way moneyline definition | Complete public Louisiana JSON retained |
| `dk_la_basketball_json` | Schedule/Format Changes; General Basketball Settlement Rules | Complete public Louisiana JSON retained |
| `dk_la_sports_index_json` | Basketball navigation identity | Supporting JSON retained; not settlement authority |
| `nba_rule_5` | Section IV overtime | Substantive official HTML retained; not bookmaker rules |

Louisiana's statute requires approved operator rules, while the Louisiana terms incorporate sportsbook rules. This establishes relevant context, not proof that the regulator approved the exact bytes captured here. [Louisiana Legislature](https://legis.la.gov/Legis/Law.aspx?d=1239437), [DraftKings Louisiana terms](https://sportsbook.draftkings.com/legal/la-terms-of-use)

Sources were captured on **2026-09-26 UTC**. Exact URLs, request/receipt times, response metadata, byte counts, and full SHA-256 digests are in:

- [Initial capture manifest](captures/20260926T233755265386Z/manifest.json)
- [Louisiana rules capture manifest](captures/20260926T234325857765Z/manifest.json)

The `.body` files preserve response entity bytes unchanged, not TLS/wire traffic. `.txt` and `.links.json` files are explicitly derived aids. No authentication credentials were sent. Hashes establish local byte integrity, not authenticity signatures or legal approval.

Browser inspection was necessary: the three directly fetched rules pages returned HTTP 200 page shells, not substantive rule text. The rendered Louisiana pages exposed their public `US-LA-SB_ent` JSON assets. Those assets, including the Louisiana text and basketball identity, were retained separately. Shells remain in the dossier as failed substantive captures; they must not substitute for the JSON evidence. Generic search results or a Louisiana footer alone do not establish jurisdiction.

The second capture also retains its exact script and source plan. The first capture records the earlier script digest but does not retain that earlier implementation; its response bytes and derivatives remain independently hash-verifiable. Capture-manifest status is acquisition status; content-review findings live here and in `review.json`, without rewriting capture history.

## Scope and applicability

Candidate scope is DraftKings, US-LA, NBA, full-game, ordinary straight two-selection moneyline, including overtime. Excluded: three-way/regulation-only markets, partial periods, props, spreads/totals, futures, parlays, promotions and cashout. The adverse analysis covers ordinary games and the separately specified postseason completion window.

Provider `h2h` and a canonical Outcome alone cannot prove that a live offering meets this scope. No actual event, bet-slip/title revision, canonical UUID, or jurisdiction-qualified provider offering was bound in this review. Market-title/bet-slip exceptions require additional retained evidence. The existing validator binding lacks an explicit jurisdiction dimension; production applicability must not be inferred from a sportsbook UUID alone.

The rules' own conflict hierarchy was considered, particularly basketball-specific overrides of general settlement provisions. Cancellation/void outcomes remain distinct from tie/push outcomes; neither is silently converted into a loss. The complete retained documents, not just favorable clauses, remain available for review.

## Machine-readable review

- [Review decision](review.json): exact source digests, approval boundary, unresolved applicability and withdrawal requirements.
- [Structured interpretation](settlement-interpretation.json): review-only rule model; **not** a runtime `corner.settlement_rules_evidence/1` document.
- [Adverse cases](adverse-cases.json): hypothetical tests of the proposed classification, not assertions about actual games.

CMS revision/update/publication timestamps and HTTP Last-Modified are retained provenance, not proven legal effective dates. Both legal applicability bounds remain unknown. No generic TTL is substituted for a governing rules period.

Any future approval must bind the complete retained rules bundle, jurisdiction and exact offered scope, an admissible effective period, reviewer authority, and explicit withdrawal semantics. A source change, contradictory rule, missing dependency or unverified applicability suspends positive use pending review; it must not silently keep an older approval alive. No existing approval is withdrawn by this dossier because none was created here.

## Offline verification

From the repository root:

```powershell
python source-approval/draftkings-la-nba-fullgame-2way-moneyline-v1/capture_sources.py --verify
python -m unittest discover -s tests -p test_source_approval_dossier.py -v
```

Verification checks retention integrity and review consistency, **not legal correctness or production approval**. `--capture` performs a new explicit network capture into a new directory; it does not update this decision or approve changed content. There is no polling task.

## Next decision

Do not admit this candidate to EV v1. Obtain retained operator clarification of the tied late-interruption branch, or investigate a different contract. Supporting pushes would require a separate analytical/settlement design, not relabeling this evidence as no-push. Phase authority remains a separate unresolved prerequisite.
