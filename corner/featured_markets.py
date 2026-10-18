"""Featured-only provider boundary. No IO, canonical identity inference, or approval.

This is a new adapter, not a change to the historical normalization/replay path.
Raw bytes and JSON pointers identify quotes; outcome counts do not prove coverage.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json

FORMAT = "corner.featured_quotes/1"
FEATURED_MARKETS = ("h2h", "spreads", "totals", "outrights", "h2h_lay", "outrights_lay")
from corner.additional_markets import ADDITIONAL_MARKETS, LINE_MARKETS, SPREAD_MARKETS, TOTAL_MARKETS
SUPPORTED_MARKETS = FEATURED_MARKETS + ADDITIONAL_MARKETS

LAY_PARENTS = {"h2h_lay": "h2h", "outrights_lay": "outrights"}


class FeaturedMarketError(ValueError):
    pass


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise FeaturedMarketError(f"{label} must be a nonblank string")
    return value


def _optional_text(value, label):
    return None if value is None else _text(value, label)


def _time(value, label):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise FeaturedMarketError(f"invalid {label}") from error
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise FeaturedMarketError(f"{label} requires an aware timestamp")
    return value.astimezone(timezone.utc)


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, str)):
        raise FeaturedMarketError(f"{label} must be an exact decimal, not a float")
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise FeaturedMarketError(f"invalid {label}") from error
    if not result.is_finite():
        raise FeaturedMarketError(f"{label} must be finite")
    return result


def _object(value, label):
    if not isinstance(value, dict):
        raise FeaturedMarketError(f"{label} must be an object")
    return value


def _array(value, label):
    if not isinstance(value, list):
        raise FeaturedMarketError(f"{label} must be an array")
    return value


def request_markets(*, has_outrights, requested=None):
    """Plan the odds endpoint's `markets` parameter without calling the provider.

    The catalog's explicit has_outrights flag selects the request family.
    Lay keys request their parent: the provider includes available exchange lays.
    Planning a request neither proves availability nor adds exchange bookmakers.
    """
    if type(has_outrights) is not bool:
        raise FeaturedMarketError("explicit catalog has_outrights flag required")
    allowed = ("outrights", "outrights_lay") if has_outrights else ("h2h", "spreads", "totals", "h2h_lay")
    keys = tuple(allowed if requested is None else requested)
    if not keys or any(key not in FEATURED_MARKETS for key in keys):
        raise FeaturedMarketError("only the six featured market keys are supported")
    if any(key not in allowed for key in keys):
        raise FeaturedMarketError("requested markets do not match the catalog sport family")
    parents = {LAY_PARENTS.get(key, key) for key in keys}
    return tuple(key for key in FEATURED_MARKETS[:4] if key in parents)


@dataclass(frozen=True)
class FeaturedQuote:
    quote_id: str
    source_pointer: str
    event_id: str
    sport_key: str
    commence_time: datetime | None
    bookmaker_key: str
    bookmaker_title: str
    market_key: str
    market_family: str
    bet_side: str
    scope: str
    selection_name: str
    selection_side: str
    point: Decimal | None
    decimal_odds: Decimal
    observed_at: datetime
    provider_updated_at: datetime | None
    bookmaker_sid: str | None
    market_sid: str | None
    outcome_sid: str | None
    bookmaker_link: str | None
    market_link: str | None
    outcome_link: str | None
    subject_name: str | None = None


@dataclass(frozen=True)
class ExcludedMarket:
    source_pointer: str
    market_key: str
    reason: str = "outside_featured_market_scope"


@dataclass(frozen=True)
class FeaturedSnapshot:
    payload_sha256: str
    received_at: datetime
    quotes: tuple[FeaturedQuote, ...]
    excluded_markets: tuple[ExcludedMarket, ...]
    format: str = FORMAT


def _no_constant(value):
    raise FeaturedMarketError(f"non-finite JSON number: {value}")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise FeaturedMarketError("duplicate JSON object key")
        result[key] = value
    return result


def normalize_featured_payload(raw_body: bytes, *, received_at: datetime):
    """Read decimal-format Odds API bytes; report excluded markets explicitly.

    Preserve Draw, outright entrant names, and lay direction. Missing odds are
    malformed input here, not fabricated unavailable observations. The caller
    retains the raw body; this object is a view, not the canonical DB ledger.
    """
    if not isinstance(raw_body, bytes):
        raise FeaturedMarketError("raw response bytes required")
    received_at = _time(received_at, "received_at")
    try:
        document = json.loads(raw_body, parse_float=Decimal, parse_constant=_no_constant,
                              object_pairs_hook=_unique_object)
    except (ValueError, UnicodeDecodeError) as error:
        raise FeaturedMarketError("invalid JSON payload") from error
    events = document if isinstance(document, list) else [document]
    digest = hashlib.sha256(raw_body).hexdigest()
    quotes, excluded = [], []
    event_ids = set()
    for event_index, event in enumerate(events):
        _object(event, "event")
        prefix = f"/{event_index}" if isinstance(document, list) else ""
        event_id = _text(event.get("id"), "event id")
        if event_id in event_ids:
            raise FeaturedMarketError("duplicate event id")
        event_ids.add(event_id)
        sport_key = _text(event.get("sport_key"), "sport key")
        commence = event.get("commence_time")
        commence = None if commence is None else _time(commence, "commence_time")
        books = set()
        for book_index, book in enumerate(_array(event.get("bookmakers", []), "bookmakers")):
            _object(book, "bookmaker")
            book_key = _text(book.get("key"), "bookmaker key")
            if book_key in books:
                raise FeaturedMarketError("duplicate bookmaker key in event")
            books.add(book_key)
            seen = set()
            for market_index, market in enumerate(_array(book.get("markets", []), "markets")):
                _object(market, "market")
                key = _text(market.get("key"), "market key")
                pointer = f"{prefix}/bookmakers/{book_index}/markets/{market_index}"
                if key not in SUPPORTED_MARKETS:
                    excluded.append(ExcludedMarket(pointer, key))
                    continue
                family = LAY_PARENTS.get(key, key)
                is_outright = family == "outrights"
                if not is_outright:
                    home = _text(event.get("home_team"), "home team")
                    away = _text(event.get("away_team"), "away team")
                    if home == away:
                        raise FeaturedMarketError("distinct event participants required")
                updated = market.get("last_update", book.get("last_update"))
                updated = None if updated is None else _time(updated, "provider_updated_at")
                for outcome_index, outcome in enumerate(_array(market.get("outcomes", []), "outcomes")):
                    _object(outcome, "outcome")
                    name = _text(outcome.get("name"), "selection name")
                    if is_outright:
                        side = "entrant"
                    elif family in TOTAL_MARKETS and name.casefold() in {"over", "under"}:
                        side = name.casefold()
                    elif family in ({"h2h", "draw_no_bet"} | SPREAD_MARKETS) and name in (home, away):
                        side = "home" if name == home else "away"
                    elif family == "h2h" and name.casefold() == "draw":
                        side = "draw"
                    elif family == "btts" and name.casefold() in {"yes", "no"}:
                        side = name.casefold()
                    else:
                        raise FeaturedMarketError("selection does not match featured market")
                    point = outcome.get("point")
                    if family in LINE_MARKETS:
                        point = _number(point, "line point")
                    elif point is not None:
                        raise FeaturedMarketError("moneyline/outright cannot carry line points")
                    subject = outcome.get("description") if key in {"team_totals", "alternate_team_totals"} else None
                    if key in {"team_totals", "alternate_team_totals"} and subject not in (home, away):
                        raise FeaturedMarketError("team total must identify an exact event participant")
                    identity = (key, name, point, subject)
                    if identity in seen:
                        raise FeaturedMarketError("duplicate featured quote identity")
                    seen.add(identity)
                    price = _number(outcome.get("price"), "decimal odds")
                    if price <= 1:
                        raise FeaturedMarketError("decimal odds must exceed one")
                    locator = f"{pointer}/outcomes/{outcome_index}"
                    quotes.append(FeaturedQuote(
                        quote_id=hashlib.sha256(f"{digest}:{locator}".encode()).hexdigest(),
                        source_pointer=locator, event_id=event_id, sport_key=sport_key,
                        commence_time=commence, bookmaker_key=book_key,
                        bookmaker_title=_text(book.get("title", book_key), "bookmaker title"),
                        market_key=key, market_family=family,
                        bet_side="lay" if key in LAY_PARENTS else "back",
                        scope="competition" if is_outright else "full_game",
                        selection_name=name, selection_side=side, point=point, decimal_odds=price,
                        observed_at=received_at, provider_updated_at=updated,
                        bookmaker_sid=_optional_text(book.get("sid"), "bookmaker sid"),
                        market_sid=_optional_text(market.get("sid"), "market sid"),
                        outcome_sid=_optional_text(outcome.get("sid"), "outcome sid"),
                        bookmaker_link=_optional_text(book.get("link"), "bookmaker link"),
                        market_link=_optional_text(market.get("link"), "market link"),
                        outcome_link=_optional_text(outcome.get("link"), "outcome link"), subject_name=subject))
    return FeaturedSnapshot(digest, received_at, tuple(quotes), tuple(excluded))


def snapshot_document(snapshot: FeaturedSnapshot):
    """JSON-ready view for fixtures/API adapters; never implicitly round decimals."""
    def encode(value):
        if isinstance(value, Decimal):
            text = format(value, "f")
            return text.rstrip("0").rstrip(".") if "." in text else text
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
        if isinstance(value, dict):
            return {key: encode(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [encode(item) for item in value]
        return value
    return encode(asdict(snapshot))
