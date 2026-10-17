"""N-way proportional no-vig consensus and back/lay conditional EV.

Explicit exact contract matching is required. This does not estimate push,
nonrunner, dead-heat, or invalidation probabilities from two-way prices. Use the
explicit payoff model when those branches have supplied probabilities.
"""
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from corner.reference_policy import sufficient_references
from corner.reference_weights import reference_weight, WEIGHT_VERSION

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


def calculate_featured_ev(market, target, reference_offers, *, required_reference_books,
                         stake=Decimal("1"), sport_key=''):
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
    consensus = {s: Fraction(0) for s in market.selection_ids}
    weights = {book: Fraction(reference_weight(book, sport_key)) for book in books}
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
    p = consensus[target.selection_id]
    odds, amount, commission = map(Fraction, (target.decimal_odds, stake, target.commission_rate))
    if target.market_key in LAY_MARKETS:
        expected = amount * ((1 - p) * (1 - commission) - p * (odds - 1))
        capital = amount * (odds - 1)
    else:
        expected = amount * (p * (odds - 1) * (1 - commission) - (1 - p))
        capital = amount
    return FeaturedEV(market.contract_id, target.quote_id, target.selection_id, tuple(references),
                      tuple((s, _decimal_ratio(consensus[s])) for s in sorted(consensus)), _decimal_ratio(p),
                      _decimal_ratio(expected), _decimal_ratio(expected / capital), stake, _decimal_ratio(capital))
