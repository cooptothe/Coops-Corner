BEGIN;

-- Eligibility is evaluated BEFORE choosing the newest quote in each stream.
-- No quote-state, freshness, or historical-as-of filtering belongs here.
CREATE VIEW corner.trusted_current_quotes AS
SELECT DISTINCT ON (o.outcome_id, o.sportsbook_id)
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
WHERE judgment.id IS NULL OR kind.code = 'reinstated'
ORDER BY o.outcome_id, o.sportsbook_id, o.observed_at DESC, o.id DESC;

COMMENT ON VIEW corner.trusted_current_quotes IS
'Latest eligible evidence per outcome/sportsbook using presently stored decisions. '
'Preserves quote state and age; no actionability or historical knowledge-time semantics. '
'Providers compete within the same stream; no provider precedence policy.';

REVOKE ALL ON corner.trusted_current_quotes FROM PUBLIC;

COMMIT;
