-- V2 preserves explicit authorization/conditioning closure evidence. No new
-- tables, rewritten history, vocabulary guesses, or runtime privileges.
BEGIN;
ALTER TABLE corner.opportunity_transitions
    DROP CONSTRAINT opportunity_transitions_check;
ALTER TABLE corner.opportunity_transitions
    ADD CONSTRAINT opportunity_transitions_check CHECK (
        (transition_kind IN ('opened','continued') AND reason_code='qualified_current'
            AND opportunity_occurrence_id IS NOT NULL AND actionability_assessment_id IS NOT NULL
            AND qualification_decision_id IS NULL AND channel_generation_activation_id IS NULL)
        OR (transition_kind='closed' AND opportunity_occurrence_id IS NULL AND (
            (reason_code='qualification_lost' AND qualification_decision_id IS NOT NULL
                AND actionability_assessment_id IS NULL AND channel_generation_activation_id IS NULL)
            OR (reason_code='channel_configuration_changed' AND channel_generation_activation_id IS NOT NULL
                AND qualification_decision_id IS NULL AND actionability_assessment_id IS NULL)
            OR (reason_code IN (
                'target_unavailable','target_stale','analytical_evidence_stale',
                'analytical_evidence_changed','unsupported_phase',
                'approval_withdrawn','approval_expired_or_not_applicable',
                'settlement_authority_unknown','current_settlement_incompatible',
                'analytical_conditioning_changed')
                AND actionability_assessment_id IS NOT NULL
                AND qualification_decision_id IS NULL AND channel_generation_activation_id IS NULL)
        ))
    );
COMMIT;
