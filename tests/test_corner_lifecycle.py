"""Synthetic pure state-machine proof; no PostgreSQL, quotas or live timestamps."""

import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from corner.ev import QuoteInput
from corner.lifecycle import (
    ActionabilityPolicy, AssessmentRequest, ChannelGeneration, ConditionKey,
    EvaluationArrival, EvaluationFact, EvaluationOrder, GenerationChange, ImplementationIdentity,
    JudgmentCommand, LifecycleConflict, LifecycleConsistencyError, LifecycleValidationError,
    PhaseEvidence, QualificationFact, change_generation, initial_state,
    process_assessment, process_evaluation, process_judgment, project_episodes,
)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.time = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
        self.condition = ConditionKey('positive_ev', 'dk', 'saints-moneyline', 'pregame-ev')
        self.engine = ImplementationIdentity('ev', '1', 'immutable-engine-build')
        self.qualifier = ImplementationIdentity('minimum_ev', '1', 'immutable-qualifier-build')
        self.policy = ActionabilityPolicy(ImplementationIdentity('lifecycle', '1', 'immutable-lifecycle-build'),
                                         timedelta(minutes=5), timedelta(minutes=10))
        self.generation = ChannelGeneration('g1', self.condition.qualification_channel, self.engine,
            'engine-config-digest', self.qualifier, 'qualification-config-digest', self.policy)
        self.initial = initial_state(self.condition, self.generation)
        self.target = QuoteInput('target-1', 'market', self.condition.outcome_id, 'dk', Decimal('2.25'),
                                 'active', self.time)
        self.refs = (
            QuoteInput('ref-a', 'market', self.condition.outcome_id, 'pinnacle', Decimal('2'), 'active', self.time),
            QuoteInput('ref-b', 'market', 'falcons-moneyline', 'pinnacle', Decimal('2'), 'active', self.time),
            QuoteInput('ref-c', 'market', self.condition.outcome_id, 'circa', Decimal('2'), 'active', self.time),
            QuoteInput('ref-d', 'market', 'falcons-moneyline', 'circa', Decimal('2'), 'active', self.time),
        )
        self.phase = PhaseEvidence('phase-1', 'event', 'pregame', 'synthetic validated pregame state')

    def at(self, seconds):
        return self.time + timedelta(seconds=seconds)

    def judgment(self, name='1', seconds=1, decision='qualified', target=None, refs=None, generation=None):
        generation = generation or self.generation
        evaluation = EvaluationFact(EvaluationOrder(self.at(seconds), 'evaluation-' + name), self.condition,
            generation.engine, generation.engine_configuration_identity, 'event',
            'not_evaluable' if decision == 'not_qualifiable' else 'evaluated',
            target or self.target, self.refs if refs is None else refs)
        q = QualificationFact('qualification-' + name, generation.id, evaluation, generation.qualification_policy,
                               generation.qualification_configuration_identity, decision)
        return JudgmentCommand(q, 'occurrence-' + name if decision == 'qualified' else None, self.at(seconds + 1))

    def assessment(self, state, name='1', seconds=3, qualification=None, quotes=None, **changes):
        qid = qualification or state.latest_threshold_qualification_id
        q = next(c.qualification for c, _ in state.judgments if c.qualification.id == qid)
        args = dict(id='assessment-' + name, generation_id=state.generation.id, assessed_at=self.at(seconds),
            watermark=state.watermark, qualification_id=qid, basis_assessment_id=state.current_assessment_id,
            current_quotes=(q.evaluation.target,) + q.evaluation.contributing_references if quotes is None else quotes,
            phase=self.phase, opening_episode_id='episode-' + name)
        args.update(changes)
        return AssessmentRequest(**args)

    def opened(self):
        state = process_judgment(self.initial, self.judgment())
        return process_assessment(state, self.assessment(state))

    def test_qualified_occurrence_alone_does_not_open(self):
        state = process_judgment(self.initial, self.judgment())
        self.assertEqual(1, len(state.occurrences))
        self.assertIsNone(state.open_episode)
        self.assertEqual((), state.events)
        self.assertEqual((), self.initial.judgments)
        with self.assertRaises(FrozenInstanceError):
            state.watermark = None

    def test_open_continue_price_change_close_and_reopen(self):
        state = self.opened()
        old_episode = state.open_episode.id
        target = replace(self.target, observation_id='target-2', decimal_odds=Decimal('2.20'), observed_at=self.at(30))
        state = process_judgment(state, self.judgment('2', 31, target=target))
        state = process_assessment(state, self.assessment(state, '2', 33))
        self.assertEqual(old_episode, state.open_episode.id)
        self.assertEqual('occurrence-2', state.open_episode.current_occurrence_id)
        state = process_judgment(state, self.judgment('3', 40, 'not_qualified', target=target))
        self.assertIsNone(state.open_episode)
        self.assertEqual('qualification_lost', state.episodes[-1].close_reason)
        state = process_judgment(state, self.judgment('4', 50, target=target))
        state = process_assessment(state, self.assessment(state, '4', 53))
        self.assertNotEqual(old_episode, state.open_episode.id)
        self.assertEqual(['opened', 'continued', 'closed', 'opened'], [e.kind for e in state.events])
        self.assertEqual(2, len(state.episodes))

    def test_delayed_qualified_occurrence_cannot_open_unavailable_quote(self):
        state = process_judgment(self.initial, self.judgment())
        unavailable = replace(self.target, observation_id='target-removed', quote_state='unavailable',
                              decimal_odds=None, observed_at=self.at(50))
        state = process_assessment(state, self.assessment(state, seconds=60, quotes=(unavailable,) + self.refs))
        self.assertIsNone(state.open_episode)
        self.assertEqual(1, len(state.occurrences))
        self.assertIn('target_unavailable', state.assessments[-1][0].reasons)

    def test_changed_price_or_identical_new_poll_requires_new_evaluation(self):
        for price in ('1.67', '2.25'):
            state = self.opened()
            new = replace(self.target, observation_id='new-poll', decimal_odds=Decimal(price), observed_at=self.at(10))
            state = process_assessment(state, self.assessment(state, '2', 12, quotes=(new,) + self.refs))
            self.assertEqual('analytical_evidence_changed', state.episodes[-1].close_reason)
            self.assertIsNone(state.open_episode)

    def test_reference_refresh_invalidates_old_analysis_then_new_analysis_opens(self):
        state = self.opened()
        refs = (replace(self.refs[0], observation_id='reference-refreshed', observed_at=self.at(10)),) + self.refs[1:]
        state = process_assessment(state, self.assessment(state, '2', 12, quotes=(self.target,) + refs))
        self.assertEqual('analytical_evidence_changed', state.episodes[-1].close_reason)
        state = process_judgment(state, self.judgment('2', 14, refs=refs))
        state = process_assessment(state, self.assessment(state, '3', 16))
        self.assertEqual('episode-3', state.open_episode.id)

    def test_inactive_target_and_unsupported_phase_closures(self):
        for quote_state in ('unavailable', 'suspended'):
            state = self.opened()
            target = replace(self.target, observation_id='inactive', quote_state=quote_state,
                             decimal_odds=None, observed_at=self.at(10))
            state = process_assessment(state, self.assessment(state, '2', 12, quotes=(target,) + self.refs))
            self.assertEqual('target_unavailable', state.episodes[-1].close_reason)
        state = self.opened()
        state = process_assessment(state, self.assessment(state, '2', 12,
            phase=replace(self.phase, id='phase-live', phase='live')))
        self.assertEqual('unsupported_phase', state.episodes[-1].close_reason)

    def test_target_deadline_inclusive_then_stale(self):
        state = self.opened()
        state = process_assessment(state, self.assessment(state, 'boundary', 300))
        self.assertIsNotNone(state.open_episode)
        state = process_assessment(state, self.assessment(state, 'expired', 300.000001))
        self.assertEqual('target_stale', state.episodes[-1].close_reason)

    def test_reference_deadline_is_separate_from_target_deadline(self):
        policy = replace(self.policy, target_max_age=timedelta(minutes=20), reference_max_age=timedelta(minutes=1))
        generation = replace(self.generation, actionability_policy=policy)
        state = process_judgment(initial_state(self.condition, generation), self.judgment())
        state = process_assessment(state, self.assessment(state))
        state = process_assessment(state, self.assessment(state, 'expired', 61))
        self.assertEqual('analytical_evidence_stale', state.episodes[-1].close_reason)
        assessment = state.assessments[-1][0]
        self.assertEqual(self.at(1200), assessment.target_deadline)
        self.assertEqual(4, len(assessment.reference_deadlines))

    def test_not_evaluable_advances_watermark_without_closing_or_replacing_threshold(self):
        state = self.opened()
        state = process_judgment(state, self.judgment('gap', 20, 'not_qualifiable'))
        self.assertEqual('evaluation-gap', state.watermark.evaluation_id)
        self.assertEqual('qualification-1', state.latest_threshold_qualification_id)
        self.assertIsNotNone(state.open_episode)
        state = process_assessment(state, self.assessment(state, 'survives', 22))
        self.assertIsNotNone(state.open_episode)
        self.assertEqual(1, len(state.events))
        state = process_assessment(state, self.assessment(state, 'expired', 301))
        self.assertEqual('target_stale', state.episodes[-1].close_reason)

    def test_uncertainty_blocks_new_open_and_reopening_from_old_qualification(self):
        for opened in (False, True):
            state = self.opened() if opened else process_judgment(self.initial, self.judgment())
            state = process_judgment(state, self.judgment('gap', 20, 'not_qualifiable'))
            if opened:
                state = process_assessment(state, self.assessment(state, 'closed', 22,
                    phase=replace(self.phase, phase='live')))
            state = process_assessment(state, self.assessment(state, 'must-not-open', 24))
            self.assertIsNone(state.open_episode)
            self.assertEqual('obsolete_analytical_evidence', state.assessments[-1][1])

    def test_late_evaluation_preserves_occurrence_without_rewinding(self):
        newer = self.judgment('newer', 30, 'not_qualified')
        state = process_judgment(self.opened(), newer)
        late = replace(self.judgment('late', 20), transition_at=self.at(50))
        state = process_judgment(state, late)
        self.assertEqual(newer.qualification.evaluation.order, state.watermark)
        self.assertIsNone(state.open_episode)
        self.assertEqual('historical_or_equivalent', state.judgments[-1][1])
        self.assertIn('occurrence-late', [o.id for o in state.occurrences])

    def test_evaluation_exact_time_tie_uses_id_not_delivery_time(self):
        state = process_judgment(self.initial, self.judgment('z', 20, 'not_qualified'))
        state = process_judgment(state, replace(self.judgment('a', 20), transition_at=self.at(50)))
        self.assertEqual('evaluation-z', state.watermark.evaluation_id)
        self.assertEqual('qualification-z', state.latest_threshold_qualification_id)

    def test_old_expiry_cannot_close_refreshed_episode_even_at_later_time(self):
        state = self.opened()
        expiry = self.assessment(state, 'old-expiry', 301)
        target = replace(self.target, observation_id='fresh-target', observed_at=self.at(240))
        state = process_judgment(state, self.judgment('fresh', 241, target=target))
        state = process_assessment(state, self.assessment(state, 'fresh', 243))
        state = process_assessment(state, expiry)
        self.assertIsNotNone(state.open_episode)
        self.assertEqual('occurrence-fresh', state.open_episode.current_occurrence_id)
        self.assertEqual('obsolete_binding', state.assessments[-1][1])

    def test_assessment_basis_protects_same_watermark_refresh(self):
        state = self.opened()
        obsolete = self.assessment(state, 'old-request', 20,
                                  phase=replace(self.phase, phase='live'))
        state = process_assessment(state, self.assessment(state, 'refresh', 10))
        state = process_assessment(state, obsolete)
        self.assertIsNotNone(state.open_episode)
        self.assertEqual('obsolete_binding', state.assessments[-1][1])

    def test_assessment_chronology_and_tie_breaker(self):
        state = self.opened()
        state = process_assessment(state, self.assessment(state, 'z', 20))
        for name, at in (('older', 19), ('a', 20)):
            state = process_assessment(state, self.assessment(state, name, at,
                phase=replace(self.phase, phase='live')))
            self.assertEqual('historical_assessment', state.assessments[-1][1])
            self.assertIsNotNone(state.open_episode)
        state = process_assessment(state, self.assessment(state, 'zz', 20,
            phase=replace(self.phase, phase='live')))
        self.assertIsNone(state.open_episode)

    def test_generation_rollover_closes_requires_fresh_compatible_evidence(self):
        state = self.opened()
        generation = replace(self.generation, id='g2', qualification_configuration_identity='threshold-v2-digest')
        rollover = GenerationChange('rollover', 'g1', generation, self.at(60))
        state = change_generation(state, rollover)
        self.assertEqual('channel_configuration_changed', state.episodes[-1].close_reason)
        self.assertIsNone(state.watermark)
        self.assertIsNone(state.current_assessment_id)
        state = process_judgment(state, self.judgment('old-generation', 70))
        self.assertIsNone(state.watermark)
        state = process_judgment(state, self.judgment('predates-generation', 50, generation=generation))
        self.assertEqual('evaluation_predates_generation', state.judgments[-1][1])
        self.assertIsNone(state.watermark)
        state = process_judgment(state, self.judgment('new-generation', 71, generation=generation))
        state = process_assessment(state, self.assessment(state, 'new-generation', 73))
        self.assertEqual('g2', state.open_episode.generation_id)
        self.assertEqual(2, len(state.episodes))
        self.assertEqual(state, change_generation(state, rollover))
        obsolete = GenerationChange('late-rollover', 'g1', replace(generation, id='g3'), self.at(80))
        state = change_generation(state, obsolete)
        self.assertEqual('g2', state.generation.id)

    def test_incompatible_engine_configuration_and_qualification_policy_do_not_drive(self):
        original = self.judgment()
        for q in (
            replace(original.qualification, policy=replace(self.qualifier, revision='other-build')),
            replace(original.qualification, configuration_identity='different-threshold'),
            replace(original.qualification, evaluation=replace(original.qualification.evaluation,
                engine=replace(self.engine, revision='other-engine'))),
            replace(original.qualification, evaluation=replace(original.qualification.evaluation,
                configuration_identity='different-model-config')),
        ):
            state = process_judgment(self.initial, replace(original, qualification=q))
            self.assertIsNone(state.watermark)
            self.assertIsNone(state.open_episode)
            self.assertEqual(1, len(state.occurrences))

    def test_duplicate_processing_is_idempotent_and_new_equivalent_judgments_do_not_continue(self):
        command = self.judgment()
        state = process_judgment(self.initial, command)
        request = self.assessment(state)
        state = process_assessment(state, request)
        self.assertEqual(state, process_judgment(state, replace(command, transition_at=self.at(20))))
        self.assertEqual(state, process_judgment(state, replace(command, occurrence_id='unused-proposed-id')))
        self.assertEqual(state, process_assessment(state, request))
        equivalent = replace(command, qualification=replace(command.qualification, id='second-decision'),
                             occurrence_id='second-occurrence')
        state = process_judgment(state, equivalent)
        self.assertEqual(2, len(state.occurrences))
        self.assertEqual(1, len(state.events))
        self.assertEqual('qualification-1', state.latest_threshold_qualification_id)

    def test_contradictory_same_evaluation_judgments_are_consistency_failures(self):
        command = self.judgment()
        state = process_judgment(self.initial, command)
        wrong = replace(command, qualification=replace(command.qualification,
            id='contradiction', decision_kind='not_qualified'), occurrence_id=None)
        with self.assertRaises(LifecycleConsistencyError):
            process_judgment(state, wrong)
        self.assertEqual(1, len(state.occurrences))

    def test_identity_reuse_and_immutable_observation_contradictions_fail(self):
        state = self.opened()
        with self.assertRaises(LifecycleConflict):
            process_judgment(state, replace(self.judgment(), qualification=replace(
                self.judgment().qualification, configuration_identity='different-policy')))
        request = state.assessments[0][0].request
        with self.assertRaises(LifecycleConflict):
            process_assessment(state, replace(request, assessed_at=self.at(20)))
        with self.assertRaises(LifecycleConsistencyError):
            process_assessment(state, self.assessment(state, 'invalid', 20,
                quotes=(replace(self.target, decimal_odds=Decimal('9')),) + self.refs))

    def test_wrong_contract_event_and_missing_trusted_reference(self):
        state = self.opened()
        with self.assertRaises(LifecycleValidationError):
            process_judgment(state, replace(self.judgment('wrong'), qualification=replace(
                self.judgment('wrong').qualification, evaluation=replace(self.judgment('wrong').qualification.evaluation,
                    condition=replace(self.condition, qualification_channel='another-channel')))))
        with self.assertRaises(LifecycleValidationError):
            process_assessment(state, self.assessment(state, 'wrong-event', 20,
                phase=replace(self.phase, event_id='other-event')))
        state = process_assessment(state, self.assessment(state, 'rejected-ref', 20,
            quotes=(self.target,) + self.refs[1:]))
        self.assertEqual('analytical_evidence_changed', state.episodes[-1].close_reason)

    def test_naive_times_and_future_evidence_rejected(self):
        with self.assertRaises(LifecycleValidationError):
            EvaluationOrder(datetime(2026, 9, 22), 'evaluation')
        state = self.opened()
        with self.assertRaises(LifecycleValidationError):
            self.assessment(state, 'future-quote', 20,
                quotes=(replace(self.target, observed_at=self.at(21)),) + self.refs)

    def test_exact_replay_of_commands_reconstructs_state_and_events(self):
        def replay():
            state = self.opened()
            state = process_judgment(state, self.judgment('gap', 20, 'not_qualifiable'))
            state = process_assessment(state, self.assessment(state, 'expired', 301))
            target = replace(self.target, observation_id='new', observed_at=self.at(310))
            state = process_judgment(state, self.judgment('new', 311, target=target))
            return process_assessment(state, self.assessment(state, 'reopened', 313))
        self.assertEqual(replay(), replay())
        self.assertEqual([1, 2, 3], [event.sequence for event in replay().events])
        self.assertEqual(replay().episodes, project_episodes(replay().events))

    def test_projector_rejects_missing_or_reordered_transitions(self):
        state = self.opened()
        state = process_judgment(state, self.judgment('close', 20, 'not_qualified'))
        with self.assertRaises(LifecycleConsistencyError):
            project_episodes(tuple(reversed(state.events)))
        with self.assertRaises(LifecycleConsistencyError):
            project_episodes((replace(state.events[-1], sequence=1),))

    def test_generation_identity_and_command_conflicts(self):
        generation = replace(self.generation, id='g2')
        command = GenerationChange('switch', 'g1', generation, self.at(20))
        state = change_generation(self.opened(), command)
        with self.assertRaises(LifecycleConflict):
            change_generation(state, replace(command, changed_at=self.at(30)))
        with self.assertRaises(LifecycleConflict):
            change_generation(state, GenerationChange('reactivate', 'g2', self.generation, self.at(40)))

    def test_same_evaluation_identity_cannot_change_immutable_evidence(self):
        state = self.opened()
        q = self.judgment().qualification
        changed = replace(q, id='different-qualification', evaluation=replace(q.evaluation,
            target=replace(self.target, observation_id='other-observation')))
        with self.assertRaises(LifecycleConsistencyError):
            process_judgment(state, JudgmentCommand(changed, 'new-occurrence', self.at(10)))

    def test_assessment_for_obsolete_evaluation_cannot_bind_to_new_watermark(self):
        state = self.opened()
        state = process_judgment(state, self.judgment('new', 20))
        wrong = self.assessment(state, 'wrong-binding', 25, qualification='qualification-1')
        state = process_assessment(state, wrong)
        self.assertEqual('obsolete_analytical_evidence', state.assessments[-1][1])
        self.assertEqual('occurrence-1', state.open_episode.current_occurrence_id)
        state = process_assessment(state, self.assessment(state, 'correct-binding', 26))
        self.assertEqual('occurrence-new', state.open_episode.current_occurrence_id)

    def test_newer_uncertainty_rejects_late_threshold_loss(self):
        state = self.opened()
        state = process_judgment(state, self.judgment('uncertain', 30, 'not_qualifiable'))
        state = process_judgment(state, replace(self.judgment('late-negative', 20, 'not_qualified'),
                                              transition_at=self.at(40)))
        self.assertIsNotNone(state.open_episode)
        self.assertEqual('qualification-1', state.latest_threshold_qualification_id)
        self.assertEqual('evaluation-uncertain', state.watermark.evaluation_id)

    def test_evaluation_before_qualification_blocks_old_opening_then_accepts_matching_judgment(self):
        state = process_judgment(self.initial, self.judgment())
        new = self.judgment('new', 20)
        arrival = EvaluationArrival('g1', new.qualification.evaluation)
        state = process_evaluation(state, arrival)
        state = process_assessment(state, self.assessment(state, 'blocked', 23, qualification='qualification-1'))
        self.assertIsNone(state.open_episode)
        self.assertEqual(state, process_evaluation(state, arrival))
        state = process_judgment(state, new)
        state = process_assessment(state, self.assessment(state, 'allowed', 24))
        self.assertEqual('occurrence-new', state.open_episode.current_occurrence_id)

    def test_not_evaluable_arrival_alone_preserves_open_episode(self):
        state = self.opened()
        gap = self.judgment('gap', 20, 'not_qualifiable')
        state = process_evaluation(state, EvaluationArrival('g1', gap.qualification.evaluation))
        self.assertIsNotNone(state.open_episode)
        self.assertEqual('evaluation-gap', state.watermark.evaluation_id)
        self.assertEqual('qualification-1', state.latest_threshold_qualification_id)
        state = process_assessment(state, self.assessment(state, 'survives', 23))
        self.assertIsNotNone(state.open_episode)
        state = process_judgment(state, gap)
        self.assertEqual('applicable', state.judgments[-1][1])
        self.assertEqual(1, len(state.events))

    def test_separate_evaluation_arrivals_cannot_rewind_or_redefine_evidence(self):
        state = process_evaluation(self.initial, EvaluationArrival('g1', self.judgment('new', 20).qualification.evaluation))
        state = process_evaluation(state, EvaluationArrival('g1', self.judgment('old', 10).qualification.evaluation))
        self.assertEqual('evaluation-new', state.watermark.evaluation_id)
        original = self.judgment('new', 20)
        altered = replace(original, qualification=replace(original.qualification,
            evaluation=replace(original.qualification.evaluation, event_id='another-event')))
        with self.assertRaises(LifecycleConsistencyError):
            process_judgment(state, altered)
