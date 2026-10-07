"""Pure +EV episode prototype: immutable inputs, judgments and state reduction.

No database, UUID generation, wall clock, scheduler, EV calculation or qualification
execution. Adapters must supply authenticated/validated ledger facts and a coherent
trusted-state snapshot. IDs are supplied; tuples retain history for this prototype,
not a proposed persistence schema. See OPPORTUNITY_LIFECYCLE.md.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal

from corner.ev import QuoteInput


class LifecycleValidationError(ValueError):
    pass


class LifecycleConflict(ValueError):
    pass


class LifecycleConsistencyError(ValueError):
    pass


def _text(*values):
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise LifecycleValidationError('identities and evidence descriptions must be nonblank')


def _time(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise LifecycleValidationError('explicit timezone-aware time required')


def _slot(quote):
    return quote.outcome_id, quote.sportsbook_id


def _quotes(values):
    values = tuple(sorted(values, key=lambda q: (q.outcome_id, q.sportsbook_id)))
    if len({_slot(q) for q in values}) != len(values):
        raise LifecycleValidationError('one quote per canonical stream required')
    if len({q.observation_id for q in values}) != len(values):
        raise LifecycleValidationError('observation IDs must be distinct')
    for q in values:
        _text(q.observation_id, q.market_id, q.outcome_id, q.sportsbook_id)
        _time(q.observed_at)
        if q.quote_state not in {'active', 'suspended', 'unavailable'}:
            raise LifecycleValidationError('unsupported quote state')
        if q.provider_updated_at is not None:
            _time(q.provider_updated_at)
        if q.quote_state == 'active':
            if not isinstance(q.decimal_odds, Decimal) or not q.decimal_odds.is_finite() or q.decimal_odds <= 1:
                raise LifecycleValidationError('active quote requires valid decimal odds')
        elif q.decimal_odds is not None:
            raise LifecycleValidationError('inactive evidence cannot carry a price')
    return values


@dataclass(frozen=True)
class ImplementationIdentity:
    name: str
    version: str
    revision: str

    def __post_init__(self):
        _text(self.name, self.version, self.revision)


@dataclass(frozen=True)
class ConditionKey:
    opportunity_type: str
    target_sportsbook_id: str
    outcome_id: str
    qualification_channel: str

    def __post_init__(self):
        _text(self.target_sportsbook_id, self.outcome_id, self.qualification_channel)
        if self.opportunity_type != 'positive_ev':
            raise LifecycleValidationError('this prototype supports +EV only')


@dataclass(frozen=True)
class ActionabilityPolicy:
    identity: ImplementationIdentity
    target_max_age: timedelta
    reference_max_age: timedelta

    def __post_init__(self):
        if any(not isinstance(age, timedelta) or age < timedelta(0)
               for age in (self.target_max_age, self.reference_max_age)):
            raise LifecycleValidationError('explicit nonnegative age limits required')


@dataclass(frozen=True)
class ChannelGeneration:
    id: str
    channel: str
    engine: ImplementationIdentity
    engine_configuration_identity: str
    qualification_policy: ImplementationIdentity
    qualification_configuration_identity: str
    actionability_policy: ActionabilityPolicy

    def __post_init__(self):
        _text(self.id, self.channel, self.engine_configuration_identity,
              self.qualification_configuration_identity)


@dataclass(frozen=True, order=True)
class EvaluationOrder:
    evaluated_at: datetime
    evaluation_id: str

    def __post_init__(self):
        _time(self.evaluated_at)
        _text(self.evaluation_id)


@dataclass(frozen=True)
class EvaluationFact:
    order: EvaluationOrder
    condition: ConditionKey
    engine: ImplementationIdentity
    configuration_identity: str
    event_id: str
    result_kind: str
    target: QuoteInput | None
    contributing_references: tuple[QuoteInput, ...]

    def __post_init__(self):
        _text(self.configuration_identity, self.event_id)
        refs = _quotes(self.contributing_references)
        object.__setattr__(self, 'contributing_references', refs)
        if self.result_kind not in {'evaluated', 'not_evaluable'}:
            raise LifecycleValidationError('invalid analytical result kind')
        if self.target is not None:
            _quotes((self.target,))
            if _slot(self.target) != (self.condition.outcome_id, self.condition.target_sportsbook_id):
                raise LifecycleValidationError('target does not identify this condition')
            if any(q.market_id != self.target.market_id or q.sportsbook_id == self.target.sportsbook_id for q in refs):
                raise LifecycleValidationError('references must belong to the same market and exclude target book')
            _quotes((self.target,) + refs)
        if self.result_kind == 'evaluated':
            if self.target is None or not refs or any(q.quote_state != 'active' for q in (self.target,) + refs):
                raise LifecycleValidationError('evaluated evidence requires active target and contributing references')
            if any(q.observed_at > self.order.evaluated_at for q in (self.target,) + refs):
                raise LifecycleValidationError('evaluation cannot precede its observations')


@dataclass(frozen=True)
class EvaluationArrival:
    generation_id: str
    evaluation: EvaluationFact

    def __post_init__(self):
        _text(self.generation_id)


@dataclass(frozen=True)
class QualificationFact:
    id: str
    generation_id: str
    evaluation: EvaluationFact
    policy: ImplementationIdentity
    configuration_identity: str
    decision_kind: str

    def __post_init__(self):
        _text(self.id, self.generation_id, self.configuration_identity)
        allowed = {'not_qualifiable'} if self.evaluation.result_kind == 'not_evaluable' else {'qualified', 'not_qualified'}
        if self.decision_kind not in allowed:
            raise LifecycleValidationError('qualification contradicts analytical result kind')


@dataclass(frozen=True)
class Occurrence:
    id: str
    qualification_id: str


@dataclass(frozen=True)
class JudgmentCommand:
    qualification: QualificationFact
    occurrence_id: str | None
    transition_at: datetime

    def __post_init__(self):
        _time(self.transition_at)
        if self.transition_at < self.qualification.evaluation.order.evaluated_at:
            raise LifecycleValidationError('processing cannot precede evaluation')
        if self.qualification.decision_kind == 'qualified':
            _text(self.occurrence_id)
        elif self.occurrence_id is not None:
            raise LifecycleValidationError('only qualified judgments produce occurrences')


@dataclass(frozen=True)
class PhaseEvidence:
    id: str
    event_id: str
    phase: str
    description: str

    def __post_init__(self):
        _text(self.id, self.event_id, self.phase, self.description)


@dataclass(frozen=True)
class AssessmentRequest:
    id: str
    generation_id: str
    assessed_at: datetime
    watermark: EvaluationOrder
    qualification_id: str
    basis_assessment_id: str | None
    current_quotes: tuple[QuoteInput, ...]
    phase: PhaseEvidence
    opening_episode_id: str | None = None

    def __post_init__(self):
        _text(self.id, self.generation_id, self.qualification_id)
        _time(self.assessed_at)
        if self.assessed_at < self.watermark.evaluated_at:
            raise LifecycleValidationError('assessment precedes evaluation watermark')
        object.__setattr__(self, 'current_quotes', _quotes(self.current_quotes))
        if any(q.observed_at > self.assessed_at for q in self.current_quotes):
            raise LifecycleValidationError('assessment precedes current observations')


@dataclass(frozen=True)
class ActionabilityAssessment:
    request: AssessmentRequest
    policy: ActionabilityPolicy
    qualification: QualificationFact
    target_deadline: datetime
    reference_deadlines: tuple[tuple[str, datetime], ...]
    reasons: tuple[str, ...]

    @property
    def actionable(self):
        return not self.reasons

    @property
    def order(self):
        return self.request.assessed_at, self.request.id


@dataclass(frozen=True)
class Episode:
    id: str
    generation_id: str
    opened_at: datetime
    current_occurrence_id: str
    closed_at: datetime | None = None
    close_reason: str | None = None


@dataclass(frozen=True)
class LifecycleEvent:
    sequence: int
    episode_id: str
    generation_id: str
    policy: ImplementationIdentity
    kind: str
    reason: str
    transition_at: datetime
    evidence_kind: str
    evidence_id: str
    occurrence_id: str | None


@dataclass(frozen=True)
class GenerationChange:
    id: str
    expected_generation_id: str
    generation: ChannelGeneration
    changed_at: datetime

    def __post_init__(self):
        _text(self.id, self.expected_generation_id)
        _time(self.changed_at)


@dataclass(frozen=True)
class LifecycleState:
    condition: ConditionKey
    generations: tuple[ChannelGeneration, ...]
    evaluations: tuple[tuple[EvaluationArrival, str], ...] = ()
    judgments: tuple[tuple[JudgmentCommand, str], ...] = ()
    occurrences: tuple[Occurrence, ...] = ()
    assessments: tuple[tuple[ActionabilityAssessment, str], ...] = ()
    generation_changes: tuple[tuple[GenerationChange, str], ...] = ()
    episodes: tuple[Episode, ...] = ()
    events: tuple[LifecycleEvent, ...] = ()
    watermark: EvaluationOrder | None = None
    latest_threshold_qualification_id: str | None = None
    current_assessment_id: str | None = None
    generation_activated_at: datetime | None = None

    @property
    def generation(self):
        return self.generations[-1]

    @property
    def open_episode(self):
        return next((episode for episode in reversed(self.episodes) if episode.closed_at is None), None)


def initial_state(condition, generation):
    if condition.qualification_channel != generation.channel:
        raise LifecycleValidationError('generation belongs to another channel')
    return LifecycleState(condition, (generation,))


def _qualification(state, qualification_id):
    for command, _ in state.judgments:
        if command.qualification.id == qualification_id:
            return command.qualification
    raise LifecycleValidationError('unknown qualification')


def _occurrence(state, qualification_id):
    return next(o for o in state.occurrences if o.qualification_id == qualification_id)


def _compatible(qualification, generation):
    return (qualification.generation_id == generation.id
            and qualification.evaluation.engine == generation.engine
            and qualification.evaluation.configuration_identity == generation.engine_configuration_identity
            and qualification.policy == generation.qualification_policy
            and qualification.configuration_identity == generation.qualification_configuration_identity)


def _validate_evaluation_identity(state, evaluation):
    known = [arrival.evaluation for arrival, _ in state.evaluations]
    known += [command.qualification.evaluation for command, _ in state.judgments]
    for old in known:
        if old.order.evaluation_id == evaluation.order.evaluation_id and old != evaluation:
            raise LifecycleConsistencyError('evaluation identity has contradictory evidence')


def process_evaluation(state, arrival):
    """Advance analytical knowledge even when qualification has not arrived yet."""
    evaluation = arrival.evaluation
    if evaluation.condition != state.condition:
        raise LifecycleValidationError('evaluation belongs to another condition')
    _validate_evaluation_identity(state, evaluation)
    for prior, _ in state.evaluations:
        if (prior.generation_id, prior.evaluation.order.evaluation_id) == (arrival.generation_id, evaluation.order.evaluation_id):
            return state
    generation = state.generation
    disposition = 'applicable'
    if (arrival.generation_id != generation.id or evaluation.engine != generation.engine
            or evaluation.configuration_identity != generation.engine_configuration_identity):
        disposition = 'incompatible_generation_or_policy'
    elif state.generation_activated_at is not None and evaluation.order.evaluated_at < state.generation_activated_at:
        disposition = 'evaluation_predates_generation'
    elif state.watermark is not None and evaluation.order <= state.watermark:
        disposition = 'historical_or_equivalent'
    return replace(state, evaluations=state.evaluations + ((arrival, disposition),),
                   watermark=evaluation.order if disposition == 'applicable' else state.watermark)


def project_episodes(events):
    """Rebuild only the episode projection from immutable lifecycle transitions."""
    episodes = {}
    previous_time = None
    for sequence, event in enumerate(events, 1):
        if event.sequence != sequence or (previous_time is not None and event.transition_at < previous_time):
            raise LifecycleConsistencyError('invalid lifecycle event sequence')
        previous_time = event.transition_at
        if event.kind == 'opened':
            if (event.episode_id in episodes or event.occurrence_id is None
                    or any(e.closed_at is None for e in episodes.values())):
                raise LifecycleConsistencyError('invalid episode opening')
            episodes[event.episode_id] = Episode(event.episode_id, event.generation_id,
                                                 event.transition_at, event.occurrence_id)
            continue
        episode = episodes.get(event.episode_id)
        if episode is None or episode.closed_at is not None or episode.generation_id != event.generation_id:
            raise LifecycleConsistencyError('transition does not belong to an open episode')
        if event.kind == 'closed':
            episodes[episode.id] = replace(episode, closed_at=event.transition_at, close_reason=event.reason)
        elif event.kind == 'continued' and event.occurrence_id is not None:
            episodes[episode.id] = replace(episode, current_occurrence_id=event.occurrence_id)
        else:
            raise LifecycleConsistencyError('invalid episode transition')
    return tuple(episodes.values())


def _transition(state, episode, kind, reason, at, evidence_kind, evidence_id, occurrence_id=None):
    if kind not in {'opened', 'continued', 'closed'} or (kind != 'closed' and occurrence_id is None):
        raise LifecycleConsistencyError('invalid lifecycle output')
    if state.events and at < state.events[-1].transition_at:
        raise LifecycleValidationError('transition time cannot precede the last applied transition')
    event = LifecycleEvent((state.events[-1].sequence if state.events else 0) + 1, episode.id, episode.generation_id,
        state.generation.actionability_policy.identity, kind, reason, at, evidence_kind, evidence_id, occurrence_id)
    events = state.events + (event,)
    # Incremental output application. The independent full projector remains the
    # replay oracle; persistence may load only the open episode and last event.
    if kind == 'opened':
        if (state.open_episode or any(e.id == episode.id for e in state.episodes)
                or episode.closed_at is not None or episode.current_occurrence_id != occurrence_id):
            raise LifecycleConsistencyError('invalid episode opening')
        episodes = state.episodes + (episode,)
    else:
        if state.open_episode != episode:
            raise LifecycleConsistencyError('transition requires the open episode')
        replacement = (replace(episode, closed_at=at, close_reason=reason) if kind == 'closed'
                       else replace(episode, current_occurrence_id=occurrence_id))
        episodes = tuple(replacement if e.id == episode.id else e for e in state.episodes)
    return replace(state, episodes=episodes, events=events)


def process_judgment(state, command):
    """Register detection even when historical; only compatible newer facts advance."""
    q = command.qualification
    if q.evaluation.condition != state.condition:
        raise LifecycleValidationError('qualification belongs to another condition')
    _validate_evaluation_identity(state, q.evaluation)
    for prior, _ in state.judgments:
        old = prior.qualification
        if old.id == q.id:
            if old != q:
                raise LifecycleConflict('qualification identity reused with different evidence')
            # Qualification is the occurrence's idempotency root. A newly proposed
            # occurrence ID on retry cannot replace its already registered ID.
            return state
        if old.evaluation.order.evaluation_id == q.evaluation.order.evaluation_id:
            if old.evaluation != q.evaluation:
                raise LifecycleConsistencyError('evaluation identity has contradictory evidence')
            if (old.generation_id, old.policy, old.configuration_identity) == (q.generation_id, q.policy, q.configuration_identity):
                if old.decision_kind != q.decision_kind:
                    raise LifecycleConsistencyError('authoritative qualification judgments disagree')
    occurrences = state.occurrences
    if command.occurrence_id is not None:
        if any(o.id == command.occurrence_id for o in occurrences):
            raise LifecycleConflict('occurrence ID already used')
        occurrences += (Occurrence(command.occurrence_id, q.id),)
    disposition = 'applicable'
    if not _compatible(q, state.generation):
        disposition = 'incompatible_generation_or_policy'
    elif state.generation_activated_at is not None and q.evaluation.order.evaluated_at < state.generation_activated_at:
        disposition = 'evaluation_predates_generation'
    elif state.watermark is not None and q.evaluation.order < state.watermark:
        disposition = 'historical_or_equivalent'
    elif any(old.qualification.evaluation.order == q.evaluation.order
             and _compatible(old.qualification, state.generation) for old, _ in state.judgments):
        disposition = 'historical_or_equivalent'
    result = replace(state, occurrences=occurrences, judgments=state.judgments + ((command, disposition),))
    if disposition != 'applicable':
        return result
    result = replace(result, watermark=q.evaluation.order)
    if q.decision_kind == 'not_qualifiable':
        return result
    result = replace(result, latest_threshold_qualification_id=q.id)
    if q.decision_kind == 'not_qualified' and result.open_episode:
        result = _transition(result, result.open_episode, 'closed', 'qualification_lost',
                             command.transition_at, 'qualification', q.id)
    return result


def assess_actionability(request, qualification, policy):
    """Compute current-state judgment; never infer actionability from EV reason codes."""
    evaluation = qualification.evaluation
    if qualification.decision_kind != 'qualified' or request.qualification_id != qualification.id:
        raise LifecycleValidationError('assessment requires exact qualified evidence')
    if request.generation_id != qualification.generation_id or request.phase.event_id != evaluation.event_id:
        raise LifecycleValidationError('assessment evidence crosses generation/event')
    if request.watermark < evaluation.order:
        raise LifecycleValidationError('assessed evaluation is newer than watermark')
    target = evaluation.target
    refs = evaluation.contributing_references
    current = {_slot(q): q for q in request.current_quotes}
    expected = (target,) + refs
    by_id = {q.observation_id: q for q in expected}
    for q in request.current_quotes:
        if q.observation_id in by_id and by_id[q.observation_id] != q:
            raise LifecycleConsistencyError('immutable observation changed under the same ID')
    target_deadline = target.observed_at + policy.target_max_age
    deadlines = tuple((q.observation_id, q.observed_at + policy.reference_max_age) for q in refs)
    reasons = []
    offered = current.get(_slot(target))
    if request.phase.phase != 'pregame':
        reasons.append('unsupported_phase')
    if offered is not None and offered.quote_state != 'active':
        reasons.append('target_unavailable')
    if request.assessed_at > target_deadline:
        reasons.append('target_stale')
    if any(request.assessed_at > deadline for _, deadline in deadlines):
        reasons.append('analytical_evidence_stale')
    if any(current.get(_slot(q)) != q for q in expected):
        reasons.append('analytical_evidence_changed')
    return ActionabilityAssessment(request, policy, qualification, target_deadline, deadlines, tuple(reasons))


def _candidate(state):
    if state.latest_threshold_qualification_id is not None:
        latest = _qualification(state, state.latest_threshold_qualification_id)
        if latest.decision_kind == 'qualified' and latest.evaluation.order == state.watermark:
            return latest
    # Uncertainty may preserve an existing episode, never create a new one.
    if state.open_episode:
        occurrence = next(o for o in state.occurrences if o.id == state.open_episode.current_occurrence_id)
        return _qualification(state, occurrence.qualification_id)
    return None


def process_assessment(state, request):
    for prior, _ in state.assessments:
        if prior.request.id == request.id:
            if prior.request != request:
                raise LifecycleConflict('assessment ID reused with different command')
            return state
    generation = next((g for g in state.generations if g.id == request.generation_id), None)
    if generation is None:
        raise LifecycleValidationError('unknown channel generation')
    q = _qualification(state, request.qualification_id)
    assessment = assess_actionability(request, q, generation.actionability_policy)
    candidate = _candidate(state)
    disposition = 'applicable'
    if not _compatible(q, state.generation):
        disposition = 'incompatible_generation_or_policy'
    elif state.generation_activated_at is not None and request.assessed_at < state.generation_activated_at:
        disposition = 'assessment_predates_generation'
    elif request.watermark != state.watermark or request.basis_assessment_id != state.current_assessment_id:
        disposition = 'obsolete_binding'
    elif candidate is None or candidate.id != q.id:
        disposition = 'obsolete_analytical_evidence'
    elif state.current_assessment_id is not None:
        previous = next(a for a, _ in state.assessments if a.request.id == state.current_assessment_id)
        if assessment.order <= previous.order:
            disposition = 'historical_assessment'
    result = replace(state, assessments=state.assessments + ((assessment, disposition),))
    if disposition != 'applicable':
        return result
    result = replace(result, current_assessment_id=request.id)
    episode = result.open_episode
    if not assessment.actionable:
        if episode:
            result = _transition(result, episode, 'closed', assessment.reasons[0],
                                 request.assessed_at, 'assessment', request.id)
        return result
    occurrence = _occurrence(result, q.id)
    if episode is None:
        # Candidate only exists without an episode when qualification == watermark.
        _text(request.opening_episode_id)
        if any(e.id == request.opening_episode_id for e in result.episodes):
            raise LifecycleConflict('episode ID already used')
        episode = Episode(request.opening_episode_id, generation.id, request.assessed_at, occurrence.id)
        return _transition(result, episode, 'opened', 'qualified_current', request.assessed_at,
                           'assessment', request.id, occurrence.id)
    if episode.current_occurrence_id != occurrence.id:
        return _transition(result, episode, 'continued', 'qualified_current', request.assessed_at,
                           'assessment', request.id, occurrence.id)
    return result  # Refresh assessment/deadline authority without duplicate continuation.


def change_generation(state, command):
    for prior, _ in state.generation_changes:
        if prior.id == command.id:
            if prior != command:
                raise LifecycleConflict('generation command identity reused')
            return state
    if command.generation.channel != state.condition.qualification_channel:
        raise LifecycleValidationError('generation belongs to another channel')
    if command.expected_generation_id != state.generation.id:
        return replace(state, generation_changes=state.generation_changes + ((command, 'obsolete_binding'),))
    if any(g.id == command.generation.id for g in state.generations):
        raise LifecycleConflict('generation identity must be new, never reinterpreted or reactivated')
    if state.events and command.changed_at < state.events[-1].transition_at:
        raise LifecycleValidationError('generation transition cannot precede latest episode transition')
    result = state
    if result.open_episode:
        result = _transition(result, result.open_episode, 'closed', 'channel_configuration_changed',
                             command.changed_at, 'generation_change', command.id)
    return replace(result, generations=result.generations + (command.generation,),
        generation_changes=result.generation_changes + ((command, 'applied'),),
        watermark=None, latest_threshold_qualification_id=None, current_assessment_id=None,
        generation_activated_at=command.changed_at)
