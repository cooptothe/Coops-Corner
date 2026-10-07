# Pinnacle NBA full-game conditional-settlement investigation v1

**Disposition: insufficient evidence; no production approval.** This is the first
research revision under EV v2 semantics, not an executable settlement assertion.

## Scope and retained evidence

Reference candidate: Pinnacle, NBA full-game two-way moneyline, pregame quotation.
The target context is DraftKings Louisiana with Pinnacle + Novig references.
Louisiana is the target jurisdiction, **not an inferred Pinnacle rules jurisdiction**.
No current Odds API response, canonical quote binding or provider product mapping
has been retained in this dossier. The `pinnacle` name alone does not prove which
regional product, rules revision or title-specific exceptions govern the quote.

`review.json` binds two public responses and their digests in capture
`20261001T214305078414Z`: [betting rules](https://www.pinnacle.com/en/future/betting-rules/)
and [linked Anjouan terms](https://www.pinnacle.com/en/future/termsandconditions/anjouan).
Raw bodies, HTTP/receipt metadata, text derivatives and frozen capture code are
retained. Hashes verify byte integrity; provenance, applicability and approval
remain distinct. No account was accessed or wager placed.

## Preliminary reading, not a normalized contract

The rules include overtime for game-period basketball bets and a 43-minute NBA
threshold. General provisions cover 12-hour non-start and 30-hour non-completion
windows, subject to exceptions. A two-way draw is void; the glossary describes
void as refund. Market rules outrank sport rules, which outrank general rules.
Venue, forfeit, format, error and result-correction provisions also need review.

This does **not** resolve how the basketball threshold interacts with the general
completion window at exactly 43 minutes, or establish the tied-interruption result
for the actual offering. Do not borrow another sport's suspension language.

The captured terms display version 1.2 dated September 17, 2026 and incorporate
betting rules. That identifies a published terms revision, not the effective rules
binding of a particular provider quote. The public product restrictions do not
authorize account access, data reuse or participation; this is not a legal opinion.

## Required evidence / questions — not sent

1. Ask The Odds API which Pinnacle entity/product/region its NBA quote represents,
   and retain an actual response plus scope/title mapping. Reference use does not
   require pretending the user can wager at that product.
2. Obtain the governing rules revision/effective period and complete hierarchy,
   including actual NBA full-game title exceptions and permitted evidence retention.
3. Resolve outcomes for interruption at 42:59, exactly 43:00, later regulation,
   between regulation and overtime, and during overtime, tied and untied. How do
   resumptions within/after the completion window affect those branches?
4. Confirm stake-return economics, fees and finality for each void/tie branch,
   including cancellations, venue changes, forfeits and erroneous markets.
5. Produce a complete reviewed conditioning/invalidation contract and compare it
   with independently approved DraftKings and Novig contracts. Similar overtime
   treatment or a shared Outcome does not establish conditional-population equality.

## Boundary

No positive classification, conditioning-equivalence claim, policy grant or
production loader is created. Missing evidence is not proof of an actual adverse
settlement. Any approval requires a new explicit review revision by an authorized
reviewer; preserve this initial insufficient-evidence record. New adverse evidence
or rules changes must be considered, not filtered to obtain compatibility.

Offline integrity check:

```powershell
python source-approval/capture_settlement_candidates.py pinnacle-nba-fullgame-conditional-v1 --verify
```

The separate `--capture` mode retains a new public-document bundle only. It does
not update review bindings or access odds, credentials, databases or runtime policy.
