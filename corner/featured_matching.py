"""Explicit provider-to-canonical binding for the six featured markets.

Routes are caller-supplied identity mappings, not settlement or phase approvals.
The database writer independently verifies these identities against the registry.
"""
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from corner.featured_markets import SUPPORTED_MARKETS, FeaturedSnapshot
from corner.additional_markets import LINE_MARKETS, MARKET_TYPES as ADDITIONAL_TYPES

MARKET_TYPES = {"h2h": "moneyline", "spreads": "spread", "totals": "total",
                "outrights": "outright", "h2h_lay": "moneyline_lay", "outrights_lay": "outright_lay"}

MARKET_TYPES.update(ADDITIONAL_TYPES)

class BindingError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise BindingError(message)


def identity(value):
    require(isinstance(value, str), "canonical UUID string required")
    try:
        require(str(UUID(value)) == value, "canonical UUID representation required")
    except ValueError as error:
        raise BindingError("canonical UUID required") from error


@dataclass(frozen=True)
class SelectionRoute:
    provider_name: str
    point: Decimal | None
    outcome_id: str
    subject_name: str | None = None

    def __post_init__(self):
        require(isinstance(self.provider_name, str) and bool(self.provider_name.strip()), "selection name required")
        identity(self.outcome_id)
        require(self.point is None or isinstance(self.point, Decimal) and self.point.is_finite(), "finite Decimal point required")


@dataclass(frozen=True)
class MarketRoute:
    provider_event_id: str
    provider_sport_key: str
    market_key: str
    market_id: str
    selections: tuple[SelectionRoute, ...]

    def __post_init__(self):
        for value in (self.provider_event_id, self.provider_sport_key):
            require(isinstance(value, str) and bool(value.strip()), "provider event/sport identity required")
        identity(self.market_id)
        require(self.market_key in SUPPORTED_MARKETS, "featured market required")
        require(type(self.selections) is tuple and bool(self.selections)
                and all(type(s) is SelectionRoute for s in self.selections), "explicit selection routes required")
        require(len({(s.provider_name, s.point, s.subject_name) for s in self.selections}) == len(self.selections), "ambiguous selection route")
        require(len({s.outcome_id for s in self.selections}) == len(self.selections), "multiple selections cannot share an outcome")
        for selection in self.selections:
            require((selection.point is not None) == (self.market_key in LINE_MARKETS), "market/point mismatch")


@dataclass(frozen=True)
class BookRoute:
    provider_bookmaker_key: str
    sportsbook_id: str

    def __post_init__(self):
        require(isinstance(self.provider_bookmaker_key, str) and bool(self.provider_bookmaker_key.strip()), "book key required")
        identity(self.sportsbook_id)


@dataclass(frozen=True)
class QuoteBinding:
    source_pointer: str
    market_id: str
    outcome_id: str
    sportsbook_id: str

    def __post_init__(self):
        require(isinstance(self.source_pointer, str) and self.source_pointer.startswith("/"), "source JSON pointer required")
        for value in (self.market_id, self.outcome_id, self.sportsbook_id):
            identity(value)


def bind_snapshot(snapshot: FeaturedSnapshot, *, markets, books):
    require(type(snapshot) is FeaturedSnapshot, "featured snapshot required")
    markets, books = tuple(markets), tuple(books)
    require(all(type(m) is MarketRoute for m in markets) and all(type(b) is BookRoute for b in books), "typed routes required")
    routes = {(m.provider_event_id, m.provider_sport_key, m.market_key): m for m in markets}
    book_routes = {b.provider_bookmaker_key: b.sportsbook_id for b in books}
    require(len(routes) == len(markets) and len(book_routes) == len(books), "duplicate or ambiguous routes")
    # Direction and event identities cannot be collapsed into one canonical market.
    require(len({m.market_id for m in markets}) == len(markets), "distinct routes require distinct canonical markets")
    result = []
    for quote in snapshot.quotes:
        route = routes.get((quote.event_id, quote.sport_key, quote.market_key))
        require(route is not None, "unmapped featured market")
        book = book_routes.get(quote.bookmaker_key)
        require(book is not None, "unmapped sportsbook")
        selection = next((s for s in route.selections
                          if (s.provider_name, s.point, s.subject_name) == (quote.selection_name, quote.point, quote.subject_name)), None)
        require(selection is not None, "unmapped selection or exact line")
        result.append(QuoteBinding(quote.source_pointer, route.market_id, selection.outcome_id, book))
    require(len({b.source_pointer for b in result}) == len(result), "duplicate source binding")
    return tuple(result)
