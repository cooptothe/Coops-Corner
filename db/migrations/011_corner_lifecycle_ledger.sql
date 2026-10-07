BEGIN;

CREATE TABLE corner.opportunity_types (
    code TEXT PRIMARY KEY CHECK (btrim(code) <> ''),
    display_name TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE
);
INSERT INTO corner.opportunity_types (code, display_name) VALUES ('positive_ev', 'Positive EV');

ALTER TABLE corner.channel_generation_activations ADD CONSTRAINT activations_id_generation_key
    UNIQUE (id, new_generation_id);

CREATE TABLE corner.opportunity_conditions (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    opportunity_type TEXT NOT NULL REFERENCES corner.opportunity_types(code) ON DELETE RESTRICT,
    target_sportsbook_id UUID NOT NULL REFERENCES corner.sportsbooks(id) ON DELETE RESTRICT,
    outcome_id UUID NOT NULL REFERENCES corner.outcomes(id) ON DELETE RESTRICT,
    qualification_channel_id UUID NOT NULL REFERENCES corner.qualification_channels(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (opportunity_type, target_sportsbook_id, outcome_id, qualification_channel_id)
);
-- Canonical identity is not an event, but none of its fields are mutable.
CREATE TRIGGER opportunity_conditions_identity_immutable BEFORE UPDATE ON corner.opportunity_conditions
FOR EACH ROW EXECUTE FUNCTION corner.reject_immutable_change();

CREATE TABLE corner.lifecycle_applications (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    condition_id UUID NOT NULL REFERENCES corner.opportunity_conditions(id) ON DELETE RESTRICT,
    application_sequence BIGINT NOT NULL CHECK (application_sequence > 0),
    previous_application_id UUID,
    previous_application_sequence BIGINT,
    pre_state_sha256 BYTEA NOT NULL CHECK (octet_length(pre_state_sha256)=32),
    post_state_sha256 BYTEA NOT NULL CHECK (octet_length(post_state_sha256)=32),
    authority_kind TEXT NOT NULL CHECK (authority_kind IN ('human','service')),
    authority_id TEXT NOT NULL CHECK (btrim(authority_id)<>''),
    application_key TEXT NOT NULL CHECK (btrim(application_key)<>''),
    command_kind TEXT NOT NULL CHECK (command_kind IN ('evaluation','qualification','assessment','generation_activation')),
    engine_evaluation_id UUID REFERENCES corner.engine_evaluations(id) ON DELETE RESTRICT,
    qualification_decision_id UUID REFERENCES corner.qualification_decisions(id) ON DELETE RESTRICT,
    opportunity_occurrence_id UUID REFERENCES corner.opportunity_occurrences(id) ON DELETE RESTRICT,
    actionability_assessment_id UUID REFERENCES corner.actionability_assessments(id) ON DELETE RESTRICT,
    channel_generation_activation_id UUID REFERENCES corner.channel_generation_activations(id) ON DELETE RESTRICT,
    reducer_name TEXT NOT NULL CHECK (btrim(reducer_name)<>''),
    reducer_version TEXT NOT NULL CHECK (btrim(reducer_version)<>''),
    reducer_revision TEXT NOT NULL CHECK (btrim(reducer_revision)<>''),
    snapshot_format_version TEXT NOT NULL,
    command_snapshot JSONB NOT NULL CHECK (jsonb_typeof(command_snapshot)='object'),
    command_sha256 BYTEA NOT NULL CHECK (octet_length(command_sha256)=32),
    result_snapshot JSONB NOT NULL CHECK (jsonb_typeof(result_snapshot)='object'),
    result_sha256 BYTEA NOT NULL CHECK (octet_length(result_sha256)=32),
    application_outcome TEXT NOT NULL CHECK (application_outcome IN ('applied','ignored','already_reflected')),
    reason_code TEXT NOT NULL CHECK (btrim(reason_code)<>''),
    transition_count INTEGER NOT NULL CHECK (transition_count>=0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (authority_kind, authority_id, application_key),
    UNIQUE (condition_id, application_sequence),
    UNIQUE (id, condition_id, application_sequence, post_state_sha256),
    FOREIGN KEY (previous_application_id, condition_id, previous_application_sequence, pre_state_sha256)
        REFERENCES corner.lifecycle_applications(id, condition_id, application_sequence, post_state_sha256) ON DELETE RESTRICT,
    CHECK ((application_sequence=1 AND previous_application_id IS NULL AND previous_application_sequence IS NULL)
        OR (application_sequence>1 AND previous_application_id IS NOT NULL
            AND previous_application_sequence IS NOT NULL AND previous_application_sequence=application_sequence-1)),
    CHECK (
        (command_kind='evaluation' AND engine_evaluation_id IS NOT NULL AND qualification_decision_id IS NULL
            AND opportunity_occurrence_id IS NULL AND actionability_assessment_id IS NULL AND channel_generation_activation_id IS NULL)
        OR (command_kind='qualification' AND qualification_decision_id IS NOT NULL AND engine_evaluation_id IS NULL
            AND actionability_assessment_id IS NULL AND channel_generation_activation_id IS NULL)
        OR (command_kind='assessment' AND actionability_assessment_id IS NOT NULL AND engine_evaluation_id IS NULL
            AND qualification_decision_id IS NULL AND opportunity_occurrence_id IS NULL AND channel_generation_activation_id IS NULL)
        OR (command_kind='generation_activation' AND channel_generation_activation_id IS NOT NULL AND engine_evaluation_id IS NULL
            AND qualification_decision_id IS NULL AND opportunity_occurrence_id IS NULL AND actionability_assessment_id IS NULL))
);
-- These support targeted reducer context, not speculative feed queries.
CREATE INDEX lifecycle_applications_evaluation_idx ON corner.lifecycle_applications(condition_id, engine_evaluation_id)
    WHERE engine_evaluation_id IS NOT NULL;
CREATE INDEX lifecycle_applications_qualification_idx ON corner.lifecycle_applications(condition_id, qualification_decision_id)
    WHERE qualification_decision_id IS NOT NULL;
CREATE INDEX lifecycle_applications_assessment_idx ON corner.lifecycle_applications(condition_id, actionability_assessment_id)
    WHERE actionability_assessment_id IS NOT NULL;
CREATE INDEX lifecycle_applications_activation_idx ON corner.lifecycle_applications(condition_id, channel_generation_activation_id)
    WHERE channel_generation_activation_id IS NOT NULL;

CREATE TABLE corner.opportunity_transitions (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    application_id UUID NOT NULL REFERENCES corner.lifecycle_applications(id) ON DELETE RESTRICT,
    output_ordinal INTEGER NOT NULL CHECK (output_ordinal>=1),
    episode_id UUID NOT NULL,
    episode_generation_id UUID NOT NULL REFERENCES corner.qualification_channel_generations(id) ON DELETE RESTRICT,
    transition_kind TEXT NOT NULL CHECK (transition_kind IN ('opened','continued','closed')),
    reason_code TEXT NOT NULL CHECK (btrim(reason_code)<>''),
    transition_at TIMESTAMPTZ NOT NULL,
    opportunity_occurrence_id UUID REFERENCES corner.opportunity_occurrences(id) ON DELETE RESTRICT,
    qualification_decision_id UUID REFERENCES corner.qualification_decisions(id) ON DELETE RESTRICT,
    actionability_assessment_id UUID REFERENCES corner.actionability_assessments(id) ON DELETE RESTRICT,
    channel_generation_activation_id UUID REFERENCES corner.channel_generation_activations(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (application_id, output_ordinal),
    UNIQUE (id, episode_id, episode_generation_id, transition_kind),
    CHECK (
        (transition_kind IN ('opened','continued') AND reason_code='qualified_current'
            AND opportunity_occurrence_id IS NOT NULL AND actionability_assessment_id IS NOT NULL
            AND qualification_decision_id IS NULL AND channel_generation_activation_id IS NULL)
        OR (transition_kind='closed' AND opportunity_occurrence_id IS NULL AND
            ((reason_code='qualification_lost' AND qualification_decision_id IS NOT NULL
                AND actionability_assessment_id IS NULL AND channel_generation_activation_id IS NULL)
             OR (reason_code='channel_configuration_changed' AND channel_generation_activation_id IS NOT NULL
                AND qualification_decision_id IS NULL AND actionability_assessment_id IS NULL)
             OR (reason_code IN ('target_unavailable','target_stale','analytical_evidence_stale','analytical_evidence_changed','unsupported_phase')
                AND actionability_assessment_id IS NOT NULL AND qualification_decision_id IS NULL AND channel_generation_activation_id IS NULL))))
);
CREATE UNIQUE INDEX opportunity_transitions_one_opening_idx ON corner.opportunity_transitions(episode_id)
    WHERE transition_kind='opened';

CREATE TABLE corner.condition_processing_projections (
    condition_id UUID PRIMARY KEY REFERENCES corner.opportunity_conditions(id) ON DELETE RESTRICT,
    processed_generation_id UUID NOT NULL,
    processed_activation_id UUID NOT NULL,
    evaluation_watermark_id UUID REFERENCES corner.engine_evaluations(id) ON DELETE RESTRICT,
    latest_threshold_qualification_id UUID REFERENCES corner.qualification_decisions(id) ON DELETE RESTRICT,
    accepted_assessment_id UUID REFERENCES corner.actionability_assessments(id) ON DELETE RESTRICT,
    open_episode_id UUID,
    open_episode_opening_transition_id UUID REFERENCES corner.opportunity_transitions(id) ON DELETE RESTRICT,
    last_transition_id UUID REFERENCES corner.opportunity_transitions(id) ON DELETE RESTRICT,
    last_application_id UUID NOT NULL,
    last_application_sequence BIGINT NOT NULL,
    authoritative_post_state_sha256 BYTEA NOT NULL,
    projection_format_version TEXT NOT NULL,
    projected_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (processed_activation_id, processed_generation_id)
        REFERENCES corner.channel_generation_activations(id, new_generation_id) ON DELETE RESTRICT,
    FOREIGN KEY (last_application_id, condition_id, last_application_sequence, authoritative_post_state_sha256)
        REFERENCES corner.lifecycle_applications(id, condition_id, application_sequence, post_state_sha256) ON DELETE RESTRICT,
    CHECK ((open_episode_id IS NULL) = (open_episode_opening_transition_id IS NULL))
);

CREATE TABLE corner.opportunities (
    id UUID PRIMARY KEY,
    condition_id UUID NOT NULL REFERENCES corner.opportunity_conditions(id) ON DELETE RESTRICT,
    episode_generation_id UUID NOT NULL,
    opening_transition_id UUID NOT NULL,
    opening_transition_kind TEXT NOT NULL DEFAULT 'opened' CHECK (opening_transition_kind='opened'),
    last_transition_id UUID NOT NULL REFERENCES corner.opportunity_transitions(id) ON DELETE RESTRICT,
    current_occurrence_id UUID NOT NULL REFERENCES corner.opportunity_occurrences(id) ON DELETE RESTRICT,
    opened_at TIMESTAMPTZ NOT NULL,
    closed_at TIMESTAMPTZ,
    close_reason TEXT,
    projection_format_version TEXT NOT NULL,
    projected_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (opening_transition_id, id, episode_generation_id, opening_transition_kind)
        REFERENCES corner.opportunity_transitions(id, episode_id, episode_generation_id, transition_kind) ON DELETE RESTRICT,
    CHECK ((closed_at IS NULL AND close_reason IS NULL)
        OR (closed_at IS NOT NULL AND close_reason IS NOT NULL AND btrim(close_reason)<>'' AND closed_at>=opened_at))
);
CREATE UNIQUE INDEX opportunities_one_open_idx ON corner.opportunities(condition_id) WHERE closed_at IS NULL;
CREATE INDEX opportunities_condition_idx ON corner.opportunities(condition_id, opened_at, id);

CREATE TRIGGER lifecycle_applications_immutable BEFORE UPDATE OR DELETE ON corner.lifecycle_applications
FOR EACH ROW EXECUTE FUNCTION corner.reject_immutable_change();
CREATE TRIGGER lifecycle_applications_no_truncate BEFORE TRUNCATE ON corner.lifecycle_applications
FOR EACH STATEMENT EXECUTE FUNCTION corner.reject_immutable_change();
CREATE TRIGGER opportunity_transitions_immutable BEFORE UPDATE OR DELETE ON corner.opportunity_transitions
FOR EACH ROW EXECUTE FUNCTION corner.reject_immutable_change();
CREATE TRIGGER opportunity_transitions_no_truncate BEFORE TRUNCATE ON corner.opportunity_transitions
FOR EACH STATEMENT EXECUTE FUNCTION corner.reject_immutable_change();
REVOKE ALL ON corner.opportunity_types, corner.opportunity_conditions, corner.lifecycle_applications,
    corner.opportunity_transitions, corner.condition_processing_projections, corner.opportunities FROM PUBLIC;
COMMIT;
