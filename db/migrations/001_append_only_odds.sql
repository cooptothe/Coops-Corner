-- Upgrade databases created with the original schema.sql.
-- This migration is non-destructive: no observations or games are deleted.

ALTER TABLE games ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE odds ADD COLUMN IF NOT EXISTS betslip_link TEXT;
ALTER TABLE odds ADD COLUMN IF NOT EXISTS market_link TEXT;
ALTER TABLE odds ADD COLUMN IF NOT EXISTS event_link TEXT;
ALTER TABLE odds ADD COLUMN IF NOT EXISTS fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE INDEX IF NOT EXISTS odds_game_fetched_at_idx ON odds (game_id, fetched_at DESC);
CREATE INDEX IF NOT EXISTS odds_current_lookup_idx ON odds (game_id, sportsbook, market, side, point, fetched_at DESC);
