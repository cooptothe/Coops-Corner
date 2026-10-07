BEGIN;

CREATE TABLE corner.ingestion_batches (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    provider_id UUID NOT NULL REFERENCES corner.providers(id) ON DELETE RESTRICT,
    endpoint_context JSONB NOT NULL DEFAULT '{}'::jsonb,
    processing_status TEXT NOT NULL DEFAULT 'started' CHECK (
        processing_status IN ('started', 'response_received', 'processing', 'completed', 'failed')
    ),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    failure_metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ingestion_batches_id_provider_key UNIQUE (id, provider_id),
    CONSTRAINT ingestion_batches_completion_after_start_check
        CHECK (completed_at IS NULL OR completed_at >= started_at)
);

CREATE TABLE corner.provider_payloads (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    ingestion_batch_id UUID NOT NULL,
    provider_id UUID NOT NULL REFERENCES corner.providers(id) ON DELETE RESTRICT,
    received_at TIMESTAMPTZ NOT NULL,
    http_status SMALLINT NOT NULL CHECK (http_status BETWEEN 100 AND 599),
    content_type TEXT,
    payload_sha256 BYTEA NOT NULL CHECK (octet_length(payload_sha256) = 32),
    raw_body BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT provider_payloads_batch_provider_fk
        FOREIGN KEY (ingestion_batch_id, provider_id)
        REFERENCES corner.ingestion_batches (id, provider_id)
        ON DELETE RESTRICT,
    CONSTRAINT provider_payloads_id_provider_key UNIQUE (id, provider_id)
);

CREATE TABLE corner.odds_observations (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    provider_payload_id UUID NOT NULL,
    provider_id UUID NOT NULL,
    outcome_id UUID NOT NULL REFERENCES corner.outcomes(id) ON DELETE RESTRICT,
    sportsbook_id UUID NOT NULL REFERENCES corner.sportsbooks(id) ON DELETE RESTRICT,
    quote_state_id UUID NOT NULL REFERENCES corner.quote_states(id) ON DELETE RESTRICT,
    source_record_key TEXT NOT NULL CHECK (btrim(source_record_key) <> ''),
    decimal_odds NUMERIC(12, 6) CHECK (decimal_odds IS NULL OR decimal_odds > 1),
    provider_updated_at TIMESTAMPTZ,
    observed_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT odds_observations_payload_provider_fk
        FOREIGN KEY (provider_payload_id, provider_id)
        REFERENCES corner.provider_payloads (id, provider_id)
        ON DELETE RESTRICT,
    CONSTRAINT odds_observations_payload_source_key UNIQUE (provider_payload_id, source_record_key)
);

CREATE INDEX odds_observations_current_quote_idx
ON corner.odds_observations (outcome_id, sportsbook_id, observed_at DESC, id DESC);

CREATE FUNCTION corner.reject_immutable_change()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION '% is immutable', TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME;
END;
$$;

CREATE TRIGGER provider_payloads_immutable
BEFORE UPDATE OR DELETE ON corner.provider_payloads
FOR EACH ROW EXECUTE FUNCTION corner.reject_immutable_change();
CREATE TRIGGER odds_observations_immutable
BEFORE UPDATE OR DELETE ON corner.odds_observations
FOR EACH ROW EXECUTE FUNCTION corner.reject_immutable_change();
CREATE TRIGGER ingestion_batches_set_updated_at
BEFORE UPDATE ON corner.ingestion_batches
FOR EACH ROW EXECUTE FUNCTION corner.set_updated_at();

COMMIT;
