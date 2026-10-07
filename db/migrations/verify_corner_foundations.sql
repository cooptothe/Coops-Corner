-- Verification only: this script always rolls back its fixture rows.
BEGIN;

DO $$
DECLARE
    provider_a_id UUID;
    provider_b_id UUID;
    sport_id UUID;
    competition_id UUID;
    participant_type_id UUID;
    participant_a_id UUID;
    participant_b_id UUID;
    category_id UUID;
    sportsbook_id UUID;
    event_status_id UUID;
    event_id UUID;
    market_type_id UUID;
    scope_id UUID;
    side_id UUID;
    quote_state_id UUID;
    market_id UUID;
    outcome_id UUID;
    batch_id UUID;
    payload_id UUID;
    observation_id UUID;
BEGIN
    INSERT INTO corner.providers (code, display_name)
    VALUES ('verify_provider_a', 'Verify Provider A')
    RETURNING id INTO provider_a_id;

    INSERT INTO corner.providers (code, display_name)
    VALUES ('verify_provider_b', 'Verify Provider B')
    RETURNING id INTO provider_b_id;

    INSERT INTO corner.sports (code, display_name)
    VALUES ('verify_sport', 'Verify Sport')
    RETURNING id INTO sport_id;

    INSERT INTO corner.competitions (sport_id, code, display_name)
    VALUES (sport_id, 'verify_competition', 'Verify Competition')
    RETURNING id INTO competition_id;

    INSERT INTO corner.participant_types (code, display_name)
    VALUES ('team', 'Team')
    RETURNING id INTO participant_type_id;

    INSERT INTO corner.participants (participant_type_id, display_name)
    VALUES (participant_type_id, 'Verify A')
    RETURNING id INTO participant_a_id;

    INSERT INTO corner.participants (participant_type_id, display_name)
    VALUES (participant_type_id, 'Verify B')
    RETURNING id INTO participant_b_id;

    INSERT INTO corner.sportsbook_categories (code, display_name)
    VALUES ('retail', 'Retail')
    RETURNING id INTO category_id;

    INSERT INTO corner.sportsbooks (code, display_name, sportsbook_category_id)
    VALUES ('verify_book', 'Verify Book', category_id)
    RETURNING id INTO sportsbook_id;

    INSERT INTO corner.event_statuses (code, display_name)
    VALUES ('scheduled', 'Scheduled')
    RETURNING id INTO event_status_id;

    INSERT INTO corner.market_types (code, display_name)
    VALUES ('moneyline', 'Moneyline')
    RETURNING id INTO market_type_id;

    INSERT INTO corner.scopes (code, display_name)
    VALUES ('full_game', 'Full Game')
    RETURNING id INTO scope_id;

    INSERT INTO corner.outcome_sides (code, display_name)
    VALUES ('home', 'Home')
    RETURNING id INTO side_id;

    INSERT INTO corner.quote_states (code, display_name)
    VALUES ('active', 'Active')
    RETURNING id INTO quote_state_id;

    INSERT INTO corner.events (competition_id, scheduled_start, event_status_id)
    VALUES (competition_id, now(), event_status_id)
    RETURNING id INTO event_id;

    IF uuid_extract_version(event_id) <> 7 THEN
        RAISE EXCEPTION 'expected UUIDv7 event identifier';
    END IF;

    INSERT INTO corner.event_participants (event_id, participant_id, role)
    VALUES (event_id, participant_a_id, 'home'), (event_id, participant_b_id, 'away');

    INSERT INTO corner.markets (event_id, market_type_id, scope_id)
    VALUES (event_id, market_type_id, scope_id)
    RETURNING id INTO market_id;

    INSERT INTO corner.outcomes (market_id, selected_participant_id, outcome_side_id)
    VALUES (market_id, participant_a_id, side_id)
    RETURNING id INTO outcome_id;

    BEGIN
        INSERT INTO corner.outcomes (market_id, selected_participant_id, outcome_side_id)
        VALUES (market_id, participant_a_id, side_id);
        RAISE EXCEPTION 'duplicate NULL-aware outcome identity was accepted';
    EXCEPTION WHEN unique_violation THEN
        NULL;
    END;

    INSERT INTO corner.ingestion_batches (provider_id)
    VALUES (provider_a_id)
    RETURNING id INTO batch_id;

    BEGIN
        INSERT INTO corner.provider_payloads (
            ingestion_batch_id, provider_id, received_at, http_status, payload_sha256, raw_body
        ) VALUES (
            batch_id, provider_b_id, now(), 200, decode(repeat('00', 32), 'hex'), convert_to('{}', 'UTF8')
        );
        RAISE EXCEPTION 'payload provider mismatch was accepted';
    EXCEPTION WHEN foreign_key_violation THEN
        NULL;
    END;

    INSERT INTO corner.provider_payloads (
        ingestion_batch_id, provider_id, received_at, http_status, payload_sha256, raw_body
    ) VALUES (
        batch_id, provider_a_id, now(), 200, decode(repeat('00', 32), 'hex'), convert_to('{}', 'UTF8')
    ) RETURNING id INTO payload_id;

    INSERT INTO corner.odds_observations (
        provider_payload_id, provider_id, outcome_id, sportsbook_id, quote_state_id,
        source_record_key, decimal_odds, observed_at
    ) VALUES (
        payload_id, provider_a_id, outcome_id, sportsbook_id, quote_state_id,
        'event[verify]/book[verify]/market[h2h]/outcome[0]', 2.000000, now()
    ) RETURNING id INTO observation_id;

    BEGIN
        UPDATE corner.provider_payloads SET content_type = 'application/json' WHERE id = payload_id;
        RAISE EXCEPTION 'mutable provider payload was accepted';
    EXCEPTION WHEN OTHERS THEN
        IF SQLSTATE <> 'P0001' THEN
            RAISE;
        END IF;
    END;

    BEGIN
        UPDATE corner.odds_observations SET decimal_odds = 2.100000 WHERE id = observation_id;
        RAISE EXCEPTION 'mutable observation was accepted';
    EXCEPTION WHEN OTHERS THEN
        IF SQLSTATE <> 'P0001' THEN
            RAISE;
        END IF;
    END;

    BEGIN
        INSERT INTO corner.odds_observations (
            provider_payload_id, provider_id, outcome_id, sportsbook_id, quote_state_id,
            source_record_key, decimal_odds, observed_at
        ) VALUES (
            payload_id, provider_b_id, outcome_id, sportsbook_id, quote_state_id,
            'event[verify]/book[verify]/market[h2h]/outcome[1]', 2.000000, now()
        );
        RAISE EXCEPTION 'observation provider mismatch was accepted';
    EXCEPTION WHEN foreign_key_violation THEN
        NULL;
    END;
END;
$$;

ROLLBACK;
