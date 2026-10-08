BEGIN;

-- The newest sportsbook links (event, market, betslip) for each outcome at each sportsbook.
-- This is navigation metadata, not evidence: it is replaced by newer captures and never read by the
-- calculators, so the immutable observation ledger is untouched. Links are validated before insert
-- (https, on the sportsbook's own domain); the CHECKs are a second line of defence.
CREATE TABLE corner.quote_links (
    outcome_id UUID NOT NULL REFERENCES corner.outcomes(id) ON DELETE RESTRICT,
    sportsbook_id UUID NOT NULL REFERENCES corner.sportsbooks(id) ON DELETE RESTRICT,
    event_url TEXT,
    market_url TEXT,
    outcome_url TEXT,
    captured_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (outcome_id, sportsbook_id),
    CONSTRAINT quote_links_https CHECK (
        (event_url IS NULL OR (event_url LIKE 'https://%' AND length(event_url) <= 2048)) AND
        (market_url IS NULL OR (market_url LIKE 'https://%' AND length(market_url) <= 2048)) AND
        (outcome_url IS NULL OR (outcome_url LIKE 'https://%' AND length(outcome_url) <= 2048))),
    CONSTRAINT quote_links_any CHECK (event_url IS NOT NULL OR market_url IS NOT NULL OR outcome_url IS NOT NULL)
);

REVOKE ALL ON corner.quote_links FROM PUBLIC;

COMMIT;
