"""Pure pregame EV evaluation over an already-selected trusted quote snapshot.

No database access, clock reads, current-quote selection, or product thresholds.
Settlement and event phase must be established by the input adapter; two prices
alone do not prove a two-way, no-push contract.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from enum import Enum


ENGINE_NAME = 'corner.pregame_moneyline_ev'
ENGINE_VERSION = '1.0.0'


class ProviderTimePolicy(str, Enum):
    IGNORE = 'ignore'
    REQUIRE = 'require'
    MAX_AGE_IF_PRESENT = 'max_age_if_present'


class Reason(str, Enum):
    INVALID_SNAPSHOT = 'invalid_snapshot'
    CONFIGURATION_MISMATCH = 'configuration_mismatch'
    UNSUPPORTED_PHASE = 'unsupported_phase'
    UNSUPPORTED_SETTLEMENT = 'unsupported_settlement'
    INACTIVE_TARGET = 'inactive_target'
    STALE_TARGET = 'stale_target'
    INVALID_TARGET_PRICE = 'invalid_target_price'
    FUTURE_TARGET = 'future_target'
    TARGET_PROVIDER_TIME = 'target_provider_time_ineligible'
    INSUFFICIENT_REFERENCE_COVERAGE = 'insufficient_reference_coverage'
    INPUT_SKEW = 'input_skew_exceeded'


class InputIssue(str, Enum):
    TARGET_BOOK = 'target_book_excluded'
    INCOMPLETE = 'incomplete_reference_set'
    INACTIVE = 'inactive_quote'
    STALE = 'stale_quote'
    INVALID_PRICE = 'invalid_price'
    FUTURE_OBSERVATION = 'future_observation'
    MISSING_PROVIDER_TIME = 'missing_provider_timestamp'
    STALE_PROVIDER_TIME = 'stale_provider_timestamp'
    FUTURE_PROVIDER_TIME = 'future_provider_timestamp'


def _aware(value):
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


@dataclass(frozen=True)
class OutcomeContract:
    outcome_id: str
    participant_id: str | None
    point: Decimal | None = None


@dataclass(frozen=True)
class MarketContract:
    market_id: str
    competition_id: str
    market_type: str
    scope: str
    settlement_policy: str
    settlement_evidence: str
    outcomes: tuple[OutcomeContract, ...]

    def __post_init__(self):
        object.__setattr__(self, 'outcomes', tuple(self.outcomes))


@dataclass(frozen=True)
class QuoteInput:
    observation_id: str
    market_id: str
    outcome_id: str
    sportsbook_id: str
    decimal_odds: Decimal | None
    quote_state: str
    observed_at: datetime
    provider_updated_at: datetime | None = None


@dataclass(frozen=True)
class EVSnapshot:
    evaluated_at: datetime
    event_phase: str
    phase_evidence: str
    contract: MarketContract
    target_observation_id: str
    quotes: tuple[QuoteInput, ...]

    def __post_init__(self):
        object.__setattr__(self, 'quotes', tuple(self.quotes))


@dataclass(frozen=True)
class EVConfiguration:
    version: str
    competition_id: str
    market_type: str
    scope: str
    reference_sportsbook_ids: tuple[str, ...]
    target_max_age: timedelta
    reference_max_age: timedelta
    max_input_skew: timedelta
    provider_time_policy: ProviderTimePolicy
    provider_max_age: timedelta | None
    calculation_precision: int
    minimum_reference_books: int = 2
    no_vig_method: str = 'proportional'
    consensus_method: str = 'equal_weight'
    settlement_policy: str = 'two_way_no_push'
    rounding: str = ROUND_HALF_EVEN

    def __post_init__(self):
        object.__setattr__(self, 'reference_sportsbook_ids', tuple(self.reference_sportsbook_ids))
        if not self.version.strip():
            raise ValueError('configuration version is required')
        if (len(set(self.reference_sportsbook_ids)) != len(self.reference_sportsbook_ids)
                or any(not book for book in self.reference_sportsbook_ids)):
            raise ValueError('reference sportsbook IDs must be distinct and nonblank')
        if self.minimum_reference_books < 2:
            raise ValueError('v1 consensus requires at least two reference books')
        if self.calculation_precision < 28:
            raise ValueError('calculation precision must be at least 28 decimal digits')
        if (self.no_vig_method != 'proportional' or self.consensus_method != 'equal_weight'
                or self.settlement_policy != 'two_way_no_push' or self.rounding != ROUND_HALF_EVEN):
            raise ValueError('unsupported v1 calculation policy')
        if not isinstance(self.provider_time_policy, ProviderTimePolicy):
            raise ValueError('explicit provider timestamp policy required')
        limits = [self.target_max_age, self.reference_max_age, self.max_input_skew]
        if self.provider_time_policy != ProviderTimePolicy.IGNORE and self.provider_max_age is None:
            raise ValueError('provider maximum age required for timestamp age checks')
        if self.provider_max_age is not None:
            limits.append(self.provider_max_age)
        if any(not isinstance(limit, timedelta) or limit < timedelta(0) for limit in limits):
            raise ValueError('age and skew limits must be nonnegative timedeltas')


@dataclass(frozen=True)
class ReferenceExclusion:
    sportsbook_id: str
    observation_ids: tuple[str, ...]
    issue: InputIssue


@dataclass(frozen=True)
class ReferenceEstimate:
    sportsbook_id: str
    observation_ids: tuple[str, ...]
    outcome_probabilities: tuple[tuple[str, Decimal], ...]


@dataclass(frozen=True)
class EVEvaluation:
    snapshot: EVSnapshot
    configuration: EVConfiguration
    reason: Reason | None
    reference_estimates: tuple[ReferenceEstimate, ...] = ()
    reference_exclusions: tuple[ReferenceExclusion, ...] = ()
    fair_probability: Decimal | None = None
    ev_ratio: Decimal | None = None
    engine_name: str = ENGINE_NAME
    engine_version: str = ENGINE_VERSION


def _quote_issue(quote, evaluated_at, max_age, config):
    if quote.quote_state != 'active':
        return InputIssue.INACTIVE
    price = quote.decimal_odds
    if not isinstance(price, Decimal) or not price.is_finite() or price <= 1:
        return InputIssue.INVALID_PRICE
    age = evaluated_at - quote.observed_at
    if age < timedelta(0):
        return InputIssue.FUTURE_OBSERVATION
    if age > max_age:
        return InputIssue.STALE
    if config.provider_time_policy == ProviderTimePolicy.IGNORE:
        return None
    if quote.provider_updated_at is None:
        if config.provider_time_policy == ProviderTimePolicy.REQUIRE:
            return InputIssue.MISSING_PROVIDER_TIME
        return None
    if quote.provider_updated_at > quote.observed_at:
        return InputIssue.FUTURE_PROVIDER_TIME
    if evaluated_at - quote.provider_updated_at > config.provider_max_age:
        return InputIssue.STALE_PROVIDER_TIME
    return None


def evaluate_ev(snapshot: EVSnapshot, config: EVConfiguration) -> EVEvaluation:
    """Return an auditable estimate or non-evaluation reason without side effects.

    Quotes must already be the trusted-current selection: duplicate streams are
    invalid, rather than an invitation to select older, more usable evidence.
    """
    def rejected(reason, exclusions=()):
        return EVEvaluation(snapshot, config, reason, reference_exclusions=tuple(exclusions))

    quotes = snapshot.quotes
    if (not _aware(snapshot.evaluated_at)
            or any(not _aware(q.observed_at) or
                   (q.provider_updated_at is not None and not _aware(q.provider_updated_at)) for q in quotes)
            or len({q.observation_id for q in quotes}) != len(quotes)
            or len({(q.outcome_id, q.sportsbook_id) for q in quotes}) != len(quotes)):
        return rejected(Reason.INVALID_SNAPSHOT)
    target = next((q for q in quotes if q.observation_id == snapshot.target_observation_id), None)
    contract = snapshot.contract
    if target is None:
        return rejected(Reason.INVALID_SNAPSHOT)
    if (contract.competition_id, contract.market_type, contract.scope) != (
            config.competition_id, config.market_type, config.scope):
        return rejected(Reason.CONFIGURATION_MISMATCH)
    if snapshot.event_phase != 'pregame' or not snapshot.phase_evidence.strip():
        return rejected(Reason.UNSUPPORTED_PHASE)
    outcomes = sorted(contract.outcomes, key=lambda outcome: outcome.outcome_id)
    if (contract.market_type != 'moneyline' or contract.settlement_policy != config.settlement_policy
            or not contract.settlement_evidence.strip() or len(outcomes) != 2
            or len({o.outcome_id for o in outcomes}) != 2
            or len({o.participant_id for o in outcomes}) != 2
            or any(not o.participant_id or o.point is not None for o in outcomes)):
        return rejected(Reason.UNSUPPORTED_SETTLEMENT)
    outcome_ids = {o.outcome_id for o in outcomes}
    if any(q.market_id != contract.market_id or q.outcome_id not in outcome_ids for q in quotes):
        return rejected(Reason.INVALID_SNAPSHOT)
    issue = _quote_issue(target, snapshot.evaluated_at, config.target_max_age, config)
    if issue:
        reason = {
            InputIssue.INACTIVE: Reason.INACTIVE_TARGET,
            InputIssue.STALE: Reason.STALE_TARGET,
            InputIssue.INVALID_PRICE: Reason.INVALID_TARGET_PRICE,
            InputIssue.FUTURE_OBSERVATION: Reason.FUTURE_TARGET,
        }.get(issue, Reason.TARGET_PROVIDER_TIME)
        return rejected(reason)

    included, exclusions = [], []
    for book in sorted(config.reference_sportsbook_ids):
        book_quotes = sorted((q for q in quotes if q.sportsbook_id == book), key=lambda q: q.outcome_id)
        if book == target.sportsbook_id:
            issue = InputIssue.TARGET_BOOK
        elif {q.outcome_id for q in book_quotes} != outcome_ids:
            issue = InputIssue.INCOMPLETE
        else:
            issue = next((problem for q in book_quotes
                          if (problem := _quote_issue(q, snapshot.evaluated_at,
                                                      config.reference_max_age, config))), None)
        if issue:
            exclusions.append(ReferenceExclusion(book, tuple(q.observation_id for q in book_quotes), issue))
        else:
            included.append((book, book_quotes))
    if len(included) < config.minimum_reference_books:
        return rejected(Reason.INSUFFICIENT_REFERENCE_COVERAGE, exclusions)
    times = [target.observed_at] + [q.observed_at for _, group in included for q in group]
    if max(times) - min(times) > config.max_input_skew:
        return rejected(Reason.INPUT_SKEW, exclusions)

    # A fresh Context prevents ambient Decimal precision/rounding from changing results.
    with localcontext(Context(prec=config.calculation_precision, rounding=config.rounding)):
        estimates, target_probabilities = [], []
        for book, group in included:
            implied = [Decimal(1) / q.decimal_odds for q in group]
            total = sum(implied, Decimal(0))
            probabilities = tuple((q.outcome_id, p / total) for q, p in zip(group, implied))
            estimates.append(ReferenceEstimate(book, tuple(q.observation_id for q in group), probabilities))
            target_probabilities.append(dict(probabilities)[target.outcome_id])
        fair = sum(target_probabilities, Decimal(0)) / Decimal(len(target_probabilities))
        ev = fair * target.decimal_odds - Decimal(1)
    return EVEvaluation(snapshot, config, None, tuple(estimates), tuple(exclusions), fair, ev)
