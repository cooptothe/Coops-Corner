"""Read current trusted evidence in one SQL statement and assemble EV inputs.

This is a current-state selector, not an historical as-of query. evaluated_at is
the engine's explicit evaluation clock, not a database visibility cutoff. The
caller owns the transaction; selection never commits or changes database state.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from psycopg2.extras import RealDictCursor

from corner.ev import EVConfiguration, EVSnapshot, MarketContract, OutcomeContract, QuoteInput


@dataclass(frozen=True)
class MarketValidation:
    """Assertions supplied by a trusted phase/rules adapter, bound to a market.

    No such production validator exists yet. Tests use explicitly synthetic
    validation. Do not infer these values from event.status or quote counts.
    """

    event_id: str
    market_id: str
    event_phase: str
    phase_evidence: str
    settlement_policy: str
    settlement_evidence: str


class SelectionReason(str, Enum):
    UNKNOWN_TARGET_OUTCOME = 'unknown_target_outcome'
    NO_TRUSTED_TARGET = 'no_trusted_target'
    VALIDATION_MISMATCH = 'validation_mismatch'
    CONFIGURATION_MISMATCH = 'configuration_mismatch'


@dataclass(frozen=True)
class SnapshotSelection:
    evaluated_at: datetime
    target_outcome_id: str
    target_sportsbook_id: str
    configuration: EVConfiguration
    validation: MarketValidation
    snapshot: EVSnapshot | None
    reason: SelectionReason | None


_SELECT = '''
    SELECT m.id AS market_id, m.event_id, e.competition_id,
           mt.code AS market_type, s.code AS scope,
           o.id AS outcome_id, o.selected_participant_id, o.point,
           q.observation_id, q.sportsbook_id, q.decimal_odds,
           qs.code AS quote_state, q.observed_at, q.provider_updated_at
    FROM corner.outcomes target
    JOIN corner.markets m ON m.id = target.market_id
    JOIN corner.events e ON e.id = m.event_id
    JOIN corner.market_types mt ON mt.id = m.market_type_id
    JOIN corner.scopes s ON s.id = m.scope_id
    JOIN corner.outcomes o ON o.market_id = m.id
    LEFT JOIN corner.trusted_current_quotes q ON q.outcome_id = o.id AND (
        (q.outcome_id = target.id AND q.sportsbook_id = %(target_book)s::uuid)
        OR (q.sportsbook_id = ANY(%(reference_books)s::uuid[])
            AND q.sportsbook_id <> %(target_book)s::uuid)
    )
    LEFT JOIN corner.quote_states qs ON qs.id = q.quote_state_id
    WHERE target.id = %(target_outcome)s::uuid
    ORDER BY o.id, q.sportsbook_id
'''


def select_ev_snapshot(conn, *, target_outcome_id: str, target_sportsbook_id: str,
                       evaluated_at: datetime, configuration: EVConfiguration,
                       validation: MarketValidation) -> SnapshotSelection:
    """Select evidence without applying state, age, price, or coverage filters.

    All canonical outcomes survive the LEFT JOIN, even if no reference currently
    prices them. One statement supplies a consistent MVCC snapshot across target,
    references, contracts and dispositions at READ COMMITTED or stronger.
    """
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError('evaluated_at must include a timezone')

    def result(snapshot=None, reason=None):
        return SnapshotSelection(evaluated_at, target_outcome_id, target_sportsbook_id,
                                 configuration, validation, snapshot, reason)

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(_SELECT, {
            'target_outcome': target_outcome_id,
            'target_book': target_sportsbook_id,
            'reference_books': list(configuration.reference_sportsbook_ids),
        })
        rows = cur.fetchall()
    if not rows:
        return result(reason=SelectionReason.UNKNOWN_TARGET_OUTCOME)
    header = rows[0]
    if (header['event_id'], header['market_id']) != (validation.event_id, validation.market_id):
        return result(reason=SelectionReason.VALIDATION_MISMATCH)
    if (header['competition_id'], header['market_type'], header['scope']) != (
            configuration.competition_id, configuration.market_type, configuration.scope):
        return result(reason=SelectionReason.CONFIGURATION_MISMATCH)

    outcomes, quotes = {}, []
    for row in rows:
        outcomes[row['outcome_id']] = OutcomeContract(
            row['outcome_id'], row['selected_participant_id'], row['point'])
        if row['observation_id'] is not None:
            quotes.append(QuoteInput(
                row['observation_id'], row['market_id'], row['outcome_id'], row['sportsbook_id'],
                row['decimal_odds'], row['quote_state'], row['observed_at'], row['provider_updated_at']))
    target = next((q for q in quotes if q.outcome_id == target_outcome_id
                   and q.sportsbook_id == target_sportsbook_id), None)
    if target is None:
        return result(reason=SelectionReason.NO_TRUSTED_TARGET)
    contract = MarketContract(header['market_id'], header['competition_id'], header['market_type'],
                              header['scope'], validation.settlement_policy,
                              validation.settlement_evidence, tuple(outcomes.values()))
    return result(snapshot=EVSnapshot(evaluated_at, validation.event_phase,
                                      validation.phase_evidence, contract,
                                      target.observation_id, tuple(quotes)))
