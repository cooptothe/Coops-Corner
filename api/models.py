"""Versioned frontend schemas; all money, odds and ratios travel as strings."""
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, AwareDatetime

from corner.featured_ev import FeaturedEV
from corner.featured_tools import BackCover, BackLayHedge
from corner.featured_middles import MiddleResult
from corner.featured_promos import PromoConversion, PromoBackConversion

from corner.additional_markets import PROP_KEYS

MarketKey = Literal['h2h', 'spreads', 'totals', 'outrights', 'h2h_lay', 'outrights_lay', 'alternate_spreads', 'alternate_totals', 'btts', 'draw_no_bet', 'team_totals', 'alternate_team_totals', *sorted(PROP_KEYS)]
ToolKind = Literal['positive_ev', 'arbitrage', 'low_hold', 'middle']
DecimalText = Annotated[str, Field(strict=True, max_length=80, pattern=r'^-?(0|[1-9][0-9]*)(\.[0-9]+)?$')]
InputDecimal = Annotated[str, Field(strict=True, max_length=26, pattern=r'^(0|[1-9][0-9]{0,12})(\.[0-9]{1,12})?$')]
Identifier = Annotated[str, Field(strict=True, min_length=1, max_length=180)]


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Meta(Model):
    format: Literal['corner.product_api/1'] = 'corner.product_api/1'
    data_mode: Literal['fixture', 'database'] = 'fixture'
    snapshot_id: str
    captured_at: AwareDatetime
    reference_clock_at: AwareDatetime
    served_at: AwareDatetime
    production_authorized: Literal[False] = False
    availability_verified: Literal[False] = False
    warnings: tuple[str, ...] = ('synthetic_data_not_bettable', 'fixture_clock_not_live_time', 'no_production_authorization')


T = TypeVar('T')


class Envelope(Model, Generic[T]):
    meta: Meta
    data: T


class Page(Model, Generic[T]):
    items: list[T]
    total: int
    offset: int
    limit: int
    next_offset: int | None


class Game(Model):
    id: str
    sport_key: str
    competition: str
    name: str
    starts_at: AwareDatetime
    scope: Literal['full_game', 'competition']
    participants: list[str]
    market_keys: list[MarketKey]
    quote_count: int
    phase: Literal['unknown'] = 'unknown'


class Book(Model):
    id: str
    name: str
    commission: DecimalText | None
    fee_status: str = 'fixture_explicit'


class QuoteLinks(Model):
    """Validated sportsbook links; each may contain {state}, {wager}, {wagerAmount} or {pickType} placeholders."""
    event: str | None = None
    market: str | None = None
    outcome: str | None = None

class NativeIds(Model):
    event: str | None = None
    market: str | None = None
    outcome: str | None = None


class Quote(Model):
    source_ids: NativeIds | None = None
    id: str
    game_id: str
    contract_id: str
    market_key: MarketKey
    sportsbook_id: str
    selection_id: str
    selection_name: str
    side: str
    point: DecimalText | None
    decimal_odds: DecimalText
    commission_rate: DecimalText | None
    fee_status: str = 'fixture_explicit'
    observed_at: AwareDatetime
    provider_updated_at: AwareDatetime | None
    links: QuoteLinks | None = None
    current_availability: Literal['unverified'] = 'unverified'
    evidence_kind: Literal['synthetic_fixture', 'retained_provider_quote'] = 'synthetic_fixture'


class RowBase(Model):
    id: str
    game_id: str
    contract_id: str
    market_key: MarketKey
    sportsbook_ids: list[str]
    quote_ids: list[str]
    oldest_observed_at: AwareDatetime
    conditional_ev_ratio: DecimalText | None = None
    minimum_profit: DecimalText | None = None
    capital_required: DecimalText


class EVRow(RowBase):
    kind: Literal['positive_ev'] = 'positive_ev'
    calculation: FeaturedEV


class CoverRow(RowBase):
    kind: Literal['arbitrage', 'low_hold']
    calculation: BackCover | BackLayHedge


class MiddleRow(RowBase):
    kind: Literal['middle'] = 'middle'
    calculation: MiddleResult


ToolRow = Annotated[EVRow | CoverRow | MiddleRow, Field(discriminator='kind')]


class PageQuery(Model):
    offset: int = Field(default=0, ge=0, le=10000)
    limit: int = Field(default=25, ge=1, le=100)
    snapshot_id: Identifier | None = None


class GameQuery(PageQuery):
    sport_key: Identifier | None = None
    search: Annotated[str, Field(max_length=100)] | None = None
    market_key: MarketKey | None = None
    sort: Literal['starts_at', 'name', 'id'] = 'starts_at'
    descending: bool = False


class QuoteQuery(PageQuery):
    market_key: MarketKey | None = None
    sportsbook_id: Identifier | None = None
    contract_id: Identifier | None = None
    sort: Literal['id', 'decimal_odds', 'observed_at'] = 'id'
    descending: bool = False


class BulkQuoteQuery(QuoteQuery):
    """Every quote of a snapshot in a few large pages, instead of one request per game."""
    offset: int = Field(default=0, ge=0, le=100000)
    limit: int = Field(default=500, ge=1, le=1000)


class ToolQuery(PageQuery):
    game_id: Identifier | None = None
    sport_key: Identifier | None = None
    market_key: MarketKey | None = None
    sportsbook_id: Identifier | None = None
    sort: Literal['id', 'conditional_ev_ratio', 'minimum_profit', 'capital_required'] = 'id'
    descending: bool = False
    minimum_ev_ratio: InputDecimal = '0'
    maximum_loss_ratio: InputDecimal = '0.01'


class TermsInput(Model):
    terms_id: Identifier
    kind: Literal['bonus_stake_not_returned', 'bonus_stake_returned_as_cash', 'loss_refund_cash', 'loss_refund_bonus']
    face_value: InputDecimal
    eligible_stake_cap: InputDecimal
    minimum_decimal_odds: InputDecimal
    loss_refund_cap: InputDecimal
    eligibility_evidence_id: Identifier
    bonus_restored_on_void: bool = Field(strict=True)


class PromoRequest(Model):
    snapshot_id: Identifier
    contract_id: Identifier
    promo_quote_id: Identifier
    hedge_quote_id: Identifier
    hedge_type: Literal['lay', 'opposite_back']
    terms: TermsInput
    stake_increment: InputDecimal = '0.01'
    maximum_hedge_stake: InputDecimal | None = None
    maximum_lay_liability: InputDecimal | None = None


class PromoResponse(Model):
    id: str
    game_id: str
    contract_id: str
    promo_quote_id: str
    hedge_quote_id: str
    calculation: PromoConversion | PromoBackConversion


class Health(Model):
    status: Literal['ok'] = 'ok'
    fixture_loaded: Literal[True] = True
    database_connected: Literal[False] = False
    live_mode_supported: Literal[False] = False


class Capabilities(Model):
    market_keys: list[MarketKey]
    tools: list[ToolKind]
    books: list[Book]
    sports: list[str]
    calculator_defaults: dict[str, DecimalText]
    unsupported: list[str]


class ErrorDetail(Model):
    code: str
    message: str
    fields: list[str] = Field(default_factory=list)


class ErrorEnvelope(Model):
    meta: Meta
    error: ErrorDetail
