BEGIN;

CREATE TABLE corner.events (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    competition_id UUID NOT NULL REFERENCES corner.competitions(id) ON DELETE RESTRICT,
    scheduled_start TIMESTAMPTZ NOT NULL,
    event_status_id UUID NOT NULL REFERENCES corner.event_statuses(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE corner.event_participants (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    event_id UUID NOT NULL REFERENCES corner.events(id) ON DELETE RESTRICT,
    participant_id UUID NOT NULL REFERENCES corner.participants(id) ON DELETE RESTRICT,
    role TEXT NOT NULL CHECK (role IN ('home', 'away', 'competitor')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT event_participants_event_participant_key UNIQUE (event_id, participant_id)
);

CREATE TABLE corner.markets (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    event_id UUID NOT NULL REFERENCES corner.events(id) ON DELETE RESTRICT,
    market_type_id UUID NOT NULL REFERENCES corner.market_types(id) ON DELETE RESTRICT,
    scope_id UUID NOT NULL REFERENCES corner.scopes(id) ON DELETE RESTRICT,
    subject_participant_id UUID REFERENCES corner.participants(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT markets_contract_key UNIQUE NULLS NOT DISTINCT (
        event_id,
        market_type_id,
        scope_id,
        subject_participant_id
    )
);

CREATE TABLE corner.outcomes (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    market_id UUID NOT NULL REFERENCES corner.markets(id) ON DELETE RESTRICT,
    selected_participant_id UUID REFERENCES corner.participants(id) ON DELETE RESTRICT,
    outcome_side_id UUID NOT NULL REFERENCES corner.outcome_sides(id) ON DELETE RESTRICT,
    point NUMERIC(12, 4),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT outcomes_contract_key UNIQUE NULLS NOT DISTINCT (
        market_id,
        selected_participant_id,
        outcome_side_id,
        point
    )
);

CREATE TABLE corner.competition_provider_identities (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    provider_id UUID NOT NULL REFERENCES corner.providers(id) ON DELETE RESTRICT,
    competition_id UUID NOT NULL REFERENCES corner.competitions(id) ON DELETE RESTRICT,
    external_id TEXT NOT NULL CHECK (btrim(external_id) <> ''),
    external_name TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT competition_provider_external_key UNIQUE (provider_id, external_id)
);

CREATE UNIQUE INDEX competition_provider_current_identity_key
ON corner.competition_provider_identities (provider_id, competition_id)
WHERE active;

CREATE TABLE corner.event_provider_identities (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    provider_id UUID NOT NULL REFERENCES corner.providers(id) ON DELETE RESTRICT,
    event_id UUID NOT NULL REFERENCES corner.events(id) ON DELETE RESTRICT,
    external_id TEXT NOT NULL CHECK (btrim(external_id) <> ''),
    external_name TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT event_provider_external_key UNIQUE (provider_id, external_id)
);

CREATE UNIQUE INDEX event_provider_current_identity_key
ON corner.event_provider_identities (provider_id, event_id)
WHERE active;

CREATE TABLE corner.participant_provider_identities (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    provider_id UUID NOT NULL REFERENCES corner.providers(id) ON DELETE RESTRICT,
    participant_id UUID NOT NULL REFERENCES corner.participants(id) ON DELETE RESTRICT,
    external_id TEXT NOT NULL CHECK (btrim(external_id) <> ''),
    external_name TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT participant_provider_external_key UNIQUE (provider_id, external_id)
);

CREATE UNIQUE INDEX participant_provider_current_identity_key
ON corner.participant_provider_identities (provider_id, participant_id)
WHERE active;

CREATE TABLE corner.sportsbook_provider_identities (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    provider_id UUID NOT NULL REFERENCES corner.providers(id) ON DELETE RESTRICT,
    sportsbook_id UUID NOT NULL REFERENCES corner.sportsbooks(id) ON DELETE RESTRICT,
    external_id TEXT NOT NULL CHECK (btrim(external_id) <> ''),
    external_name TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT sportsbook_provider_external_key UNIQUE (provider_id, external_id)
);

CREATE UNIQUE INDEX sportsbook_provider_current_identity_key
ON corner.sportsbook_provider_identities (provider_id, sportsbook_id)
WHERE active;

CREATE TABLE corner.provider_market_mappings (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    provider_id UUID NOT NULL REFERENCES corner.providers(id) ON DELETE RESTRICT,
    provider_market_key TEXT NOT NULL CHECK (btrim(provider_market_key) <> ''),
    market_type_id UUID NOT NULL REFERENCES corner.market_types(id) ON DELETE RESTRICT,
    default_scope_id UUID NOT NULL REFERENCES corner.scopes(id) ON DELETE RESTRICT,
    requires_subject BOOLEAN NOT NULL DEFAULT FALSE,
    requires_point BOOLEAN NOT NULL DEFAULT FALSE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT provider_market_mappings_provider_key UNIQUE (provider_id, provider_market_key)
);

CREATE TABLE corner.provider_participant_aliases (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    provider_id UUID NOT NULL REFERENCES corner.providers(id) ON DELETE RESTRICT,
    competition_id UUID NOT NULL REFERENCES corner.competitions(id) ON DELETE RESTRICT,
    raw_name TEXT NOT NULL CHECK (btrim(raw_name) <> ''),
    participant_id UUID REFERENCES corner.participants(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX provider_participant_aliases_lookup_idx
ON corner.provider_participant_aliases (provider_id, competition_id, raw_name);

CREATE INDEX markets_event_id_idx ON corner.markets (event_id);
CREATE INDEX outcomes_market_id_idx ON corner.outcomes (market_id);
CREATE INDEX events_competition_scheduled_start_idx
ON corner.events (competition_id, scheduled_start);

CREATE TRIGGER events_set_updated_at
BEFORE UPDATE ON corner.events
FOR EACH ROW EXECUTE FUNCTION corner.set_updated_at();
CREATE TRIGGER event_participants_set_updated_at
BEFORE UPDATE ON corner.event_participants
FOR EACH ROW EXECUTE FUNCTION corner.set_updated_at();
CREATE TRIGGER markets_set_updated_at
BEFORE UPDATE ON corner.markets
FOR EACH ROW EXECUTE FUNCTION corner.set_updated_at();
CREATE TRIGGER outcomes_set_updated_at
BEFORE UPDATE ON corner.outcomes
FOR EACH ROW EXECUTE FUNCTION corner.set_updated_at();
CREATE TRIGGER competition_provider_identities_set_updated_at
BEFORE UPDATE ON corner.competition_provider_identities
FOR EACH ROW EXECUTE FUNCTION corner.set_updated_at();
CREATE TRIGGER event_provider_identities_set_updated_at
BEFORE UPDATE ON corner.event_provider_identities
FOR EACH ROW EXECUTE FUNCTION corner.set_updated_at();
CREATE TRIGGER participant_provider_identities_set_updated_at
BEFORE UPDATE ON corner.participant_provider_identities
FOR EACH ROW EXECUTE FUNCTION corner.set_updated_at();
CREATE TRIGGER sportsbook_provider_identities_set_updated_at
BEFORE UPDATE ON corner.sportsbook_provider_identities
FOR EACH ROW EXECUTE FUNCTION corner.set_updated_at();
CREATE TRIGGER provider_market_mappings_set_updated_at
BEFORE UPDATE ON corner.provider_market_mappings
FOR EACH ROW EXECUTE FUNCTION corner.set_updated_at();
CREATE TRIGGER provider_participant_aliases_set_updated_at
BEFORE UPDATE ON corner.provider_participant_aliases
FOR EACH ROW EXECUTE FUNCTION corner.set_updated_at();

COMMIT;
