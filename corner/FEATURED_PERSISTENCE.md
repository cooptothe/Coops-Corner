# Featured canonical matching, persistence and query adapter

Implemented October 2, 2026. No new schema migration is required. The first proof
uses a synthetic six-market payload in a disposable PostgreSQL database, not the
main local database and not a production-authorized evidence path.

## Physical mapping

| Provider key | Canonical market type | Scope |
| --- | --- | --- |
| h2h | moneyline | full_game |
| spreads | spread | full_game |
| totals | total | full_game |
| outrights | outright | competition |
| h2h_lay | moneyline_lay | full_game |
| outrights_lay | outright_lay | competition |

Existing vocabulary tables permit these explicit codes. A competition-scoped
tournament occurrence is an Event with competitor participants, not a fabricated
home/away matchup. No default pregame status is assigned by this adapter.

Back and lay have different canonical Markets and Outcomes. Consequently the
existing `(outcome_id, sportsbook_id)` trusted-current stream identity cannot
overwrite a back quote with a lay quote. During hedge assembly, the query adapter
maps their selections only after comparing event, scope, family, participant,
side and point. The original observation IDs remain attached to both offers.

## Explicit registry binding

`featured_matching.bind_snapshot(snapshot, markets=..., books=...)` accepts typed
`MarketRoute`, `SelectionRoute`, and `BookRoute` objects. Every featured quote
must bind exactly once; unknown markets, books, names or line points fail.
Non-featured markets already excluded by the parser remain explicitly reported.
Routes are not discovered by fuzzy names or by copying the available price set.

The registry must already contain the canonical events/competitions, participants,
market types/scopes, outcomes and active provider identities. The store rechecks
every binding against those rows, including unambiguous competition-scoped
participant aliases and event membership. It does not auto-create or mutate them.
These identity mappings prove neither settlement equivalence nor phase approval.

## Retained payload to observations

```python
bindings = bind_snapshot(snapshot, markets=market_routes, books=book_routes)
receipt = ingest_featured_payload(conn, payload_id=retained_payload_id,
                                  bindings=bindings)
conn.commit()  # caller owns the whole transaction
```

The writer requires a READ COMMITTED transaction and an existing successful
`the_odds_api` ProviderPayload. It verifies the raw-body digest and reparses the
retained bytes with the retained receipt time; caller-supplied prices cannot
replace the source. A payload-specific transaction advisory lock serializes
competing writers without granting UPDATE on the immutable payload.

All bindings validate before insertion. A savepoint also rolls back earlier
inserts if a later SQL write fails. No partial observations remain. Existing
ingestion batch status/commit ownership stays with the caller.

Source locators use `featured-v1:` plus the JSON pointer. Exact retries compare
the proposed canonical bindings and all observation values against the original
rows and return original observation IDs. They do not re-resolve current aliases.
Changed bindings, mixed historical adapters, or partial existing ingestion conflict.
An empty payload creates no fake observations; absence is not unavailability.

Raw prices remain retained at source precision. The existing observation column
is NUMERIC(12,6), so this writer **rejects** a price it cannot store exactly; it
never silently rounds it into a different quote. Extending SQL precision is a
separate change if real inputs require it.

## Read-only calculator integration

`read_featured_streams` reads an explicit set of expected outcome/book pairs in
one SQL statement. It exposes observation ID, payload/provider IDs, source
locator, exact stored price, state and timestamps. Missing rows remain explicit.
It respects dispositions and does not fall back to an older active quote after
an unavailable/suspended quote becomes current. An observation exactly at the
age limit is fresh; later than the limit is stale. Future observations and
provider update timestamps later than receipt are ineligible.

`read_calculation_inputs` requires a **REPEATABLE READ, READ ONLY** transaction
because canonical structure and current quotes are read in separate statements:

```python
conn.set_session(isolation_level='REPEATABLE READ', readonly=True)
inputs = read_calculation_inputs(
    conn, market_id=back_market_id, outcome_ids=expected_outcome_ids,
    sportsbook_ids=book_ids, assessed_at=assessment_time,
    max_age=age_limit, max_input_skew=skew_limit,
    settlement_identity=explicit_rules_identity, refund_possible=True,
    commissions=commission_by_book, lay_market_id=optional_matching_lay_market_id,
)
cover = inputs.back_cover(total_stake=Decimal('100'))
conn.rollback()  # release read snapshot
```

The winner population must include every registered h2h/outright outcome. The
caller still must establish that the registry itself is complete. Spreads require
opposite signed points for distinct home/away participants. Totals require the
same threshold. Integer lines require a refund/push branch; quarter/split lines
are rejected by this simple payoff model. Separate line pairs receive different
calculation identities. Mixed rule identities must not be supplied as compatible.

Missing/stale/unavailable streams are returned as diagnostics, not fictitious
prices. Covers fail if any expected decisive selection has no eligible offer.
Excessive input skew fails the entire candidate snapshot rather than choosing a
convenient subset. Commission must be supplied for every requested book, including
an explicit zero for no commission. Back-cover commission remains unsupported
when nonzero; isolated back/lay commission follows the pure calculator contract.

The adapter does not authenticate the supplied settlement identity, prove live
liquidity, establish pregame phase, or open lifecycle episodes. Provider timestamp
age limits, source approval and actionability remain separate policies. It does
not recalculate or reinterpret persisted v1/v2 evaluations.

## Verification and boundaries

`test_featured_store.py` exercises pure binding plus isolated PostgreSQL writes,
concurrent retries, changed-binding conflicts, injected mid-write failure,
digest/precision validation, stale and missing states, disposition changes, and
database-to-calculator integration. Test databases are uniquely named and removed.
No production role memberships, grants, service configuration or main tables are
changed by the acceptance harness. Existing runtime profiles have not been newly
certified for this adapter; service wiring remains separate.

Next: broader versioned +EV/payoff models, then middles and promo calculators,
tracker/bankroll/CLV, and the browser-facing API. No approval research or paid data
capture is needed to continue fixture-backed development.
