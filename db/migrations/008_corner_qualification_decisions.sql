BEGIN;

-- Candidate key enforces the exact result claimed by each qualification.
ALTER TABLE corner.engine_evaluations
ADD CONSTRAINT engine_evaluations_id_result_key UNIQUE (id, result_sha256);

CREATE TABLE corner.qualification_decisions (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    engine_evaluation_id UUID NOT NULL,
    evaluation_result_sha256 BYTEA NOT NULL CHECK (octet_length(evaluation_result_sha256) = 32),
    authority_kind TEXT NOT NULL CHECK (authority_kind IN ('human', 'service')),
    authority_id TEXT NOT NULL CHECK (btrim(authority_id) <> ''),
    qualification_key TEXT NOT NULL CHECK (btrim(qualification_key) <> ''),
    policy_name TEXT NOT NULL CHECK (btrim(policy_name) <> ''),
    policy_version TEXT NOT NULL CHECK (btrim(policy_version) <> ''),
    policy_revision TEXT NOT NULL CHECK (btrim(policy_revision) <> ''),
    qualification_snapshot_format_version TEXT NOT NULL CHECK (btrim(qualification_snapshot_format_version) <> ''),
    decision_kind TEXT NOT NULL CHECK (decision_kind IN ('qualified', 'not_qualified', 'not_qualifiable')),
    reason_code TEXT NOT NULL CHECK (btrim(reason_code) <> ''),
    decided_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    command_snapshot JSONB NOT NULL CHECK (jsonb_typeof(command_snapshot) = 'object'),
    command_sha256 BYTEA NOT NULL CHECK (octet_length(command_sha256) = 32),
    result_snapshot JSONB NOT NULL CHECK (jsonb_typeof(result_snapshot) = 'object'),
    result_sha256 BYTEA NOT NULL CHECK (octet_length(result_sha256) = 32),
    CONSTRAINT qualification_decisions_evaluation_result_fk
        FOREIGN KEY (engine_evaluation_id, evaluation_result_sha256)
        REFERENCES corner.engine_evaluations (id, result_sha256) ON DELETE RESTRICT,
    CONSTRAINT qualification_decisions_command_key
        UNIQUE (authority_kind, authority_id, qualification_key)
);

CREATE INDEX qualification_decisions_evaluation_history_idx
ON corner.qualification_decisions (engine_evaluation_id, decided_at DESC, id DESC);

CREATE TRIGGER qualification_decisions_immutable
BEFORE UPDATE OR DELETE ON corner.qualification_decisions
FOR EACH ROW EXECUTE FUNCTION corner.reject_immutable_change();
CREATE TRIGGER qualification_decisions_no_truncate
BEFORE TRUNCATE ON corner.qualification_decisions
FOR EACH STATEMENT EXECUTE FUNCTION corner.reject_immutable_change();

REVOKE ALL ON corner.qualification_decisions FROM PUBLIC;
COMMIT;
