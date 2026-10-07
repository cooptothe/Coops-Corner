BEGIN;

CREATE TABLE corner.disposition_types (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    code TEXT NOT NULL UNIQUE CHECK (code IN ('rejected', 'reinstated')),
    display_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO corner.disposition_types (code, display_name)
VALUES ('rejected', 'Rejected'), ('reinstated', 'Reinstated');

CREATE TABLE corner.observation_dispositions (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    observation_id UUID NOT NULL REFERENCES corner.odds_observations(id) ON DELETE RESTRICT,
    disposition_type_id UUID NOT NULL REFERENCES corner.disposition_types(id) ON DELETE RESTRICT,
    decision_key TEXT NOT NULL CHECK (btrim(decision_key) <> ''),
    reason TEXT NOT NULL CHECK (btrim(reason) <> ''),
    decided_at TIMESTAMPTZ NOT NULL,
    authority_kind TEXT NOT NULL CHECK (authority_kind IN ('human', 'service')),
    authority_id TEXT NOT NULL CHECK (btrim(authority_id) <> ''),
    authority_metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT observation_dispositions_command_key
        UNIQUE (authority_kind, authority_id, decision_key)
);

CREATE INDEX observation_dispositions_latest_idx
ON corner.observation_dispositions (observation_id, decided_at DESC, id DESC);

CREATE TRIGGER observation_dispositions_immutable
BEFORE UPDATE OR DELETE ON corner.observation_dispositions
FOR EACH ROW EXECUTE FUNCTION corner.reject_immutable_change();
CREATE TRIGGER observation_dispositions_no_truncate
BEFORE TRUNCATE ON corner.observation_dispositions
FOR EACH STATEMENT EXECUTE FUNCTION corner.reject_immutable_change();
CREATE TRIGGER disposition_types_immutable
BEFORE UPDATE OR DELETE ON corner.disposition_types
FOR EACH ROW EXECUTE FUNCTION corner.reject_immutable_change();

REVOKE ALL ON corner.observation_dispositions FROM PUBLIC;
REVOKE ALL ON corner.disposition_types FROM PUBLIC;

COMMIT;
