"""Versioned evaluate preparation only. No provider calls or phase inference.

Validation is supplied by a trusted, explicitly pinned adapter. No production
phase/settlement adapter is implemented here; tests use synthetic evidence.
"""
from dataclasses import asdict, dataclass
from datetime import timedelta
import hashlib
from pathlib import Path
from typing import Callable

from psycopg2.extras import RealDictCursor

from corner import assessments as a, evaluations as codec, ev, ev_selection as selection
from corner import lifecycle_store as ls, work as w
from corner.lifecycle import ImplementationIdentity
from corner.reconciliation import evaluation_route

FORMAT = 'corner.ev.selection/1'
REVISION = 'sha256:' + codec._digest({
    'capture': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'selector': hashlib.sha256(Path(selection.__file__).read_bytes()).hexdigest(),
}).hex()


class CaptureWaiting(Exception):
    """No validated command can yet be assembled; never a fabricated EV result."""


@dataclass(frozen=True)
class ValidationAdapter:
    identity: ImplementationIdentity
    validate: Callable

    def __post_init__(self):
        w._require(isinstance(self.identity, ImplementationIdentity) and callable(self.validate),
                   'versioned trusted validation adapter required')


def request_intent(*, outcome_id, sportsbook_id, validation_adapter):
    """Explicit producer intent. This function does not establish routing itself."""
    w._require(isinstance(validation_adapter, ImplementationIdentity), 'validation adapter identity required')
    return evaluation_route(outcome_id=outcome_id, sportsbook_id=sportsbook_id) | {
        'selector': {'format': FORMAT, 'revision': REVISION, 'validation_adapter': asdict(validation_adapter)}}


def _scope(cur, request):
    w._require(request['condition_id'] and request['generation_id'], 'evaluation requires explicit condition/generation')
    condition, _ = ls._condition(cur, request['condition_id'])
    ls._generation(cur, request['generation_id'], condition)
    generation = a._row(cur, 'qualification_channel_generations', request['generation_id'])
    intent = request['intent_snapshot']['intent']
    route = evaluation_route(outcome_id=condition['outcome_id'], sportsbook_id=condition['target_sportsbook_id'])
    w._require(all(intent.get(k) == v for k, v in route.items()), 'evaluation route mismatch')
    selector = intent['selector']
    w._require(selector['format'] == FORMAT, 'unsupported selector format')
    if selector['revision'] != REVISION:
        raise w.WorkBlocked('pinned selector implementation unavailable')
    ImplementationIdentity(**selector['validation_adapter'])
    engine = generation['configuration_snapshot']['engine']
    if engine['implementation'] != {'name': ev.ENGINE_NAME, 'version': ev.ENGINE_VERSION, 'revision': codec.ENGINE_REVISION}:
        raise w.WorkBlocked('pinned engine implementation unavailable')
    config = dict(engine['configuration'])
    for key in ('target_max_age', 'reference_max_age', 'max_input_skew', 'provider_max_age'):
        config[key] = timedelta(microseconds=config[key]) if config[key] is not None else None
    config['provider_time_policy'] = ev.ProviderTimePolicy(config['provider_time_policy'])
    return condition, ev.EVConfiguration(**config), selector


def _validation(value):
    w._require(isinstance(value, selection.MarketValidation), 'explicit MarketValidation required')
    w._require(all(isinstance(v, str) and v.strip() for v in asdict(value).values()),
               'nonblank phase and settlement evidence required')
    return value


def capture(conn, *, request, validator):
    """Select quotes in one MVCC statement without locking WorkExecution.

The worker checks its lease immediately before entering this transaction and
again when freezing the result. A capture that outlives its lease is discardable.
The trusted adapter must be read-only and bound its own external work/timeouts.
"""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        condition, configuration, selector = _scope(cur, request)
        if validator is None:
            raise CaptureWaiting('evaluation_validation_unavailable')
        w._require(isinstance(validator, ValidationAdapter), 'invalid validation adapter')
        if asdict(validator.identity) != selector['validation_adapter']:
            raise w.WorkBlocked('pinned validation adapter unavailable')
        evaluated_at = w._now(cur)
    validation = _validation(validator.validate(conn, dict(condition), evaluated_at))
    selected = selection.select_ev_snapshot(conn, target_outcome_id=condition['outcome_id'],
        target_sportsbook_id=condition['target_sportsbook_id'], evaluated_at=evaluated_at,
        configuration=configuration, validation=validation)
    if selected.reason == selection.SelectionReason.NO_TRUSTED_TARGET:
        raise CaptureWaiting('evaluation_target_missing')
    w._require(selected.snapshot is not None and selected.reason is None,
               'selector cannot assemble the requested canonical contract')
    context = {'selection': {'selector': selector, 'validation': asdict(validation),
                            'captured_at': codec._encode(evaluated_at)}}
    return codec.EvaluationCommand(selected.snapshot, selected.configuration, codec.canonical_json(context))


def validate_frozen(cur, request, document):
    """Validate captured metadata and pinned scope without selecting current quotes."""
    condition, configuration, selector = _scope(cur, request)
    command = codec.deserialize_command(document['payload'])
    capture_doc = document['payload']['context']['selection']
    w._require(capture_doc['selector'] == selector, 'frozen selector identity differs from intent')
    validation = _validation(selection.MarketValidation(**capture_doc['validation']))
    snapshot = command.snapshot
    w._require(configuration == command.configuration and
               capture_doc['captured_at'] == codec._encode(snapshot.evaluated_at), 'capture configuration/time mismatch')
    cur.execute('SELECT event_id FROM corner.markets WHERE id=%s', (snapshot.contract.market_id,))
    market = cur.fetchone()
    w._require(market and (validation.event_id, validation.market_id) == (market['event_id'], snapshot.contract.market_id),
               'frozen validation belongs to another contract')
    w._require((validation.event_phase, validation.phase_evidence, validation.settlement_policy, validation.settlement_evidence) ==
               (snapshot.event_phase, snapshot.phase_evidence, snapshot.contract.settlement_policy, snapshot.contract.settlement_evidence),
               'frozen validation contradicts snapshot')
    w._bind(cur, request, document)
