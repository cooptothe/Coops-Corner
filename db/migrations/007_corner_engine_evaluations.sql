BEGIN;

CREATE TABLE corner.engine_evaluations (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    authority_kind TEXT NOT NULL CHECK (authority_kind IN ('human', 'service')),
    authority_id TEXT NOT NULL CHECK (btrim(authority_id) <> ''),
    evaluation_key TEXT NOT NULL CHECK (btrim(evaluation_key) <> ''),
    evaluated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    engine_name TEXT NOT NULL CHECK (btrim(engine_name) <> ''),
    engine_version TEXT NOT NULL CHECK (btrim(engine_version) <> ''),
    engine_revision TEXT NOT NULL CHECK (btrim(engine_revision) <> ''),
    configuration_version TEXT NOT NULL CHECK (btrim(configuration_version) <> ''),
    snapshot_format_version TEXT NOT NULL CHECK (btrim(snapshot_format_version) <> ''),
    target_observation_id UUID NOT NULL REFERENCES corner.odds_observations(id) ON DELETE RESTRICT,
    market_id UUID NOT NULL REFERENCES corner.markets(id) ON DELETE RESTRICT,
    competition_id UUID NOT NULL REFERENCES corner.competitions(id) ON DELETE RESTRICT,
    result_kind TEXT NOT NULL CHECK (result_kind IN ('evaluated', 'not_evaluable')),
    non_evaluation_reason TEXT CHECK (btrim(non_evaluation_reason) <> ''),
    fair_probability NUMERIC(12,10) CHECK (fair_probability >= 0 AND fair_probability <= 1),
    ev_ratio NUMERIC(12,8) CHECK (ev_ratio <> 'NaN'::numeric),
    reference_book_count INTEGER NOT NULL CHECK (reference_book_count >= 0),
    command_snapshot JSONB NOT NULL CHECK (jsonb_typeof(command_snapshot) = 'object'),
    command_sha256 BYTEA NOT NULL CHECK (octet_length(command_sha256) = 32),
    result_snapshot JSONB NOT NULL CHECK (jsonb_typeof(result_snapshot) = 'object'),
    result_sha256 BYTEA NOT NULL CHECK (octet_length(result_sha256) = 32),
    CONSTRAINT engine_evaluations_command_key UNIQUE (authority_kind, authority_id, evaluation_key),
    CONSTRAINT engine_evaluations_result_shape CHECK (
        (result_kind = 'evaluated' AND non_evaluation_reason IS NULL
         AND fair_probability IS NOT NULL AND ev_ratio IS NOT NULL)
        OR (result_kind = 'not_evaluable' AND non_evaluation_reason IS NOT NULL
            AND fair_probability IS NULL AND ev_ratio IS NULL)
    )
);

CREATE TABLE corner.engine_evaluation_inputs (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    evaluation_id UUID NOT NULL REFERENCES corner.engine_evaluations(id) ON DELETE RESTRICT,
    observation_id UUID NOT NULL REFERENCES corner.odds_observations(id) ON DELETE RESTRICT,
    role TEXT NOT NULL CHECK (role IN ('target', 'reference')),
    CONSTRAINT engine_evaluation_inputs_observation_key UNIQUE (evaluation_id, observation_id)
);
CREATE UNIQUE INDEX engine_evaluation_inputs_one_target
ON corner.engine_evaluation_inputs (evaluation_id) WHERE role = 'target';
CREATE INDEX engine_evaluation_inputs_reverse_idx
ON corner.engine_evaluation_inputs (observation_id);

CREATE TRIGGER engine_evaluations_immutable
BEFORE UPDATE OR DELETE ON corner.engine_evaluations
FOR EACH ROW EXECUTE FUNCTION corner.reject_immutable_change();
CREATE TRIGGER engine_evaluations_no_truncate
BEFORE TRUNCATE ON corner.engine_evaluations
FOR EACH STATEMENT EXECUTE FUNCTION corner.reject_immutable_change();
CREATE TRIGGER engine_evaluation_inputs_immutable
BEFORE UPDATE OR DELETE ON corner.engine_evaluation_inputs
FOR EACH ROW EXECUTE FUNCTION corner.reject_immutable_change();
CREATE TRIGGER engine_evaluation_inputs_no_truncate
BEFORE TRUNCATE ON corner.engine_evaluation_inputs
FOR EACH STATEMENT EXECUTE FUNCTION corner.reject_immutable_change();

REVOKE ALL ON corner.engine_evaluations, corner.engine_evaluation_inputs FROM PUBLIC;
COMMIT;
