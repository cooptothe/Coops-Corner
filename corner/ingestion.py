"""Fixture-ready canonical ingestion for The Odds API payloads."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable

from psycopg2.extensions import connection as Connection

from corner.normalization import normalize_event


PROVIDER_CODE = "the_odds_api"
SPORT_KEY_MAPPINGS = {
    "americanfootball_nfl": ("american_football", "American Football", "nfl", "NFL"),
    "americanfootball_ncaaf": ("american_football", "American Football", "ncaaf", "NCAA Football"),
    "basketball_nba": ("basketball", "Basketball", "nba", "NBA"),
    "basketball_ncaab": ("basketball", "Basketball", "ncaab", "NCAA Basketball"),
    "baseball_mlb": ("baseball", "Baseball", "mlb", "MLB"),
    "icehockey_nhl": ("ice_hockey", "Ice Hockey", "nhl", "NHL"),
    "soccer_usa_mls": ("soccer", "Soccer", "mls", "MLS"),
    "soccer_epl": ("soccer", "Soccer", "epl", "English Premier League"),
    "soccer_spain_la_liga": ("soccer", "Soccer", "la_liga", "La Liga"),
    "soccer_germany_bundesliga": ("soccer", "Soccer", "bundesliga", "Bundesliga"),
    "soccer_italy_serie_a": ("soccer", "Soccer", "serie_a", "Serie A"),
    "soccer_france_ligue_one": ("soccer", "Soccer", "ligue_one", "Ligue 1"),
    "soccer_uefa_champs_league": ("soccer", "Soccer", "ucl", "UEFA Champions League"),
    "basketball_wncaab": ("basketball", "Basketball", "wncaab", "NCAA Women's Basketball"),
    "basketball_wnba": ("basketball", "Basketball", "wnba", "WNBA"),
    "mma_mixed_martial_arts": ("mma", "MMA", "mma", "MMA"),
}
# Tennis keys are one per tournament and rotate; every ATP/WTA tournament maps to one competition.
_TENNIS = {"tennis_atp_": ("tennis", "Tennis", "atp", "ATP Tennis"), "tennis_wta_": ("tennis", "Tennis", "wta", "WTA Tennis")}


class _SportKeyMappings(dict):
    def __missing__(self, key):
        for prefix, value in _TENNIS.items():
            if key.startswith(prefix):
                return value
        raise KeyError(key)


SPORT_KEY_MAPPINGS = _SportKeyMappings(SPORT_KEY_MAPPINGS)


class UnresolvedParticipantAlias(RuntimeError):
    def __init__(self, raw_names: str | list[str], payload_id: str | None = None):
        self.raw_names = (raw_names,) if isinstance(raw_names, str) else tuple(sorted(raw_names))
        self.raw_name = ", ".join(self.raw_names)
        self.payload_id = payload_id
        super().__init__(f"unresolved provider participant alias: {self.raw_name}")


def ingest_payload(
    conn: Connection,
    raw_body: bytes,
    *,
    received_at: datetime | None = None,
    endpoint_context: dict[str, Any] | None = None,
) -> tuple[str, int]:
    """Record one immutable payload, then normalize it once into observations."""
    received_at = received_at or datetime.now(timezone.utc)
    payload = json.loads(raw_body)
    provider_id = _seed_provider(conn)
    batch_id = _create_batch(conn, provider_id, endpoint_context or {})
    payload_id = _create_payload(conn, batch_id, provider_id, received_at, raw_body)
    try:
        observation_count = process_payload(conn, payload_id, payload)
    except UnresolvedParticipantAlias as error:
        error.payload_id = str(payload_id)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE corner.ingestion_batches
                SET processing_status = 'failed', completed_at = now(),
                    failure_metadata = %s::jsonb
                WHERE id = %s
                """,
                (json.dumps({"reason": "unresolved_participant_alias", "raw_name": error.raw_name}), batch_id),
            )
        conn.commit()
        raise
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE corner.ingestion_batches
            SET processing_status = 'completed', completed_at = now()
            WHERE id = %s
            """,
            (batch_id,),
        )
    conn.commit()
    return str(payload_id), observation_count


def replay_payload(conn: Connection, payload_id: str) -> int:
    """Reprocess an already-recorded payload without creating duplicate quotes."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT raw_body FROM corner.provider_payloads WHERE id = %s",
            (payload_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise ValueError(f"provider payload {payload_id} does not exist")
    count = process_payload(conn, payload_id, json.loads(bytes(row[0])))
    conn.commit()
    return count


def process_payload(conn: Connection, payload_id: str, payload: Any) -> int:
    """Normalize one persisted payload. Replays are idempotent by DB constraint."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT provider_id, received_at FROM corner.provider_payloads WHERE id = %s",
            (payload_id,),
        )
        payload_row = cur.fetchone()
    if payload_row is None:
        raise ValueError(f"provider payload {payload_id} does not exist")
    provider_id, observed_at = payload_row

    count = 0
    events: Iterable[dict[str, Any]] = payload if isinstance(payload, list) else [payload]
    for event in events:
        event_id, competition_id = _resolve_event(conn, provider_id, event)
        participants = _resolve_event_participants(conn, provider_id, competition_id, event_id, event)
        quotes = normalize_event(event)
        subject_participants = {}
        unresolved_aliases = []
        for raw_name in sorted({quote.subject_participant_name for quote in quotes if quote.subject_participant_name}):
            try:
                subject_participants[raw_name] = _resolve_subject_participant(
                    conn, provider_id, competition_id, raw_name
                )
            except UnresolvedParticipantAlias:
                unresolved_aliases.append(raw_name)
        if unresolved_aliases:
            raise UnresolvedParticipantAlias(unresolved_aliases)
        for quote in quotes:
            sportsbook_id = _resolve_sportsbook(conn, provider_id, quote.bookmaker_key, quote.bookmaker_name)
            market_type_code, scope_code = _resolve_provider_market_contract(
                conn, provider_id, quote.provider_market_key
            )
            subject_participant_id = (
                subject_participants[quote.subject_participant_name]
                if quote.subject_participant_name is not None
                else None
            )
            market_id = _resolve_market(
                conn, event_id, market_type_code, scope_code, subject_participant_id
            )
            selected_participant_id = (
                participants[quote.selected_participant_name]
                if quote.selected_participant_name is not None
                else None
            )
            outcome_id = _resolve_outcome(
                conn, market_id, selected_participant_id, quote.outcome_side_code, quote.point
            )
            _insert_observation(
                conn,
                payload_id,
                provider_id,
                outcome_id,
                sportsbook_id,
                quote,
                observed_at,
            )
            count += 1
    return count


def _fetch_id(cur, sql: str, values: tuple[Any, ...]) -> str:
    cur.execute(sql, values)
    return cur.fetchone()[0]


def _seed_provider(conn: Connection) -> str:
    with conn.cursor() as cur:
        provider_id = _fetch_id(
            cur,
            """
            INSERT INTO corner.providers (code, display_name)
            VALUES (%s, %s)
            ON CONFLICT (code) DO UPDATE SET display_name = EXCLUDED.display_name
            RETURNING id
            """,
            (PROVIDER_CODE, "The Odds API"),
        )
        scope_id = _ensure_vocabulary(cur, "scopes", "full_game", "Full Game")
        for provider_key, market_code, display_name in (
            ("h2h", "moneyline", "Moneyline"),
            ("spreads", "spread", "Spread"),
            ("totals", "total", "Total"),
            ("player_pass_tds", "player_pass_tds", "Player Passing Touchdowns"),
        ):
            market_type_id = _ensure_vocabulary(cur, "market_types", market_code, display_name)
            cur.execute(
                """
                INSERT INTO corner.provider_market_mappings (
                    provider_id, provider_market_key, market_type_id, default_scope_id, requires_point
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (provider_id, provider_market_key) DO UPDATE
                SET market_type_id = EXCLUDED.market_type_id,
                    default_scope_id = EXCLUDED.default_scope_id,
                    requires_point = EXCLUDED.requires_point
                """,
                (provider_id, provider_key, market_type_id, scope_id, provider_key in {"spreads", "totals"}),
            )
        return provider_id


def _create_batch(conn: Connection, provider_id: str, endpoint_context: dict[str, Any]) -> str:
    with conn.cursor() as cur:
        return _fetch_id(
            cur,
            """
            INSERT INTO corner.ingestion_batches (provider_id, endpoint_context, processing_status)
            VALUES (%s, %s::jsonb, 'response_received')
            RETURNING id
            """,
            (provider_id, json.dumps(endpoint_context, separators=(",", ":"))),
        )


def _create_payload(
    conn: Connection, batch_id: str, provider_id: str, received_at: datetime, raw_body: bytes
) -> str:
    with conn.cursor() as cur:
        return _fetch_id(
            cur,
            """
            INSERT INTO corner.provider_payloads (
                ingestion_batch_id, provider_id, received_at, http_status,
                content_type, payload_sha256, raw_body
            ) VALUES (%s, %s, %s, 200, 'application/json', %s, %s)
            RETURNING id
            """,
            (batch_id, provider_id, received_at, hashlib.sha256(raw_body).digest(), raw_body),
        )


def _resolve_event(conn: Connection, provider_id: str, event: dict[str, Any]) -> tuple[str, str]:
    sport_code, sport_name, competition_code, competition_name = SPORT_KEY_MAPPINGS[event["sport_key"]]
    with conn.cursor() as cur:
        sport_id = _fetch_id(
            cur,
            """INSERT INTO corner.sports (code, display_name) VALUES (%s, %s)
               ON CONFLICT (code) DO UPDATE SET display_name = EXCLUDED.display_name RETURNING id""",
            (sport_code, sport_name),
        )
        competition_id = _fetch_id(
            cur,
            """INSERT INTO corner.competitions (sport_id, code, display_name) VALUES (%s, %s, %s)
               ON CONFLICT (sport_id, code) DO UPDATE SET display_name = EXCLUDED.display_name RETURNING id""",
            (sport_id, competition_code, competition_name),
        )
        status_id = _ensure_vocabulary(cur, "event_statuses", "scheduled", "Scheduled")
        cur.execute(
            """SELECT event_id FROM corner.event_provider_identities
               WHERE provider_id = %s AND external_id = %s""",
            (provider_id, event["id"]),
        )
        existing = cur.fetchone()
        if existing:
            event_id = existing[0]
            cur.execute(
                """UPDATE corner.events SET competition_id = %s, scheduled_start = %s, event_status_id = %s
                   WHERE id = %s""",
                (competition_id, event["commence_time"], status_id, event_id),
            )
            return event_id, competition_id

        event_id = _fetch_id(
            cur,
            """INSERT INTO corner.events (competition_id, scheduled_start, event_status_id)
               VALUES (%s, %s, %s) RETURNING id""",
            (competition_id, event["commence_time"], status_id),
        )
        cur.execute(
            """INSERT INTO corner.event_provider_identities (provider_id, event_id, external_id, external_name)
               VALUES (%s, %s, %s, %s)""",
            (provider_id, event_id, event["id"], f"{event['away_team']} at {event['home_team']}"),
        )
        return event_id, competition_id


def _resolve_event_participants(
    conn: Connection,
    provider_id: str,
    competition_id: str,
    event_id: str,
    event: dict[str, Any],
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    with conn.cursor() as cur:
        participant_type_id = _ensure_vocabulary(cur, "participant_types", "team", "Team")
        for name, role in ((event["home_team"], "home"), (event["away_team"], "away")):
            cur.execute(
                """SELECT participant_id FROM corner.provider_participant_aliases
                   WHERE provider_id = %s AND competition_id = %s AND raw_name = %s
                     AND participant_id IS NOT NULL
                   ORDER BY created_at DESC LIMIT 1""",
                (provider_id, competition_id, name),
            )
            row = cur.fetchone()
            if row:
                participant_id = row[0]
            else:
                participant_id = _fetch_id(
                    cur,
                    """INSERT INTO corner.participants (participant_type_id, display_name)
                       VALUES (%s, %s) RETURNING id""",
                    (participant_type_id, name),
                )
                cur.execute(
                    """INSERT INTO corner.provider_participant_aliases
                       (provider_id, competition_id, raw_name, participant_id)
                       VALUES (%s, %s, %s, %s)""",
                    (provider_id, competition_id, name, participant_id),
                )
            cur.execute(
                """INSERT INTO corner.event_participants (event_id, participant_id, role)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (event_id, participant_id) DO UPDATE SET role = EXCLUDED.role""",
                (event_id, participant_id, role),
            )
            resolved[name] = participant_id
    return resolved


def _resolve_sportsbook(conn: Connection, provider_id: str, key: str, name: str) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT sportsbook_id FROM corner.sportsbook_provider_identities
               WHERE provider_id = %s AND external_id = %s""",
            (provider_id, key),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        category_id = _ensure_vocabulary(cur, "sportsbook_categories", "unknown", "Unknown")
        sportsbook_id = _fetch_id(
            cur,
            """INSERT INTO corner.sportsbooks (code, display_name, sportsbook_category_id)
               VALUES (%s, %s, %s)
               ON CONFLICT (code) DO UPDATE SET display_name = EXCLUDED.display_name RETURNING id""",
            (key, name, category_id),
        )
        cur.execute(
            """INSERT INTO corner.sportsbook_provider_identities
               (provider_id, sportsbook_id, external_id, external_name)
               VALUES (%s, %s, %s, %s)""",
            (provider_id, sportsbook_id, key, name),
        )
        return sportsbook_id


def _resolve_market(
    conn: Connection,
    event_id: str,
    market_code: str,
    scope_code: str,
    subject_participant_id: str | None = None,
) -> str:
    with conn.cursor() as cur:
        market_type_id = _ensure_vocabulary(cur, "market_types", market_code, market_code.replace("_", " ").title())
        scope_id = _ensure_vocabulary(cur, "scopes", scope_code, scope_code.replace("_", " ").title())
        return _fetch_id(
            cur,
            """INSERT INTO corner.markets (event_id, market_type_id, scope_id, subject_participant_id)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT ON CONSTRAINT markets_contract_key DO UPDATE SET updated_at = now()
               RETURNING id""",
            (event_id, market_type_id, scope_id, subject_participant_id),
        )


def _resolve_provider_market_contract(
    conn: Connection, provider_id: str, provider_market_key: str
) -> tuple[str, str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT market_types.code, scopes.code
            FROM corner.provider_market_mappings AS mappings
            JOIN corner.market_types ON market_types.id = mappings.market_type_id
            JOIN corner.scopes ON scopes.id = mappings.default_scope_id
            WHERE mappings.provider_id = %s
              AND mappings.provider_market_key = %s
              AND mappings.active
            """,
            (provider_id, provider_market_key),
        )
        row = cur.fetchone()
    if row is None:
        raise ValueError(f"no active Corner mapping for provider market {provider_market_key!r}")
    return row[0], row[1]


def _resolve_subject_participant(
    conn: Connection, provider_id: str, competition_id: str, raw_name: str
) -> str:
    """Resolve only a deliberately reconciled player alias; never invent a player."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, participant_id
            FROM corner.provider_participant_aliases
            WHERE provider_id = %s AND competition_id = %s AND raw_name = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (provider_id, competition_id, raw_name),
        )
        alias = cur.fetchone()
        if alias and alias[1] is not None:
            return alias[1]
        if alias is None:
            cur.execute(
                """
                INSERT INTO corner.provider_participant_aliases (provider_id, competition_id, raw_name)
                VALUES (%s, %s, %s)
                """,
                (provider_id, competition_id, raw_name),
            )
    raise UnresolvedParticipantAlias(raw_name)


def resolve_player_alias(
    conn: Connection, *, sport_key: str, raw_name: str, display_name: str | None = None
) -> str:
    """Explicitly attach a raw provider player name to one canonical Participant."""
    sport_code, sport_name, competition_code, competition_name = SPORT_KEY_MAPPINGS[sport_key]
    provider_id = _seed_provider(conn)
    with conn.cursor() as cur:
        sport_id = _fetch_id(
            cur,
            """INSERT INTO corner.sports (code, display_name) VALUES (%s, %s)
               ON CONFLICT (code) DO UPDATE SET display_name = EXCLUDED.display_name RETURNING id""",
            (sport_code, sport_name),
        )
        competition_id = _fetch_id(
            cur,
            """INSERT INTO corner.competitions (sport_id, code, display_name) VALUES (%s, %s, %s)
               ON CONFLICT (sport_id, code) DO UPDATE SET display_name = EXCLUDED.display_name RETURNING id""",
            (sport_id, competition_code, competition_name),
        )
        cur.execute(
            """SELECT id, participant_id FROM corner.provider_participant_aliases
               WHERE provider_id = %s AND competition_id = %s AND raw_name = %s
               ORDER BY created_at DESC LIMIT 1""",
            (provider_id, competition_id, raw_name),
        )
        alias = cur.fetchone()
        if alias and alias[1] is not None:
            return alias[1]
        participant_type_id = _ensure_vocabulary(cur, "participant_types", "player", "Player")
        participant_id = _fetch_id(
            cur,
            """INSERT INTO corner.participants (participant_type_id, display_name)
               VALUES (%s, %s) RETURNING id""",
            (participant_type_id, display_name or raw_name),
        )
        if alias:
            cur.execute(
                """UPDATE corner.provider_participant_aliases SET participant_id = %s WHERE id = %s""",
                (participant_id, alias[0]),
            )
        else:
            cur.execute(
                """INSERT INTO corner.provider_participant_aliases
                   (provider_id, competition_id, raw_name, participant_id)
                   VALUES (%s, %s, %s, %s)""",
                (provider_id, competition_id, raw_name, participant_id),
            )
    conn.commit()
    return participant_id


def _resolve_outcome(
    conn: Connection, market_id: str, participant_id: str | None, side_code: str, point: Any
) -> str:
    with conn.cursor() as cur:
        side_id = _ensure_vocabulary(cur, "outcome_sides", side_code, side_code.title())
        return _fetch_id(
            cur,
            """INSERT INTO corner.outcomes (market_id, selected_participant_id, outcome_side_id, point)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT ON CONSTRAINT outcomes_contract_key DO UPDATE SET updated_at = now()
               RETURNING id""",
            (market_id, participant_id, side_id, point),
        )


def _insert_observation(
    conn: Connection,
    payload_id: str,
    provider_id: str,
    outcome_id: str,
    sportsbook_id: str,
    quote,
    observed_at: datetime,
) -> None:
    with conn.cursor() as cur:
        quote_state_id = _ensure_vocabulary(
            cur, "quote_states", quote.quote_state_code, quote.quote_state_code.title()
        )
        cur.execute(
            """INSERT INTO corner.odds_observations (
                   provider_payload_id, provider_id, outcome_id, sportsbook_id, quote_state_id,
                   source_record_key, decimal_odds, provider_updated_at, observed_at
               ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT ON CONSTRAINT odds_observations_payload_source_key DO NOTHING""",
            (
                payload_id,
                provider_id,
                outcome_id,
                sportsbook_id,
                quote_state_id,
                quote.source_record_key,
                quote.decimal_odds,
                quote.provider_updated_at,
                observed_at,
            ),
        )


def _ensure_vocabulary(cur, table: str, code: str, display_name: str) -> str:
    allowed = {
        "event_statuses",
        "market_types",
        "outcome_sides",
        "participant_types",
        "quote_states",
        "scopes",
        "sportsbook_categories",
    }
    if table not in allowed:
        raise ValueError(f"unsupported vocabulary table: {table}")
    return _fetch_id(
        cur,
        f"""INSERT INTO corner.{table} (code, display_name) VALUES (%s, %s)
            ON CONFLICT (code) DO UPDATE SET display_name = EXCLUDED.display_name
            RETURNING id""",
        (code, display_name),
    )
