BEGIN;

CREATE TABLE corner.actionability_assessments (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    channel_generation_id UUID NOT NULL REFERENCES corner.qualification_channel_generations(id) ON DELETE RESTRICT,
    qualification_decision_id UUID NOT NULL,
    qualification_decision_kind TEXT NOT NULL DEFAULT 'qualified' CHECK (qualification_decision_kind = 'qualified'),
    evaluation_watermark_id UUID NOT NULL REFERENCES corner.engine_evaluations(id) ON DELETE RESTRICT,
    basis_assessment_id UUID REFERENCES corner.actionability_assessments(id) ON DELETE RESTRICT,
    snapshot_captured_at TIMESTAMPTZ NOT NULL,
    assessed_at TIMESTAMPTZ NOT NULL CHECK (assessed_at >= snapshot_captured_at),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    authority_kind TEXT NOT NULL CHECK (authority_kind IN ('human', 'service')),
    authority_id TEXT NOT NULL CHECK (btrim(authority_id) <> ''),
    assessment_key TEXT NOT NULL CHECK (btrim(assessment_key) <> ''),
    implementation_name TEXT NOT NULL CHECK (btrim(implementation_name) <> ''),
    implementation_version TEXT NOT NULL CHECK (btrim(implementation_version) <> ''),
    implementation_revision TEXT NOT NULL CHECK (btrim(implementation_revision) <> ''),
    snapshot_format_version TEXT NOT NULL CHECK (btrim(snapshot_format_version) <> ''),
    actionable BOOLEAN NOT NULL,
    primary_reason TEXT,
    target_deadline TIMESTAMPTZ,
    command_snapshot JSONB NOT NULL CHECK (jsonb_typeof(command_snapshot) = 'object'),
    command_sha256 BYTEA NOT NULL CHECK (octet_length(command_sha256) = 32),
    result_snapshot JSONB NOT NULL CHECK (jsonb_typeof(result_snapshot) = 'object'),
    result_sha256 BYTEA NOT NULL CHECK (octet_length(result_sha256) = 32),
    CONSTRAINT actionability_assessments_reason_shape CHECK (
        (actionable AND primary_reason IS NULL) OR
        (NOT actionable AND primary_reason IS NOT NULL AND btrim(primary_reason) <> '')),
    CONSTRAINT actionability_assessments_qualified_fk
        FOREIGN KEY (qualification_decision_id, qualification_decision_kind)
        REFERENCES corner.qualification_decisions(id, decision_kind) ON DELETE RESTRICT,
    CONSTRAINT actionability_assessments_command_key UNIQUE (authority_kind, authority_id, assessment_key)
);

CREATE TABLE corner.assessment_stream_evidence (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    assessment_id UUID NOT NULL REFERENCES corner.actionability_assessments(id) ON DELETE RESTRICT,
    stream_role TEXT NOT NULL CHECK (stream_role IN ('target', 'reference')),
    sportsbook_id UUID NOT NULL REFERENCES corner.sportsbooks(id) ON DELETE RESTRICT,
    outcome_id UUID NOT NULL REFERENCES corner.outcomes(id) ON DELETE RESTRICT,
    selection_kind TEXT NOT NULL CHECK (selection_kind IN ('selected_trusted_observation', 'missing_trusted_observation')),
    selected_observation_id UUID REFERENCES corner.odds_observations(id) ON DELETE RESTRICT,
    selected_disposition_id UUID REFERENCES corner.observation_dispositions(id) ON DELETE RESTRICT,
    missing_reason TEXT,
    evidence_snapshot JSONB NOT NULL CHECK (jsonb_typeof(evidence_snapshot) = 'object'),
    CONSTRAINT assessment_stream_evidence_selection_shape CHECK (
        (selection_kind = 'selected_trusted_observation' AND selected_observation_id IS NOT NULL AND missing_reason IS NULL)
        OR (selection_kind = 'missing_trusted_observation' AND selected_observation_id IS NULL
            AND selected_disposition_id IS NULL AND missing_reason IS NOT NULL AND btrim(missing_reason) <> '')),
    CONSTRAINT assessment_stream_evidence_stream_key UNIQUE (assessment_id, sportsbook_id, outcome_id)
);
CREATE UNIQUE INDEX assessment_stream_evidence_one_target_idx
ON corner.assessment_stream_evidence (assessment_id) WHERE stream_role = 'target';
CREATE INDEX actionability_assessments_judgment_history_idx
ON corner.actionability_assessments (qualification_decision_id, assessed_at DESC, id DESC);

CREATE TRIGGER actionability_assessments_immutable
BEFORE UPDATE OR DELETE ON corner.actionability_assessments
FOR EACH ROW EXECUTE FUNCTION corner.reject_immutable_change();
CREATE TRIGGER actionability_assessments_no_truncate
BEFORE TRUNCATE ON corner.actionability_assessments
FOR EACH STATEMENT EXECUTE FUNCTION corner.reject_immutable_change();
CREATE TRIGGER assessment_stream_evidence_immutable
BEFORE UPDATE OR DELETE ON corner.assessment_stream_evidence
FOR EACH ROW EXECUTE FUNCTION corner.reject_immutable_change();
CREATE TRIGGER assessment_stream_evidence_no_truncate
BEFORE TRUNCATE ON corner.assessment_stream_evidence
FOR EACH STATEMENT EXECUTE FUNCTION corner.reject_immutable_change();
REVOKE ALL ON corner.actionability_assessments, corner.assessment_stream_evidence FROM PUBLIC;
COMMIT;
