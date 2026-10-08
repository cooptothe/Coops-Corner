"""Six-market ingestion into existing canonical observation/trust ledgers.

Caller retains ProviderPayload first and owns commit/rollback. No registry writes,
provider calls, implicit trust decisions, or production authorization are added.
Lay direction is isolated by market type, so existing stream keys remain valid.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
import hashlib
from uuid import uuid4

from psycopg2.extras import RealDictCursor, execute_values

from corner.featured_markets import normalize_featured_payload
from corner.featured_matching import BindingError, MARKET_TYPES, QuoteBinding, identity, require

SOURCE_PREFIX = "featured-v1:"


class FeaturedConflict(BindingError):
    pass


@dataclass(frozen=True)
class IngestionReceipt:
    payload_id: str
    observation_ids: tuple[str, ...]
    excluded_market_count: int


def _transaction(conn):
    require(not conn.autocommit, "caller-owned transaction required")
    require(conn.isolation_level in (None, 1), "READ COMMITTED required")


def _payload(cur, payload_id):
    cur.execute('''SELECT p.*, provider.code AS provider_code FROM corner.provider_payloads p
                   JOIN corner.providers provider ON provider.id=p.provider_id WHERE p.id=%s''', (payload_id,))
    row = cur.fetchone()
    require(row is not None and row['provider_code'] == 'the_odds_api', "Odds API payload required")
    require(row['http_status'] == 200, "successful retained response required")
    raw = bytes(row['raw_body'])
    require(hashlib.sha256(raw).digest() == bytes(row['payload_sha256']), "retained payload digest mismatch")
    return row, normalize_featured_payload(raw, received_at=row['received_at'])


def _lookup(cur, cache, many, sql, params):
    """A read-only lookup, answered once per ingestion call.

    The same outcome, event, competition, sportsbook, alias and role are checked for every market and side that
    mentions them. Inside one caller-owned transaction the identical statement returns the identical rows, so
    repeating it is pure overhead; every check still runs against the (reused) result.
    """
    key = (sql, params)
    if cache is not None and key in cache:
        return cache[key]
    cur.execute(sql, params)
    result = cur.fetchall() if many else cur.fetchone()
    if cache is not None:
        cache[key] = result
    return result


def _validate_registry(cur, provider_id, quote, binding, cache=None):
    row = _lookup(cur, cache, False, '''SELECT o.market_id, o.point, o.selected_participant_id, side.code AS side,
                          m.event_id, m.subject_participant_id, mt.code AS market_type, scope.code AS scope,
                          e.competition_id
                   FROM corner.outcomes o JOIN corner.outcome_sides side ON side.id=o.outcome_side_id
                   JOIN corner.markets m ON m.id=o.market_id JOIN corner.market_types mt ON mt.id=m.market_type_id
                   JOIN corner.scopes scope ON scope.id=m.scope_id JOIN corner.events e ON e.id=m.event_id
                   WHERE o.id=%s''', (binding.outcome_id,))
    require(row is not None, "unknown canonical outcome")
    require(str(row['market_id']) == binding.market_id and row['market_type'] == MARKET_TYPES[quote.market_key]
            and row['scope'] == quote.scope and row['subject_participant_id'] is None,
            "canonical market, direction or scope mismatch")
    require(row['point'] == quote.point and row['side'] == quote.selection_side, "canonical outcome/line mismatch")
    for table, column, canonical, external in (
        ('event_provider_identities', 'event_id', row['event_id'], quote.event_id),
        ('competition_provider_identities', 'competition_id', row['competition_id'], quote.sport_key),
        ('sportsbook_provider_identities', 'sportsbook_id', binding.sportsbook_id, quote.bookmaker_key)):
        # Table and column names are constants above; values are always parameters.
        found = _lookup(cur, cache, False, f'''SELECT 1 FROM corner.{table} WHERE provider_id=%s AND {column}=%s
                         AND external_id=%s AND active''', (provider_id, canonical, external))
        require(found is not None, "missing or incompatible active provider identity")
    participant = row['selected_participant_id']
    if quote.selection_side in {'home', 'away', 'entrant'}:
        require(participant is not None, "selected participant required")
        found = _lookup(cur, cache, True, '''SELECT DISTINCT participant_id FROM corner.provider_participant_aliases
                       WHERE provider_id=%s AND competition_id=%s AND raw_name=%s''',
                        (provider_id, row['competition_id'], quote.selection_name))
        aliases = {str(alias['participant_id']) if alias['participant_id'] is not None else None for alias in found}
        require(aliases == {str(participant)}, "unresolved or ambiguous participant alias")
        membership = _lookup(cur, cache, False, '''SELECT role FROM corner.event_participants WHERE event_id=%s AND participant_id=%s''',
                             (row['event_id'], participant))
        require(membership is not None and membership['role'] == ('competitor' if quote.selection_side == 'entrant' else quote.selection_side),
                "participant does not belong to the expected event role")
    else:
        require(participant is None, "draw/total must not select a participant")


def _exact_sql_price(price):
    require(price <= Decimal('999999.999999') and (Fraction(price) * 1_000_000).denominator == 1,
            "price cannot be represented exactly in NUMERIC(12,6)")


def ingest_featured_payload(conn, *, payload_id, bindings):
    """Idempotent by retained payload ID, with exact binding comparison on replay.

    Validates every featured quote before any insert. An existing partial/mixed
    ingestion is a conflict, not permission to fill or overwrite historical rows.
    Retries return original IDs without resolving today's mutable identity aliases.
    """
    _transaction(conn)
    identity(payload_id)
    bindings = tuple(bindings)
    require(all(type(b) is QuoteBinding for b in bindings), "typed quote bindings required")
    by_source = {b.source_pointer: b for b in bindings}
    require(len(by_source) == len(bindings), "duplicate source bindings")
    savepoint = 'featured_' + uuid4().hex
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(f'SAVEPOINT {savepoint}')
        try:
            # Serialize without granting UPDATE on an immutable payload table.
            cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ('corner.featured:' + payload_id,))
            payload, snapshot = _payload(cur, payload_id)
            require(set(by_source) == {q.source_pointer for q in snapshot.quotes}, "bind every featured quote exactly once")
            cur.execute('''SELECT o.*, q.code AS state, m.id AS market_id FROM corner.odds_observations o
                           JOIN corner.quote_states q ON q.id=o.quote_state_id
                           JOIN corner.outcomes outcome ON outcome.id=o.outcome_id
                           JOIN corner.markets m ON m.id=outcome.market_id
                           WHERE o.provider_payload_id=%s''', (payload_id,))
            existing = {row['source_record_key']: row for row in cur.fetchall()}
            ordered = []
            if existing:
                if set(existing) != {SOURCE_PREFIX + q.source_pointer for q in snapshot.quotes}:
                    raise FeaturedConflict("payload already has partial or different ingestion")
                for quote in snapshot.quotes:
                    row, binding = existing[SOURCE_PREFIX + quote.source_pointer], by_source[quote.source_pointer]
                    expected = (binding.market_id, binding.outcome_id, binding.sportsbook_id, 'active', quote.decimal_odds,
                                quote.observed_at, quote.provider_updated_at)
                    actual = (str(row['market_id']), str(row['outcome_id']), str(row['sportsbook_id']), row['state'],
                              row['decimal_odds'], row['observed_at'], row['provider_updated_at'])
                    if actual != expected:
                        raise FeaturedConflict("replay changes original binding or observation")
                    ordered.append(str(row['id']))
            else:
                seen = {}
                for quote in snapshot.quotes:
                    _exact_sql_price(quote.decimal_odds)
                    _validate_registry(cur, payload['provider_id'], quote, by_source[quote.source_pointer], seen)
                cur.execute("SELECT id FROM corner.quote_states WHERE code='active'")
                state = cur.fetchone()
                require(state is not None, "active quote state must be provisioned")
                rows = [(payload_id, payload['provider_id'], by_source[q.source_pointer].outcome_id,
                         by_source[q.source_pointer].sportsbook_id, state['id'], SOURCE_PREFIX + q.source_pointer,
                         q.decimal_odds, q.provider_updated_at, q.observed_at) for q in snapshot.quotes]
                # One batched insert; ids are matched back by source key, so the receipt keeps the quotes' order.
                stored = execute_values(cur, '''INSERT INTO corner.odds_observations
                    (provider_payload_id,provider_id,outcome_id,sportsbook_id,quote_state_id,source_record_key,
                     decimal_odds,provider_updated_at,observed_at)
                    VALUES %s RETURNING source_record_key, id''', rows, page_size=1000, fetch=True)
                ids = {row['source_record_key']: str(row['id']) for row in stored}
                ordered = [ids[SOURCE_PREFIX + q.source_pointer] for q in snapshot.quotes]
            cur.execute(f'RELEASE SAVEPOINT {savepoint}')
            return IngestionReceipt(payload_id, tuple(ordered), len(snapshot.excluded_markets))
        except Exception:
            cur.execute(f'ROLLBACK TO SAVEPOINT {savepoint}')
            cur.execute(f'RELEASE SAVEPOINT {savepoint}')
            raise


@dataclass(frozen=True)
class QuoteStream:
    outcome_id: str
    sportsbook_id: str
    observation_id: str | None
    state: str
    decimal_odds: Decimal | None
    observed_at: datetime | None
    provider_updated_at: datetime | None
    reason: str | None
    provider_payload_id: str | None = None
    provider_id: str | None = None
    source_record_key: str | None = None


def read_featured_streams(conn, *, streams, assessed_at, max_age):
    """One-statement trusted-current read; missing/stale/unavailable stay explicit.

    Supplied stream pairs are the expected universe, not whatever rows happen to
    exist. No fallback to an older price, no persistence, no approval assessment.
    Freshness here is observation-age only, inclusive at max_age; provider update
    timestamps remain available for a later explicit provider-age policy.
    """
    require(isinstance(assessed_at, datetime) and assessed_at.tzinfo is not None
            and assessed_at.utcoffset() is not None, "aware assessment time required")
    require(isinstance(max_age, timedelta) and max_age >= timedelta(0), "nonnegative max age required")
    streams = tuple(streams)
    for outcome, book in streams:
        identity(outcome)
        identity(book)
    require(len(set(streams)) == len(streams), "duplicate expected stream")
    if not streams:
        return ()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute('''WITH expected AS (SELECT * FROM unnest(%s::uuid[],%s::uuid[]) AS s(outcome_id,sportsbook_id))
            SELECT s.outcome_id,s.sportsbook_id, t.observation_id,t.decimal_odds,t.observed_at,t.provider_updated_at,
                   qs.code AS state, mt.code AS market_type, sb.id AS book_exists,
                   scope.code AS scope, m.subject_participant_id,
                   t.provider_payload_id,t.provider_id,observation.source_record_key
            FROM expected s LEFT JOIN corner.outcomes o ON o.id=s.outcome_id
            LEFT JOIN corner.markets m ON m.id=o.market_id LEFT JOIN corner.market_types mt ON mt.id=m.market_type_id
            LEFT JOIN corner.scopes scope ON scope.id=m.scope_id
            LEFT JOIN corner.sportsbooks sb ON sb.id=s.sportsbook_id
            LEFT JOIN corner.trusted_current_quotes t ON t.outcome_id=s.outcome_id AND t.sportsbook_id=s.sportsbook_id
            LEFT JOIN corner.odds_observations observation ON observation.id=t.observation_id
            LEFT JOIN corner.quote_states qs ON qs.id=t.quote_state_id''',
                    ([s[0] for s in streams], [s[1] for s in streams]))
        rows = {(str(row['outcome_id']), str(row['sportsbook_id'])): row for row in cur.fetchall()}
    result = []
    for outcome, book in streams:
        row = rows[(outcome, book)]
        require(row['market_type'] in MARKET_TYPES.values() and row['book_exists'] is not None,
                "unknown or out-of-scope canonical stream")
        require(row['scope']==('competition' if row['market_type'] in {'outright','outright_lay'} else 'full_game')
                and row['subject_participant_id'] is None, "non-featured scope or subject")
        if row['observation_id'] is None:
            result.append(QuoteStream(outcome,book,None,'missing',None,None,None,'missing_trusted_observation'))
            continue
        reason = None
        if row['state'] != 'active':
            reason = 'quote_' + row['state']
        elif row['observed_at'] > assessed_at:
            reason = 'future_observation'
        elif row['provider_updated_at'] is not None and row['provider_updated_at'] > row['observed_at']:
            reason = 'future_provider_timestamp'
        elif assessed_at - row['observed_at'] > max_age:
            reason = 'stale_observation'
        result.append(QuoteStream(outcome,book,str(row['observation_id']),row['state'],row['decimal_odds'],
                                  row['observed_at'],row['provider_updated_at'],reason,
                                  str(row['provider_payload_id']),str(row['provider_id']),row['source_record_key']))
    return tuple(result)
