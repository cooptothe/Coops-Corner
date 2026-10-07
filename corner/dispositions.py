"""Append eligibility decisions. The caller owns transaction commit/rollback.

Use READ COMMITTED (the psycopg2 default). At stricter isolation levels the
caller must retry serialization failures with the same command/key.
Authority must be built by a trusted authentication adapter, never deserialized
from request JSON. This module supplies persistence, not authentication.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from psycopg2.extras import Json, RealDictCursor


@dataclass(frozen=True)
class DecisionAuthority:
    kind: str
    identifier: str


@dataclass(frozen=True)
class DispositionCommand:
    decision_key: str
    observation_id: str
    disposition: str
    reason: str
    decided_at: datetime
    authority_metadata: dict[str, Any] | None = None


class IdempotencyConflict(ValueError):
    """An authority reused a decision key for a different command."""


def record_disposition(conn, *, authority: DecisionAuthority, command: DispositionCommand):
    if command.decided_at.tzinfo is None or command.decided_at.utcoffset() is None:
        raise ValueError('decided_at must include a timezone')
    if command.disposition not in {'rejected', 'reinstated'}:
        raise ValueError('unsupported disposition')
    if authority.kind not in {'human', 'service'}:
        raise ValueError('unsupported authority kind')
    for value in (authority.identifier, command.decision_key, command.reason):
        if not isinstance(value, str) or not value.strip():
            raise ValueError('authority identifier, decision key, and reason must be nonblank')
    metadata = Json(command.authority_metadata) if command.authority_metadata is not None else None
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute('SELECT id FROM corner.disposition_types WHERE code = %s', (command.disposition,))
        disposition_type_id = cur.fetchone()['id']
        values = (command.observation_id, disposition_type_id, command.reason,
                  command.decided_at, metadata)
        key = (authority.kind, authority.identifier, command.decision_key)
        cur.execute('''
            INSERT INTO corner.observation_dispositions
                (observation_id, disposition_type_id, reason, decided_at, authority_metadata,
                 authority_kind, authority_id, decision_key)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT ON CONSTRAINT observation_dispositions_command_key DO NOTHING
            RETURNING *
        ''', values + key)
        inserted = cur.fetchone()
        if inserted is not None:
            return dict(inserted)
        # Separate statement sees the winning concurrent insert at READ COMMITTED.
        cur.execute('''
            SELECT d.*, (
                observation_id = %s::uuid AND disposition_type_id = %s::uuid
                AND reason = %s AND decided_at = %s::timestamptz
                AND authority_metadata IS NOT DISTINCT FROM %s::jsonb
            ) AS identical_command
            FROM corner.observation_dispositions d
            WHERE authority_kind = %s AND authority_id = %s AND decision_key = %s
        ''', values + key)
        existing = cur.fetchone()
        if existing is None:
            raise RuntimeError('retry the transaction: conflicting command is outside its snapshot')
        result = dict(existing)
        if not result.pop('identical_command'):
            raise IdempotencyConflict('decision key already identifies a different command')
        return result
