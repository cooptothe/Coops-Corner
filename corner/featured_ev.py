"""N-way proportional no-vig consensus and back/lay conditional EV.

Explicit exact contract matching is required. This does not estimate push,
nonrunner, dead-heat, or invalidation probabilities from two-way prices. Use the
explicit payoff model when those branches have supplied probabilities.
"""
from dataclasses import dataclass, replace
from decimal import Decimal
from fractions import Fraction
from functools import lru_cache
from corner.devig_methods import comparisons, pooled_distributions, distributions
from corner.reference_policy import sufficient_references
from corner.reference_weights import reference_weight, WEIGHT_VERSION
from corner.reference_policy import reference_source
from collections import Counter

from corner.featured_tools import MatchedMarket, Offer, LAY_MARKETS, _require, _decimal_ratio, _decimal, _id

FORMAT = "corner.featured_ev/1"


@dataclass(frozen=True)
class ReferenceProbability:
    sportsbook_id: str
    quote_ids: tuple[str, ...]
    probabilities: tuple[tuple[str, Decimal], ...]
    implied_probability_sum: Decimal
    weight: Decimal = Decimal('1')


@dataclass(frozen=True)
class FeaturedEV:
    contract_id: str
    target_quote_id: str
    selection_id: str
    reference_books: tuple[ReferenceProbability, ...]
    conditional_probabilities: tuple[tuple[str, Decimal], ...]
    conditional_fair_probability: Decimal
    conditional_expected_profit: Decimal
    conditional_ev_ratio_on_capital: Decimal
    stake: Decimal
    capital_at_risk: Decimal
    calculation_basis: str = "decisive_settlement_conditional"
    probability_basis: str = "named_selection_wins_given_decisive_settlement"
    devig_method: str = "proportional_reputation_weighted_consensus"
    reference_weight_version: str = WEIGHT_VERSION
    nondecisive_probability_model: None = None
    unconditional_ev_ratio: None = None
    format: str = FORMAT
    availability_verified: bool = False
    devig_comparisons: tuple = ()
    applied_devig_method: str = 'multiplicative'


def calculate_featured_ev(market, target, reference_offers, *, required_reference_books,
                         stake=Decimal("1"), sport_key='', devig_method='current'):
    """Use every explicitly required complete reference book; never silently drop one.

    Three-way h2h includes draw, outrights includes every declared entrant. Spread
    and total contracts are exact-line contracts with conditional decisive prices.
    References use raw back prices: account execution commission is not bookmaker
    margin and is not subtracted when estimating consensus. Target may be lay.
    """
    _require(type(market) is MatchedMarket and type(target) is Offer, "validated market/target required")
    _decimal(stake, "stake", positive=True)
    _require(target.contract_id == market.contract_id and target.selection_id in market.selection_ids,
             "target contract mismatch")
    _require(target.market_key == market.market_key or LAY_MARKETS.get(target.market_key) == market.market_key,
             "target market mismatch")
    from corner.book_policy import supported_book
    books = tuple(required_reference_books)
    _require(supported_book(target.sportsbook_id) and all(supported_book(b) for b in books),
             "withdrawn sportsbook is not supported")
    for book in books:
        _id(book)
    _require(sufficient_references(books, sport_key) and len(set(books)) == len(books), "at least two distinct required reference books")
    _require(target.sportsbook_id not in books, "target cannot be its own reference")
    offers = tuple(reference_offers)
    _require(all(type(o) is Offer for o in offers), "validated references required")
    _require(len({o.quote_id for o in offers}) == len(offers) and target.quote_id not in {o.quote_id for o in offers},
             "duplicate quote identity")
    for offer in offers:
        _require(offer.sportsbook_id in books, "unexpected reference book")
        _require((offer.contract_id, offer.market_key) == (market.contract_id, market.market_key),
                 "incompatible reference contract or direction")
        _require(offer.selection_id in market.selection_ids, "unexpected selection")
    probabilities, references = _reference_consensus(market, offers, books, sport_key)
    consensus = dict(probabilities)
    _require(devig_method in {'current', 'multiplicative', 'additive', 'power', 'shin', 'worst_case'}, 'unsupported devig method')
    populations = tuple((tuple(o.decimal_odds for o in sorted(
        (o for o in offers if o.sportsbook_id == reference.sportsbook_id), key=lambda o: o.selection_id)),
        reference.weight) for reference in references)
    applied_method = 'multiplicative'
    if devig_method != 'current':
        methods = dict(pooled_distributions(populations))
        _require(devig_method in methods, 'devig method unavailable for reference population')
        applied_method = devig_method
        if devig_method == 'worst_case':
            index = sorted(market.selection_ids).index(target.selection_id)
            choose = max if target.market_key in LAY_MARKETS else min
            applied_method = choose((name for name in methods if name != 'worst_case'),
                                    key=lambda name: methods[name][index])
        values = methods[applied_method]
        consensus = dict(zip(sorted(market.selection_ids), map(Fraction, values)))
        references = tuple(replace(reference, probabilities=tuple(zip(sorted(market.selection_ids),
                           dict(distributions(population[0]))[applied_method])))
                           for reference, population in zip(references, populations))
    p = consensus[target.selection_id]
    odds, amount, commission = map(Fraction, (target.decimal_odds, stake, target.commission_rate))
    if target.market_key in LAY_MARKETS:
        expected = amount * ((1 - p) * (1 - commission) - p * (odds - 1))
        capital = amount * (odds - 1)
    else:
        expected = amount * (p * (odds - 1) * (1 - commission) - (1 - p))
        capital = amount
    comparison = comparisons(populations, sorted(market.selection_ids).index(target.selection_id),
                             target.decimal_odds, target.commission_rate,
                             lay=target.market_key in LAY_MARKETS)
    return FeaturedEV(market.contract_id, target.quote_id, target.selection_id, tuple(references),
                      tuple((s, _decimal_ratio(consensus[s])) for s in sorted(consensus)), _decimal_ratio(p),
                      _decimal_ratio(expected), _decimal_ratio(expected / capital), stake, _decimal_ratio(capital), devig_comparisons=comparison,
                      devig_method='proportional_reputation_weighted_consensus' if devig_method == 'current' else devig_method,
                      applied_devig_method=applied_method)


@lru_cache(maxsize=4096)
def _reference_consensus(market, offers, books, sport_key):
    """Bounded exact computation cache; callers still validate every request.

    Immutable keys contain every reference identity, price, contract and book.
    Freshness and eligibility remain enforced by the catalog before calculation.
    """
    consensus = {s: Fraction(0) for s in market.selection_ids}
    source_counts = Counter(reference_source(b) for b in books)
    weights = {book: Fraction(reference_weight(book, sport_key, market_key=market.market_key))/source_counts[reference_source(book)] for book in books}
    total_weight = sum(weights.values())
    references = []
    for book in sorted(books):
        entries = [o for o in offers if o.sportsbook_id == book]
        _require(len(entries) == len(market.selection_ids) and {o.selection_id for o in entries} == set(market.selection_ids),
                 f"incomplete or duplicate reference population: {book}")
        implied = {o.selection_id: 1 / Fraction(o.decimal_odds) for o in entries}
        total = sum(implied.values())
        probabilities = {s: p / total for s, p in implied.items()}
        for selection, probability in probabilities.items():
            consensus[selection] += probability * weights[book] / total_weight
        references.append(ReferenceProbability(book, tuple(o.quote_id for o in sorted(entries, key=lambda o: o.selection_id)),
                          tuple((s, _decimal_ratio(probabilities[s])) for s in sorted(probabilities)), _decimal_ratio(total), _decimal_ratio(weights[book] / total_weight)))
    return tuple(consensus.items()), tuple(references)
