-- The Corner odds storage. Run on a new PostgreSQL database.
-- `odds` is append-only: each row is one observed price at one fetch time.

CREATE TABLE sports (
    id SERIAL PRIMARY KEY,
    key VARCHAR(100) UNIQUE NOT NULL,
    title VARCHAR(100) NOT NULL
);

CREATE TABLE games (
    id UUID PRIMARY KEY,
    sport_id INT NOT NULL REFERENCES sports(id),
    game_date TIMESTAMPTZ NOT NULL,
    home_team VARCHAR(100) NOT NULL,
    away_team VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'upcoming',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE odds (
    id BIGSERIAL PRIMARY KEY,
    game_id UUID NOT NULL REFERENCES games(id),
    sportsbook VARCHAR(50) NOT NULL,
    market VARCHAR(20) NOT NULL,
    side VARCHAR(20) NOT NULL,
    price DECIMAL(10, 2),
    decimal_price DECIMAL(10, 4) NOT NULL CHECK (decimal_price > 1),
    implied_prob DECIMAL(10, 6),
    point DECIMAL(10, 3),
    betslip_link TEXT,
    market_link TEXT,
    event_link TEXT,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX odds_game_fetched_at_idx ON odds (game_id, fetched_at DESC);
CREATE INDEX odds_current_lookup_idx ON odds (game_id, sportsbook, market, side, point, fetched_at DESC);

