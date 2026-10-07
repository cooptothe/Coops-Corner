BEGIN;

-- The legacy public.sports/games/odds tables remain migration sources.
-- The Corner's canonical v1 model lives in its own schema.
CREATE SCHEMA corner;

CREATE FUNCTION corner.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

CREATE TABLE corner.market_types (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    code TEXT NOT NULL UNIQUE CHECK (btrim(code) <> ''),
    display_name TEXT NOT NULL CHECK (btrim(display_name) <> ''),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE corner.scopes (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    code TEXT NOT NULL UNIQUE CHECK (btrim(code) <> ''),
    display_name TEXT NOT NULL CHECK (btrim(display_name) <> ''),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE corner.participant_types (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    code TEXT NOT NULL UNIQUE CHECK (btrim(code) <> ''),
    display_name TEXT NOT NULL CHECK (btrim(display_name) <> ''),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE corner.sportsbook_categories (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    code TEXT NOT NULL UNIQUE CHECK (btrim(code) <> ''),
    display_name TEXT NOT NULL CHECK (btrim(display_name) <> ''),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE corner.event_statuses (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    code TEXT NOT NULL UNIQUE CHECK (btrim(code) <> ''),
    display_name TEXT NOT NULL CHECK (btrim(display_name) <> ''),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE corner.quote_states (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    code TEXT NOT NULL UNIQUE CHECK (btrim(code) <> ''),
    display_name TEXT NOT NULL CHECK (btrim(display_name) <> ''),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE corner.outcome_sides (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    code TEXT NOT NULL UNIQUE CHECK (btrim(code) <> ''),
    display_name TEXT NOT NULL CHECK (btrim(display_name) <> ''),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE corner.providers (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    code TEXT NOT NULL UNIQUE CHECK (btrim(code) <> ''),
    display_name TEXT NOT NULL CHECK (btrim(display_name) <> ''),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE corner.sports (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    code TEXT NOT NULL UNIQUE CHECK (btrim(code) <> ''),
    display_name TEXT NOT NULL CHECK (btrim(display_name) <> ''),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE corner.competitions (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    sport_id UUID NOT NULL REFERENCES corner.sports(id) ON DELETE RESTRICT,
    code TEXT NOT NULL CHECK (btrim(code) <> ''),
    display_name TEXT NOT NULL CHECK (btrim(display_name) <> ''),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT competitions_sport_code_key UNIQUE (sport_id, code)
);

CREATE TABLE corner.participants (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    participant_type_id UUID NOT NULL REFERENCES corner.participant_types(id) ON DELETE RESTRICT,
    display_name TEXT NOT NULL CHECK (btrim(display_name) <> ''),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE corner.sportsbooks (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    code TEXT NOT NULL UNIQUE CHECK (btrim(code) <> ''),
    display_name TEXT NOT NULL CHECK (btrim(display_name) <> ''),
    sportsbook_category_id UUID NOT NULL REFERENCES corner.sportsbook_categories(id) ON DELETE RESTRICT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TRIGGER market_types_set_updated_at
BEFORE UPDATE ON corner.market_types
FOR EACH ROW EXECUTE FUNCTION corner.set_updated_at();
CREATE TRIGGER scopes_set_updated_at
BEFORE UPDATE ON corner.scopes
FOR EACH ROW EXECUTE FUNCTION corner.set_updated_at();
CREATE TRIGGER participant_types_set_updated_at
BEFORE UPDATE ON corner.participant_types
FOR EACH ROW EXECUTE FUNCTION corner.set_updated_at();
CREATE TRIGGER sportsbook_categories_set_updated_at
BEFORE UPDATE ON corner.sportsbook_categories
FOR EACH ROW EXECUTE FUNCTION corner.set_updated_at();
CREATE TRIGGER event_statuses_set_updated_at
BEFORE UPDATE ON corner.event_statuses
FOR EACH ROW EXECUTE FUNCTION corner.set_updated_at();
CREATE TRIGGER quote_states_set_updated_at
BEFORE UPDATE ON corner.quote_states
FOR EACH ROW EXECUTE FUNCTION corner.set_updated_at();
CREATE TRIGGER outcome_sides_set_updated_at
BEFORE UPDATE ON corner.outcome_sides
FOR EACH ROW EXECUTE FUNCTION corner.set_updated_at();
CREATE TRIGGER providers_set_updated_at
BEFORE UPDATE ON corner.providers
FOR EACH ROW EXECUTE FUNCTION corner.set_updated_at();
CREATE TRIGGER sports_set_updated_at
BEFORE UPDATE ON corner.sports
FOR EACH ROW EXECUTE FUNCTION corner.set_updated_at();
CREATE TRIGGER competitions_set_updated_at
BEFORE UPDATE ON corner.competitions
FOR EACH ROW EXECUTE FUNCTION corner.set_updated_at();
CREATE TRIGGER participants_set_updated_at
BEFORE UPDATE ON corner.participants
FOR EACH ROW EXECUTE FUNCTION corner.set_updated_at();
CREATE TRIGGER sportsbooks_set_updated_at
BEFORE UPDATE ON corner.sportsbooks
FOR EACH ROW EXECUTE FUNCTION corner.set_updated_at();

COMMIT;
