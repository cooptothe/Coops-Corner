BEGIN;

-- Stable canonical identity, not a ledger and not a current-generation pointer.
CREATE TABLE corner.qualification_channels (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    code TEXT NOT NULL UNIQUE CHECK (btrim(code) <> ''),
    display_name TEXT NOT NULL CHECK (btrim(display_name) <> ''),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER qualification_channels_set_updated_at
BEFORE UPDATE ON corner.qualification_channels
FOR EACH ROW EXECUTE FUNCTION corner.set_updated_at();

CREATE TABLE corner.qualification_channel_generations (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    channel_id UUID NOT NULL REFERENCES corner.qualification_channels(id) ON DELETE RESTRICT,
    engine_name TEXT NOT NULL CHECK (btrim(engine_name) <> ''),
    engine_version TEXT NOT NULL CHECK (btrim(engine_version) <> ''),
    engine_revision TEXT NOT NULL CHECK (btrim(engine_revision) <> ''),
    qualification_name TEXT NOT NULL CHECK (btrim(qualification_name) <> ''),
    qualification_version TEXT NOT NULL CHECK (btrim(qualification_version) <> ''),
    qualification_revision TEXT NOT NULL CHECK (btrim(qualification_revision) <> ''),
    lifecycle_name TEXT NOT NULL CHECK (btrim(lifecycle_name) <> ''),
    lifecycle_version TEXT NOT NULL CHECK (btrim(lifecycle_version) <> ''),
    lifecycle_revision TEXT NOT NULL CHECK (btrim(lifecycle_revision) <> ''),
    snapshot_format_version TEXT NOT NULL CHECK (btrim(snapshot_format_version) <> ''),
    configuration_snapshot JSONB NOT NULL CHECK (jsonb_typeof(configuration_snapshot) = 'object'),
    configuration_sha256 BYTEA NOT NULL CHECK (octet_length(configuration_sha256) = 32),
    registration_authority_kind TEXT NOT NULL CHECK (registration_authority_kind IN ('human', 'service')),
    registration_authority_id TEXT NOT NULL CHECK (btrim(registration_authority_id) <> ''),
    registration_key TEXT NOT NULL CHECK (btrim(registration_key) <> ''),
    registration_command_snapshot JSONB NOT NULL CHECK (jsonb_typeof(registration_command_snapshot) = 'object'),
    registration_command_sha256 BYTEA NOT NULL CHECK (octet_length(registration_command_sha256) = 32),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT channel_generations_id_channel_key UNIQUE (id, channel_id),
    CONSTRAINT channel_generations_registration_key UNIQUE
        (registration_authority_kind, registration_authority_id, registration_key)
);
CREATE INDEX channel_generations_channel_idx ON corner.qualification_channel_generations (channel_id);

CREATE TABLE corner.channel_generation_activations (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    channel_id UUID NOT NULL REFERENCES corner.qualification_channels(id) ON DELETE RESTRICT,
    new_generation_id UUID NOT NULL,
    expected_previous_generation_id UUID,
    activation_sequence BIGINT NOT NULL CHECK (activation_sequence > 0),
    activated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    authority_kind TEXT NOT NULL CHECK (authority_kind IN ('human', 'service')),
    authority_id TEXT NOT NULL CHECK (btrim(authority_id) <> ''),
    activation_key TEXT NOT NULL CHECK (btrim(activation_key) <> ''),
    snapshot_format_version TEXT NOT NULL CHECK (btrim(snapshot_format_version) <> ''),
    command_snapshot JSONB NOT NULL CHECK (jsonb_typeof(command_snapshot) = 'object'),
    command_sha256 BYTEA NOT NULL CHECK (octet_length(command_sha256) = 32),
    CONSTRAINT channel_activations_new_generation_fk FOREIGN KEY (new_generation_id, channel_id)
        REFERENCES corner.qualification_channel_generations(id, channel_id) ON DELETE RESTRICT,
    -- MATCH SIMPLE deliberately skips the predecessor check for the NULL genesis
    -- predecessor; channel_id itself is mandatory and independently referenced.
    CONSTRAINT channel_activations_previous_generation_fk FOREIGN KEY (expected_previous_generation_id, channel_id)
        REFERENCES corner.qualification_channel_generations(id, channel_id) ON DELETE RESTRICT,
    CONSTRAINT channel_activations_successor_key UNIQUE NULLS NOT DISTINCT
        (channel_id, expected_previous_generation_id),
    CONSTRAINT channel_activations_generation_key UNIQUE (new_generation_id),
    CONSTRAINT channel_activations_sequence_key UNIQUE (channel_id, activation_sequence),
    CONSTRAINT channel_activations_command_key UNIQUE (authority_kind, authority_id, activation_key),
    CONSTRAINT channel_activations_distinct_generations CHECK
        (new_generation_id <> expected_previous_generation_id),
    CONSTRAINT channel_activations_genesis_shape CHECK
        ((activation_sequence = 1) = (expected_previous_generation_id IS NULL))
);

ALTER TABLE corner.qualification_decisions
ADD CONSTRAINT qualification_decisions_id_kind_key UNIQUE (id, decision_kind);

CREATE TABLE corner.opportunity_occurrences (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    qualification_decision_id UUID NOT NULL UNIQUE,
    qualification_decision_kind TEXT NOT NULL DEFAULT 'qualified'
        CHECK (qualification_decision_kind = 'qualified'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT opportunity_occurrences_qualified_decision_fk
        FOREIGN KEY (qualification_decision_id, qualification_decision_kind)
        REFERENCES corner.qualification_decisions(id, decision_kind) ON DELETE RESTRICT
);

CREATE TRIGGER channel_generations_immutable
BEFORE UPDATE OR DELETE ON corner.qualification_channel_generations
FOR EACH ROW EXECUTE FUNCTION corner.reject_immutable_change();
CREATE TRIGGER channel_generations_no_truncate
BEFORE TRUNCATE ON corner.qualification_channel_generations
FOR EACH STATEMENT EXECUTE FUNCTION corner.reject_immutable_change();
CREATE TRIGGER channel_activations_immutable
BEFORE UPDATE OR DELETE ON corner.channel_generation_activations
FOR EACH ROW EXECUTE FUNCTION corner.reject_immutable_change();
CREATE TRIGGER channel_activations_no_truncate
BEFORE TRUNCATE ON corner.channel_generation_activations
FOR EACH STATEMENT EXECUTE FUNCTION corner.reject_immutable_change();
CREATE TRIGGER opportunity_occurrences_immutable
BEFORE UPDATE OR DELETE ON corner.opportunity_occurrences
FOR EACH ROW EXECUTE FUNCTION corner.reject_immutable_change();
CREATE TRIGGER opportunity_occurrences_no_truncate
BEFORE TRUNCATE ON corner.opportunity_occurrences
FOR EACH STATEMENT EXECUTE FUNCTION corner.reject_immutable_change();

REVOKE ALL ON corner.qualification_channels, corner.qualification_channel_generations,
    corner.channel_generation_activations, corner.opportunity_occurrences FROM PUBLIC;
COMMIT;
