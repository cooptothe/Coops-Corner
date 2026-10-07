"""Channel registration, serialized activation, and qualified-only occurrences.

Caller owns a READ COMMITTED transaction and supplies trusted authority. No fan-out,
condition processing or lifecycle transitions occur here. Savepoints contain failed
writes; successful channel locks remain held until the caller commits/rolls back.
"""

import json
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from uuid import UUID

from psycopg2.extras import Json, RealDictCursor

from corner import evaluations as serialization
from corner.ev import EVConfiguration
from corner.lifecycle import ActionabilityPolicy, ImplementationIdentity
from corner.qualifications import MinimumEVPolicy


REGISTRATION_FORMAT = 'corner.channel.registration/1'
CONFIGURATION_FORMAT = 'corner.channel.configuration/1'
ACTIVATION_FORMAT = 'corner.channel.activation/1'


class ChannelValidationError(ValueError):
    pass


class ChannelConflict(ValueError):
    """An existing identity/key has different content."""


class ActivationConflict(ValueError):
    """Predecessor CAS, chronological activation, or no-reactivation rule failed."""


@dataclass(frozen=True)
class ChannelAuthority:
    kind: str
    identifier: str


@dataclass(frozen=True)
class GenerationConfiguration:
    engine: ImplementationIdentity
    engine_configuration: EVConfiguration
    qualification_implementation: ImplementationIdentity
    qualification_policy: MinimumEVPolicy
    actionability_policy: ActionabilityPolicy

    def __post_init__(self):
        for value, expected in ((self.engine, ImplementationIdentity),
            (self.engine_configuration, EVConfiguration),
            (self.qualification_implementation, ImplementationIdentity),
            (self.qualification_policy, MinimumEVPolicy), (self.actionability_policy, ActionabilityPolicy)):
            if not isinstance(value, expected):
                raise ChannelValidationError(f'configuration requires {expected.__name__}')


@dataclass(frozen=True)
class GenerationRegistration:
    channel_id: str
    configuration: GenerationConfiguration
    context_json: str = '{}'


@dataclass(frozen=True)
class ActivationCommand:
    channel_id: str
    new_generation_id: str
    expected_previous_generation_id: str | None
    activated_at: datetime
    context_json: str = '{}'


def _text(*values):
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ChannelValidationError('nonblank identity/text fields required')


def _uuid(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as error:
        raise ChannelValidationError('canonical UUID required') from error


def _authority(authority, key):
    _text(authority.identifier, key)
    if authority.kind not in {'human', 'service'}:
        raise ChannelValidationError('trusted human/service authority required')
    return authority.kind, authority.identifier, key


def _context(text):
    try:
        value = json.loads(text, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        if not isinstance(value, dict):
            raise ValueError('context must be an object')
        return serialization._encode(value, identifiers=False)
    except (ValueError, TypeError) as error:
        raise ChannelValidationError('context must be a JSON object without floating-point values') from error


def configuration_snapshot(configuration):
    if not isinstance(configuration, GenerationConfiguration):
        raise ChannelValidationError('validated generation configuration required')
    engine_config = serialization._encode(asdict(configuration.engine_configuration))
    engine_config['reference_sportsbook_ids'] = sorted(_uuid(book) for book in engine_config['reference_sportsbook_ids'])
    qualifier = configuration.qualification_policy
    lifecycle = configuration.actionability_policy
    return {
        'snapshot_format_version': CONFIGURATION_FORMAT,
        'engine': {'implementation': asdict(configuration.engine), 'configuration': engine_config},
        'qualification': {'implementation': asdict(configuration.qualification_implementation),
            'configuration': {'policy_name': 'minimum_ev', 'policy_version': qualifier.version,
                'minimum_ev_ratio': serialization._decimal(qualifier.minimum_ev_ratio),
                'comparison': 'greater_than_or_equal'}},
        'lifecycle': {'implementation': asdict(lifecycle.identity), 'configuration': {
            'target_max_age_microseconds': serialization._encode(lifecycle.target_max_age),
            'reference_max_age_microseconds': serialization._encode(lifecycle.reference_max_age)}},
    }


def registration_snapshot(command):
    config = configuration_snapshot(command.configuration)
    return {'snapshot_format_version': REGISTRATION_FORMAT, 'channel_id': _uuid(command.channel_id),
            'configuration': config, 'configuration_sha256': serialization._digest(config).hex(),
            'context': _context(command.context_json)}


def activation_snapshot(command):
    when = command.activated_at
    if not isinstance(when, datetime) or when.tzinfo is None or when.utcoffset() is None:
        raise ChannelValidationError('activated_at must have an explicit timezone')
    return {'snapshot_format_version': ACTIVATION_FORMAT, 'channel_id': _uuid(command.channel_id),
        'new_generation_id': _uuid(command.new_generation_id),
        'expected_previous_generation_id': (_uuid(command.expected_previous_generation_id)
                                            if command.expected_previous_generation_id is not None else None),
        'activated_at': serialization._encode(when), 'context': _context(command.context_json)}


@contextmanager
def _write(conn, name):
    # All names are module constants, never caller-controlled SQL fragments.
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute('SAVEPOINT ' + name)
        try:
            yield cur
            cur.execute('RELEASE SAVEPOINT ' + name)
        except Exception:
            cur.execute('ROLLBACK TO SAVEPOINT ' + name)
            cur.execute('RELEASE SAVEPOINT ' + name)
            raise


def _retry(row, document, prefix=''):
    if row is None:
        raise RuntimeError('retry transaction: concurrent writer is outside this snapshot')
    if (bytes(row[prefix + 'command_sha256']) != serialization._digest(document)
            or row[prefix + 'command_snapshot'] != document):
        raise ChannelConflict('authority/key identifies a different command')
    return dict(row)


def create_channel(conn, *, code, display_name):
    """Idempotent canonical identity creation; never overwrite existing metadata."""
    _text(code, display_name)
    with _write(conn, 'corner_channel_create') as cur:
        cur.execute('''INSERT INTO corner.qualification_channels (code, display_name) VALUES (%s,%s)
            ON CONFLICT (code) DO NOTHING RETURNING *''', (code, display_name))
        row = cur.fetchone()
        if row is None:
            cur.execute('SELECT * FROM corner.qualification_channels WHERE code=%s', (code,))
            row = cur.fetchone()
            if row is None:
                raise RuntimeError('retry transaction: channel is outside snapshot')
            if row['display_name'] != display_name:
                raise ChannelConflict('channel code already has different metadata')
        return dict(row)


def register_generation(conn, *, authority: ChannelAuthority, registration_key: str,
                        command: GenerationRegistration):
    key = _authority(authority, registration_key)
    document = registration_snapshot(command)
    config = document['configuration']
    identities = tuple(config[part]['implementation'][field]
                       for part in ('engine', 'qualification', 'lifecycle')
                       for field in ('name', 'version', 'revision'))
    with _write(conn, 'corner_generation_register') as cur:
        cur.execute('''INSERT INTO corner.qualification_channel_generations
            (channel_id, engine_name, engine_version, engine_revision,
             qualification_name, qualification_version, qualification_revision,
             lifecycle_name, lifecycle_version, lifecycle_revision, snapshot_format_version,
             configuration_snapshot, configuration_sha256,
             registration_authority_kind, registration_authority_id, registration_key,
             registration_command_snapshot, registration_command_sha256)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT ON CONSTRAINT channel_generations_registration_key DO NOTHING RETURNING *''',
            (document['channel_id'],) + identities + (CONFIGURATION_FORMAT, Json(config), serialization._digest(config))
            + key + (Json(document), serialization._digest(document)))
        row = cur.fetchone()
        if row is not None:
            return dict(row)
        cur.execute('''SELECT * FROM corner.qualification_channel_generations
            WHERE registration_authority_kind=%s AND registration_authority_id=%s AND registration_key=%s''', key)
        return _retry(cur.fetchone(), document, 'registration_')


def activate_generation(conn, *, authority: ChannelAuthority, activation_key: str, command: ActivationCommand):
    key = _authority(authority, activation_key)
    document = activation_snapshot(command)
    channel = document['channel_id']
    new_generation = document['new_generation_id']
    previous = document['expected_previous_generation_id']
    with _write(conn, 'corner_generation_activate') as cur:
        # Lock the stable identity, not a mutable authoritative current pointer.
        cur.execute('SELECT id FROM corner.qualification_channels WHERE id=%s FOR UPDATE', (channel,))
        if cur.fetchone() is None:
            raise ChannelValidationError('channel does not exist')
        cur.execute('''SELECT * FROM corner.channel_generation_activations
            WHERE authority_kind=%s AND authority_id=%s AND activation_key=%s''', key)
        existing = cur.fetchone()
        if existing is not None:
            return _retry(existing, document)  # BEFORE predecessor/time/reactivation validation.
        cur.execute('''SELECT * FROM corner.channel_generation_activations
            WHERE channel_id=%s ORDER BY activation_sequence DESC LIMIT 1''', (channel,))
        head = cur.fetchone()
        if previous != (head['new_generation_id'] if head is not None else None):
            raise ActivationConflict('expected predecessor is not the current channel generation')
        if head is not None and command.activated_at < head['activated_at']:
            raise ActivationConflict('activation time precedes predecessor activation')
        cur.execute('SELECT channel_id FROM corner.qualification_channel_generations WHERE id=%s', (new_generation,))
        generation = cur.fetchone()
        if generation is None or generation['channel_id'] != channel:
            raise ChannelValidationError('new generation must exist in this channel')
        cur.execute('SELECT id FROM corner.channel_generation_activations WHERE new_generation_id=%s', (new_generation,))
        if cur.fetchone() is not None:
            raise ActivationConflict('generation has already been activated')
        sequence = head['activation_sequence'] + 1 if head is not None else 1
        cur.execute('''INSERT INTO corner.channel_generation_activations
            (channel_id, new_generation_id, expected_previous_generation_id, activation_sequence,
             activated_at, authority_kind, authority_id, activation_key, snapshot_format_version,
             command_snapshot, command_sha256)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT ON CONSTRAINT channel_activations_command_key DO NOTHING RETURNING *''',
            (channel, new_generation, previous, sequence, command.activated_at) + key
            + (ACTIVATION_FORMAT, Json(document), serialization._digest(document)))
        row = cur.fetchone()
        if row is not None:
            return dict(row)
        # Another channel can race on the same authority-scoped key. The unique
        # winner is compared rather than treating a changed command as a retry.
        cur.execute('''SELECT * FROM corner.channel_generation_activations
            WHERE authority_kind=%s AND authority_id=%s AND activation_key=%s''', key)
        return _retry(cur.fetchone(), document)


def create_occurrence(conn, *, qualification_decision_id):
    decision = _uuid(qualification_decision_id)
    with _write(conn, 'corner_occurrence_create') as cur:
        cur.execute('SELECT decision_kind FROM corner.qualification_decisions WHERE id=%s', (decision,))
        qualification = cur.fetchone()
        if qualification is None or qualification['decision_kind'] != 'qualified':
            raise ChannelValidationError('occurrence requires a persisted qualified decision')
        cur.execute('''INSERT INTO corner.opportunity_occurrences (qualification_decision_id)
            VALUES (%s) ON CONFLICT (qualification_decision_id) DO NOTHING RETURNING *''', (decision,))
        row = cur.fetchone()
        if row is None:
            cur.execute('SELECT * FROM corner.opportunity_occurrences WHERE qualification_decision_id=%s', (decision,))
            row = cur.fetchone()
        if row is None:
            raise RuntimeError('retry transaction: occurrence is outside snapshot')
        return dict(row)
