BEGIN;
CREATE TABLE corner.work_kinds (
    code TEXT PRIMARY KEY CHECK (btrim(code)<>''),
    display_name TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE
);
INSERT INTO corner.work_kinds(code,display_name) VALUES
    ('evaluate','Evaluate'),('qualify','Qualify'),('ensure_occurrence','Ensure occurrence'),
    ('assess','Assess actionability'),('apply_lifecycle','Apply lifecycle command');

CREATE TABLE corner.work_requests (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    work_kind TEXT NOT NULL REFERENCES corner.work_kinds(code) ON DELETE RESTRICT,
    deduplication_namespace TEXT NOT NULL CHECK (btrim(deduplication_namespace)<>''),
    deduplication_key TEXT NOT NULL CHECK (btrim(deduplication_key)<>''),
    condition_id UUID REFERENCES corner.opportunity_conditions(id) ON DELETE RESTRICT,
    generation_id UUID REFERENCES corner.qualification_channel_generations(id) ON DELETE RESTRICT,
    engine_evaluation_id UUID REFERENCES corner.engine_evaluations(id) ON DELETE RESTRICT,
    qualification_decision_id UUID REFERENCES corner.qualification_decisions(id) ON DELETE RESTRICT,
    actionability_assessment_id UUID REFERENCES corner.actionability_assessments(id) ON DELETE RESTRICT,
    channel_generation_activation_id UUID REFERENCES corner.channel_generation_activations(id) ON DELETE RESTRICT,
    trigger_observation_id UUID REFERENCES corner.odds_observations(id) ON DELETE RESTRICT,
    trigger_disposition_id UUID REFERENCES corner.observation_dispositions(id) ON DELETE RESTRICT,
    intent_format_version TEXT NOT NULL,
    intent_snapshot JSONB NOT NULL CHECK (jsonb_typeof(intent_snapshot)='object'),
    intent_sha256 BYTEA NOT NULL CHECK (octet_length(intent_sha256)=32),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(deduplication_namespace,deduplication_key),
    UNIQUE(id,work_kind)
);

CREATE TABLE corner.prepared_work_commands (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    work_request_id UUID NOT NULL UNIQUE REFERENCES corner.work_requests(id) ON DELETE RESTRICT,
    command_format_version TEXT NOT NULL,
    command_snapshot JSONB NOT NULL CHECK (jsonb_typeof(command_snapshot)='object'),
    command_sha256 BYTEA NOT NULL CHECK (octet_length(command_sha256)=32),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(id,work_request_id)
);

CREATE TABLE corner.work_executions (
    work_request_id UUID PRIMARY KEY,
    work_kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ready' CHECK (status IN ('ready','leased','retryable','waiting','blocked','completed')),
    available_at TIMESTAMPTZ,
    claim_count INTEGER NOT NULL DEFAULT 0 CHECK (claim_count>=0),
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count>=0),
    lease_owner TEXT,
    lease_token UUID,
    lease_expires_at TIMESTAMPTZ,
    waiting_reason TEXT,
    blocked_reason TEXT,
    last_error_code TEXT,
    last_error_details JSONB,
    completed_at TIMESTAMPTZ,
    prepared_command_id UUID,
    engine_evaluation_id UUID REFERENCES corner.engine_evaluations(id) ON DELETE RESTRICT,
    qualification_decision_id UUID REFERENCES corner.qualification_decisions(id) ON DELETE RESTRICT,
    opportunity_occurrence_id UUID REFERENCES corner.opportunity_occurrences(id) ON DELETE RESTRICT,
    actionability_assessment_id UUID REFERENCES corner.actionability_assessments(id) ON DELETE RESTRICT,
    lifecycle_application_id UUID REFERENCES corner.lifecycle_applications(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY(work_request_id,work_kind) REFERENCES corner.work_requests(id,work_kind) ON DELETE RESTRICT,
    FOREIGN KEY(prepared_command_id,work_request_id) REFERENCES corner.prepared_work_commands(id,work_request_id) ON DELETE RESTRICT,
    CHECK ((status='leased' AND lease_owner IS NOT NULL AND btrim(lease_owner)<>'' AND lease_token IS NOT NULL
                AND lease_expires_at IS NOT NULL AND completed_at IS NULL)
        OR (status<>'leased' AND lease_owner IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL)),
    CHECK (status NOT IN ('ready','retryable') OR available_at IS NOT NULL),
    CHECK ((status='waiting' AND waiting_reason IS NOT NULL AND btrim(waiting_reason)<>'') OR (status<>'waiting' AND waiting_reason IS NULL)),
    CHECK ((status='blocked' AND blocked_reason IS NOT NULL AND btrim(blocked_reason)<>'') OR (status<>'blocked' AND blocked_reason IS NULL)),
    CHECK ((status='completed' AND completed_at IS NOT NULL AND prepared_command_id IS NOT NULL AND
        num_nonnulls(engine_evaluation_id,qualification_decision_id,opportunity_occurrence_id,actionability_assessment_id,lifecycle_application_id)=1 AND
        ((work_kind='evaluate' AND engine_evaluation_id IS NOT NULL)
        OR (work_kind='qualify' AND qualification_decision_id IS NOT NULL)
        OR (work_kind='ensure_occurrence' AND opportunity_occurrence_id IS NOT NULL)
        OR (work_kind='assess' AND actionability_assessment_id IS NOT NULL)
        OR (work_kind='apply_lifecycle' AND lifecycle_application_id IS NOT NULL)))
        OR (status<>'completed' AND completed_at IS NULL AND
            num_nonnulls(engine_evaluation_id,qualification_decision_id,opportunity_occurrence_id,actionability_assessment_id,lifecycle_application_id)=0))
);
CREATE INDEX work_executions_due_idx ON corner.work_executions(available_at,work_request_id) WHERE status IN ('ready','retryable');
CREATE INDEX work_executions_expired_idx ON corner.work_executions(lease_expires_at,work_request_id) WHERE status='leased';

CREATE TRIGGER work_requests_immutable BEFORE UPDATE OR DELETE ON corner.work_requests
FOR EACH ROW EXECUTE FUNCTION corner.reject_immutable_change();
CREATE TRIGGER work_requests_no_truncate BEFORE TRUNCATE ON corner.work_requests
FOR EACH STATEMENT EXECUTE FUNCTION corner.reject_immutable_change();
CREATE TRIGGER prepared_work_commands_immutable BEFORE UPDATE OR DELETE ON corner.prepared_work_commands
FOR EACH ROW EXECUTE FUNCTION corner.reject_immutable_change();
CREATE TRIGGER prepared_work_commands_no_truncate BEFORE TRUNCATE ON corner.prepared_work_commands
FOR EACH STATEMENT EXECUTE FUNCTION corner.reject_immutable_change();
REVOKE ALL ON corner.work_kinds,corner.work_requests,corner.prepared_work_commands,corner.work_executions FROM PUBLIC;
COMMIT;
