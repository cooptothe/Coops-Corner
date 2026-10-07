"""Explicit DBA provisioning, not runtime authentication or a schema migration.

Creates fresh NOLOGIN group roles only. Refuses existing names rather than adopting
roles with unknown privileges. Caller owns commit. Login membership is a separate
deployment decision; never grant a runtime login the migration owner's role.
"""
import re
from psycopg2 import sql

SUFFIXES = ('reader','ingest','analysis','channel_admin','disposition','recovery','work_producer','worker','work_admin')


def provision(conn, *, prefix='corner'):
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,35}',prefix):
        raise ValueError('safe short lowercase role prefix required')
    roles={suffix:prefix+'_'+suffix for suffix in SUFFIXES}
    with conn.cursor() as cur:
        cur.execute('SELECT rolname FROM pg_roles WHERE rolname=ANY(%s)',(list(roles.values()),))
        if cur.fetchone():
            raise ValueError('role name already exists; refusing to adopt an unknown privilege profile')
        for role in roles.values():
            cur.execute(sql.SQL('CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS').format(sql.Identifier(role)))
        cur.execute(sql.SQL('GRANT USAGE ON SCHEMA corner TO {}').format(sql.Identifier(roles['reader'])))
        # Internal evidence reader, NOT a public/member API role. Future objects
        # require an explicit grant review; no blanket default privileges.
        cur.execute(sql.SQL('GRANT SELECT ON ALL TABLES IN SCHEMA corner TO {}').format(sql.Identifier(roles['reader'])))
        for suffix in SUFFIXES[1:]:
            cur.execute(sql.SQL('GRANT {} TO {}').format(sql.Identifier(roles['reader']),sql.Identifier(roles[suffix])))
        def grant(privilege,tables,role):
            cur.execute(sql.SQL('GRANT '+privilege+' ON '+','.join('corner.'+t for t in tables)+' TO {}').format(sql.Identifier(roles[role])))
        grant('INSERT',('engine_evaluations','engine_evaluation_inputs','qualification_decisions','opportunity_occurrences',
            'actionability_assessments','assessment_stream_evidence','opportunity_conditions','lifecycle_applications','opportunity_transitions'),'analysis')
        grant('INSERT, UPDATE',('condition_processing_projections','opportunities'),'analysis')
        grant('UPDATE (id)',('opportunity_conditions',),'analysis')  # SELECT FOR UPDATE; actual mutation rejected by trigger.
        grant('INSERT',('qualification_channels','qualification_channel_generations','channel_generation_activations'),'channel_admin')
        grant('UPDATE (display_name)',('qualification_channels',),'channel_admin')
        grant('INSERT',('observation_dispositions',),'disposition')
        grant('INSERT',('providers','sports','competitions','participants','sportsbooks','events','event_participants',
            'markets','outcomes','event_provider_identities','sportsbook_provider_identities','provider_market_mappings',
            'provider_participant_aliases','ingestion_batches','provider_payloads','odds_observations',
            'market_types','scopes','participant_types','sportsbook_categories','event_statuses','quote_states','outcome_sides'),'ingest')
        grant('UPDATE',('ingestion_batches',),'ingest')
        grant('UPDATE (display_name)',('providers','sports','competitions','sportsbooks','market_types','scopes',
            'participant_types','sportsbook_categories','event_statuses','quote_states','outcome_sides'),'ingest')
        grant('UPDATE (market_type_id,default_scope_id,requires_point)',('provider_market_mappings',),'ingest')
        grant('UPDATE (role)',('event_participants',),'ingest')
        grant('UPDATE (updated_at)',('markets','outcomes'),'ingest')
        grant('UPDATE (competition_id,scheduled_start,event_status_id)',('events',),'ingest')
        grant('UPDATE (participant_id)',('provider_participant_aliases',),'ingest')
        for suffix in ('recovery','worker'):
            cur.execute(sql.SQL('GRANT {} TO {}').format(sql.Identifier(roles['analysis']),sql.Identifier(roles[suffix])))
        grant('DELETE',('condition_processing_projections','opportunities'),'recovery')
        cur.execute(sql.SQL('GRANT {} TO {}').format(sql.Identifier(roles['work_producer']),sql.Identifier(roles['worker'])))
    return roles


def grant_work_privileges(conn,roles):
    """DBA-only follow-up after 012, using roles just returned by provision()."""
    with conn.cursor() as cur:
        for suffix in SUFFIXES:
            role=roles[suffix]
            cur.execute('SELECT rolsuper,rolcreatedb,rolcreaterole,rolcanlogin,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=%s',(role,))
            if cur.fetchone() != (False,False,False,False,False,False):
                raise ValueError('unexpected role attributes')
        cur.execute(sql.SQL('GRANT SELECT ON corner.work_kinds,corner.work_requests,corner.prepared_work_commands,corner.work_executions TO {}')
                    .format(sql.Identifier(roles['reader'])))
        cur.execute(sql.SQL('GRANT INSERT ON corner.work_requests,corner.work_executions TO {}').format(sql.Identifier(roles['work_producer'])))
        cur.execute(sql.SQL('GRANT INSERT ON corner.prepared_work_commands TO {}').format(sql.Identifier(roles['worker'])))
        for suffix in ('worker','work_admin'):
            cur.execute(sql.SQL('GRANT UPDATE ON corner.work_executions TO {}').format(sql.Identifier(roles[suffix])))
