BEGIN;
-- Same evidence/eligibility/tie-breaking as trusted_current_quotes, but one
-- indexed stream probe stops at its first eligible observation. Never push
-- active-state or freshness predicates before this winner is selected.
CREATE OR REPLACE FUNCTION corner.trusted_quote_for_stream(
    requested_outcome uuid, requested_book uuid
) RETURNS SETOF corner.trusted_current_quotes
LANGUAGE sql STABLE SECURITY DEFINER ROWS 1
SET search_path = pg_catalog
AS $quote$
SELECT
    o.id AS observation_id,
    o.outcome_id,
    o.sportsbook_id,
    o.provider_id,
    o.provider_payload_id,
    o.quote_state_id,
    o.decimal_odds,
    o.observed_at,
    o.provider_updated_at,
    o.created_at AS observation_created_at,
    judgment.id AS latest_disposition_id,
    kind.code AS latest_disposition_code,
    judgment.decided_at AS disposition_decided_at,
    judgment.created_at AS disposition_created_at
FROM corner.odds_observations o
LEFT JOIN LATERAL (
    SELECT d.id, d.disposition_type_id, d.decided_at, d.created_at
    FROM corner.observation_dispositions d
    WHERE d.observation_id = o.id
    ORDER BY d.decided_at DESC, d.id DESC
    LIMIT 1
) judgment ON TRUE
LEFT JOIN corner.disposition_types kind ON kind.id = judgment.disposition_type_id
WHERE o.outcome_id = requested_outcome AND o.sportsbook_id = requested_book
  AND (judgment.id IS NULL OR kind.code = 'reinstated')
ORDER BY o.observed_at DESC, o.id DESC
LIMIT 1;
$quote$;
REVOKE ALL ON FUNCTION corner.trusted_quote_for_stream(uuid, uuid) FROM PUBLIC;
DO $grant$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='corner_api') THEN
        GRANT EXECUTE ON FUNCTION corner.trusted_quote_for_stream(uuid, uuid) TO corner_api;
    END IF;
END;
$grant$;
COMMIT;
