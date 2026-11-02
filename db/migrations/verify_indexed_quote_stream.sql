-- All synthetic observations and decisions are rolled back, never published.
BEGIN;
SET LOCAL statement_timeout = '15000ms';
DO $verify$
DECLARE
    seed corner.odds_observations%ROWTYPE;
    selected_id uuid;
    expected_state uuid;
    state_name text;
    stamp timestamptz;
    fast jsonb;
    original jsonb;
BEGIN
    SELECT * INTO seed FROM corner.odds_observations LIMIT 1;
    IF seed.id IS NULL THEN RAISE EXCEPTION 'Existing quote evidence required for verification'; END IF;
    SELECT greatest(now(), observed_at) INTO stamp FROM corner.odds_observations
      WHERE outcome_id=seed.outcome_id AND sportsbook_id=seed.sportsbook_id
      ORDER BY observed_at DESC,id DESC LIMIT 1;
    FOREACH state_name IN ARRAY ARRAY['active','suspended','unavailable'] LOOP
        stamp := stamp + interval '1 second';
        INSERT INTO corner.quote_states(code,display_name) VALUES(state_name,initcap(state_name))
          ON CONFLICT(code) DO NOTHING;
        SELECT id INTO STRICT expected_state FROM corner.quote_states WHERE code=state_name;
        INSERT INTO corner.odds_observations
          (provider_payload_id,provider_id,outcome_id,sportsbook_id,quote_state_id,
           source_record_key,decimal_odds,observed_at)
        VALUES(seed.provider_payload_id,seed.provider_id,seed.outcome_id,seed.sportsbook_id,
          expected_state,format('indexed-quote-verification/%s/%s',pg_backend_pid(),state_name),
          CASE WHEN state_name='active' THEN 2.15 ELSE NULL END,stamp)
        RETURNING id INTO selected_id;
        SELECT to_jsonb(q) INTO fast FROM corner.trusted_quote_for_stream(seed.outcome_id,seed.sportsbook_id) q;
        SELECT to_jsonb(q) INTO original FROM corner.trusted_current_quotes q
          WHERE outcome_id=seed.outcome_id AND sportsbook_id=seed.sportsbook_id;
        IF fast IS DISTINCT FROM original OR fast->>'observation_id' IS DISTINCT FROM selected_id::text THEN
          RAISE EXCEPTION 'Indexed quote state equivalence failed';
        END IF;
    END LOOP;
    FOREACH state_name IN ARRAY ARRAY['rejected','reinstated'] LOOP
        stamp := stamp + interval '1 second';
        INSERT INTO corner.observation_dispositions
          (observation_id,disposition_type_id,decision_key,reason,decided_at,authority_kind,authority_id)
        SELECT selected_id,id,format('indexed-quote-verification/%s/%s',pg_backend_pid(),state_name),
          'Rollback-only lookup verification',stamp,'service','indexed-quote-verification'
        FROM corner.disposition_types WHERE code=state_name;
        IF NOT FOUND THEN RAISE EXCEPTION 'Required disposition vocabulary missing'; END IF;
        SELECT to_jsonb(q) INTO fast FROM corner.trusted_quote_for_stream(seed.outcome_id,seed.sportsbook_id) q;
        SELECT to_jsonb(q) INTO original FROM corner.trusted_current_quotes q
          WHERE outcome_id=seed.outcome_id AND sportsbook_id=seed.sportsbook_id;
        IF fast IS DISTINCT FROM original THEN RAISE EXCEPTION 'Indexed quote decision equivalence failed'; END IF;
        IF state_name='reinstated' AND fast->>'observation_id' IS DISTINCT FROM selected_id::text THEN
          RAISE EXCEPTION 'Reinstated quote did not win';
        END IF;
    END LOOP;
END;
$verify$;
ROLLBACK;
SELECT json_build_object('result','indexed_quote_equivalence_passed',
                        'synthetic_changes_committed',0,'provider_calls',0);
