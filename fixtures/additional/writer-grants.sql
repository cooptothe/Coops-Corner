GRANT SELECT, INSERT ON
  corner.providers, corner.sports, corner.competitions,
  corner.participants, corner.sportsbooks, corner.events,
  corner.event_participants, corner.markets, corner.outcomes,
  corner.event_provider_identities, corner.competition_provider_identities,
  corner.sportsbook_provider_identities, corner.provider_market_mappings,
  corner.provider_participant_aliases, corner.ingestion_batches,
  corner.provider_payloads, corner.odds_observations, corner.market_types,
  corner.scopes, corner.participant_types, corner.sportsbook_categories,
  corner.event_statuses, corner.quote_states, corner.outcome_sides,
  corner.quote_links
TO {writer};

GRANT UPDATE ON corner.ingestion_batches TO {writer};
GRANT UPDATE(display_name) ON
  corner.providers, corner.sports, corner.competitions, corner.sportsbooks,
  corner.market_types, corner.scopes, corner.participant_types,
  corner.sportsbook_categories, corner.event_statuses,
  corner.quote_states, corner.outcome_sides
TO {writer};
GRANT UPDATE(market_type_id,default_scope_id,requires_point)
  ON corner.provider_market_mappings TO {writer};
GRANT UPDATE(role) ON corner.event_participants TO {writer};
GRANT UPDATE(updated_at) ON corner.markets,corner.outcomes TO {writer};
GRANT UPDATE(competition_id,scheduled_start,event_status_id)
  ON corner.events TO {writer};
GRANT UPDATE(participant_id) ON corner.provider_participant_aliases TO {writer};
GRANT UPDATE(event_url,market_url,outcome_url,captured_at)
  ON corner.quote_links TO {writer};
