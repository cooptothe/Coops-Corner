-- Canonical competitions may be tours: ATP/WTA have rotating tournament keys.
-- Keep provider/external_id unique: a provider key can never map to two competitions.
-- Preserve every identity, event, participant, observation and retained payload.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
CREATE INDEX IF NOT EXISTS competition_provider_current_lookup_idx
ON corner.competition_provider_identities (provider_id, competition_id)
WHERE active;
DROP INDEX IF EXISTS corner.competition_provider_current_identity_key;
COMMENT ON TABLE corner.competition_provider_identities IS
'Provider competition keys map uniquely to canonical competitions; multiple keys may identify one canonical tour or league. Exact active provider-key validation remains required.';
COMMIT;
