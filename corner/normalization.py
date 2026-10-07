"""Pure normalization of The Odds API v4 event payloads into Corner contracts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


MARKET_MAPPINGS = {
    "h2h": "moneyline",
    "spreads": "spread",
    "totals": "total",
    "player_pass_tds": "player_pass_tds",
}


@dataclass(frozen=True)
class NormalizedQuote:
    event_external_id: str
    bookmaker_key: str
    bookmaker_name: str
    provider_market_key: str
    market_type_code: str
    scope_code: str
    outcome_side_code: str
    selected_participant_name: str | None
    subject_participant_name: str | None
    point: Decimal | None
    decimal_odds: Decimal | None
    provider_updated_at: str | None
    source_record_key: str
    quote_state_code: str = "active"

    def __post_init__(self) -> None:
        if self.quote_state_code not in {"active", "suspended", "unavailable"}:
            raise ValueError(f"unsupported quote state: {self.quote_state_code!r}")
        if self.quote_state_code == "active":
            if (self.decimal_odds is None or not self.decimal_odds.is_finite()
                    or self.decimal_odds <= 1):
                raise ValueError("active quotes require finite decimal odds greater than 1")
        elif self.decimal_odds is not None:
            raise ValueError("non-priced quote states require null decimal odds")


def source_record_key(
    event_id: str,
    bookmaker_key: str,
    market_key: str,
    market_index: int,
    outcome_index: int,
) -> str:
    """Return a stable locator when replaying the same immutable payload."""
    return (
        f"event[{event_id}]/bookmaker[{bookmaker_key}]/"
        f"market[{market_key}:{market_index}]/outcome[{outcome_index}]"
    )


def normalize_event(event: dict[str, Any]) -> list[NormalizedQuote]:
    """Normalize supported main markets from one Odds API event.

    This intentionally preserves provider vocabulary at the boundary and emits
    canonical contract concepts only after mapping h2h/spreads/totals.
    """
    event_id = event["id"]
    home_team = event["home_team"]
    away_team = event["away_team"]
    quotes: list[NormalizedQuote] = []

    for bookmaker in event.get("bookmakers", []):
        bookmaker_key = bookmaker["key"]
        bookmaker_name = bookmaker.get("title", bookmaker_key)
        for market_index, market in enumerate(bookmaker.get("markets", [])):
            provider_market_key = market["key"]
            market_type_code = MARKET_MAPPINGS.get(provider_market_key)
            if market_type_code is None:
                continue

            for outcome_index, outcome in enumerate(market.get("outcomes", [])):
                side, selected_participant, subject_participant = _normalize_outcome_contract(
                    provider_market_key,
                    outcome,
                    home_team,
                    away_team,
                )
                price = outcome.get("price")
                decimal_odds = Decimal(str(price)) if price is not None else None
                if decimal_odds is not None and decimal_odds <= 1:
                    raise ValueError(f"invalid decimal odds for {event_id}: {price!r}")

                point = outcome.get("point")
                quotes.append(
                    NormalizedQuote(
                        event_external_id=event_id,
                        bookmaker_key=bookmaker_key,
                        bookmaker_name=bookmaker_name,
                        provider_market_key=provider_market_key,
                        market_type_code=market_type_code,
                        scope_code="full_game",
                        outcome_side_code=side,
                        selected_participant_name=selected_participant,
                        subject_participant_name=subject_participant,
                        point=Decimal(str(point)) if point is not None else None,
                        decimal_odds=decimal_odds,
                        provider_updated_at=market.get("last_update"),
                        source_record_key=source_record_key(
                            event_id,
                            bookmaker_key,
                            provider_market_key,
                            market_index,
                            outcome_index,
                        ),
                    )
                )
    return quotes


def _normalize_outcome_contract(
    market_key: str,
    outcome: dict[str, Any],
    home_team: str,
    away_team: str,
) -> tuple[str, str | None, str | None]:
    outcome_name = outcome.get("name")
    if not outcome_name:
        raise ValueError(f"{market_key} outcome is missing a name")

    if market_key in {"h2h", "spreads"}:
        if outcome_name == home_team:
            return "home", home_team, None
        if outcome_name == away_team:
            return "away", away_team, None
        if market_key == "h2h" and outcome_name.casefold() == "draw":
            return "draw", None, None
        raise ValueError(f"unrecognized {market_key} outcome {outcome_name!r}")

    normalized_total = outcome_name.casefold()
    if market_key == "totals" and normalized_total in {"over", "under"}:
        return normalized_total, None, None
    if market_key == "player_pass_tds" and normalized_total in {"over", "under"}:
        subject = outcome.get("description")
        if not subject:
            raise ValueError("player_pass_tds outcome is missing a player description")
        return normalized_total, None, subject
    raise ValueError(f"unrecognized {market_key} outcome {outcome_name!r}")
