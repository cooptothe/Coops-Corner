"""Acceptance-stage configuration/readiness. No provisioning or service startup.

The target approval is supplied out of band by the deployment authority, never
learned from the candidate database during startup. This module has no DB_CONFIG
fallback. It deliberately supports only an isolated, local acceptance target.
"""
from dataclasses import dataclass, asdict
from datetime import timedelta
import hashlib
import json
import math
import os
from uuid import uuid4

import psycopg2

from corner import polling, worker, channels, versioned_dispatch


class ReadinessError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ReadinessError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


SERVICES = {'discovery': 'work_producer', 'execution': 'worker', 'health': 'reader'}
INHERITANCE = {'discovery': ('work_producer', 'reader'),
               'execution': ('worker', 'analysis', 'work_producer', 'reader'),
               'health': ('reader',)}


@dataclass(frozen=True)
class Configuration:
    document: str
    service: str | None = None

    @classmethod
    def parse(cls, text, *, service=None):
        require(service is None or service in SERVICES, 'unsupported fixed service')
        def unique(pairs):
            result = {}
            for key, value in pairs:
                require(key not in result, 'duplicate configuration key')
                result[key] = value
            return result
        doc = json.loads(text, object_pairs_hook=unique)
        require(set(doc) == {'format', 'environment', 'production_positive_authorization', 'database',
                'identities', 'authority', 'polling', 'worker', 'work_kinds', 'partitions', 'max_cycles'},
                'missing/unknown configuration fields')
        require(doc['format'] == ('corner.deployment.acceptance/1' if service is None else 'corner.host-service/1'),
                'unsupported configuration format')
        require(doc['environment'] == 'isolated_nonproduction' and doc['production_positive_authorization'] is False,
                'production enablement is unsupported')
        db = doc['database']
        require(set(db) == {'host', 'port', 'dbname'} and db['host'] in ('127.0.0.1', '::1', 'localhost')
                and type(db['port']) is int and 1 <= db['port'] <= 65535
                and isinstance(db['dbname'], str) and bool(db['dbname']), 'explicit local database target required')
        required_services = set(SERVICES) if service is None else {service}
        require(set(doc['identities']) == required_services, 'exact service identities required')
        for value in doc['identities'].values():
            require(set(value) == {'login', 'secret_ref'} and all(isinstance(v, str) and v.strip() for v in value.values()),
                    'login and external secret reference required')
        require(len({v['login'] for v in doc['identities'].values()}) == len(required_services), 'service logins must be distinct')
        if service is not None:
            require(doc['identities'][service]['secret_ref'] == 'Corner/Postgres/' + service.capitalize(),
                    'wrong fixed service credential target')
        require(set(doc['authority']) == {'kind', 'identifier'}, 'explicit authenticated authority required')
        require(set(doc['polling']) == set(asdict(polling.PollSettings())), 'all polling bounds must be explicit')
        settings = polling.PollSettings(**doc['polling'])
        require(set(doc['worker']) == {'lease_seconds', 'retry_seconds', 'max_retries', 'statement_timeout_seconds'},
                'all worker bounds must be explicit')
        w = doc['worker']
        require(all(type(w[k]) in (int, float) and math.isfinite(w[k]) and w[k] > 0 for k in ('lease_seconds', 'retry_seconds', 'statement_timeout_seconds')),
                'positive worker durations required')
        require(w['lease_seconds'] > settings.operation_seconds and w['statement_timeout_seconds'] <= settings.operation_seconds,
                'incompatible operation/lease bounds')
        worker.WorkerSettings('configuration-validation', channels.ChannelAuthority(**doc['authority']),
            timedelta(seconds=w['lease_seconds']), timedelta(seconds=w['retry_seconds']), w['max_retries'],
            timedelta(seconds=w['statement_timeout_seconds']))
        kinds = doc['work_kinds']
        require(isinstance(kinds, list) and len(set(kinds)) == len(kinds) and set(kinds) <= set(polling.KINDS),
                'explicit unique work kinds required')
        require(isinstance(doc['partitions'], list), 'explicit discovery partitions required')
        parts = [polling.Partition(**p) for p in doc['partitions']]
        require(len(set(parts)) == len(parts), 'duplicate discovery partition')
        if service in ('discovery', 'health'):
            require(not kinds, 'this service cannot execute work')
        else:
            require(bool(kinds), 'explicit work kinds required')
        if service in ('execution', 'health'):
            require(not parts, 'this service cannot discover work')
        if service == 'discovery':
            require(bool(parts), 'explicit discovery partitions required')
        require(type(doc['max_cycles']) is int and doc['max_cycles'] > 0, 'finite cycle count required')
        return cls(canonical(doc), service)

    @property
    def value(self):
        return json.loads(self.document)


def environment_secret(reference):
    """Acceptance injection only; production secret-store/rotation is not inferred."""
    value = os.environ.get(reference)
    require(isinstance(value, str) and bool(value), 'required service secret unavailable')
    return value


def catalog_digest(cur):
    """Release manifest over actual definitions, not a migration filename marker."""
    queries = (
        """SELECT c.relname,c.relkind,a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,
            pg_get_expr(d.adbin,d.adrelid) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
            LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
            WHERE n.nspname='corner' ORDER BY c.relname,a.attnum""",
        """SELECT c.relname,k.conname,k.convalidated,pg_get_constraintdef(k.oid,true)
            FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='corner' ORDER BY c.relname,k.conname""",
        "SELECT indexname,indexdef FROM pg_indexes WHERE schemaname='corner' ORDER BY indexname",
        """SELECT c.relname,t.tgname,t.tgenabled,pg_get_triggerdef(t.oid,true) FROM pg_trigger t
            JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='corner' AND NOT t.tgisinternal ORDER BY c.relname,t.tgname""",
        "SELECT viewname,definition FROM pg_views WHERE schemaname='corner' ORDER BY viewname",
        """SELECT p.proname,pg_get_function_identity_arguments(p.oid),pg_get_functiondef(p.oid)
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname='corner' ORDER BY p.proname,pg_get_function_identity_arguments(p.oid)""",
    )
    values = []
    for query in queries:
        cur.execute(query)
        values.append(cur.fetchall())
    return digest(values)


def privilege_digest(cur, role):
    """Effective object privileges, including PUBLIC and column-level grants."""
    data = []
    for query in (
        """SELECT n.nspname,c.relname,p,has_table_privilege(%s,c.oid,p),
            has_table_privilege(%s,c.oid,p || ' WITH GRANT OPTION') FROM pg_class c
            JOIN pg_namespace n ON n.oid=c.relnamespace CROSS JOIN
            unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER','MAINTAIN']) p
            WHERE n.nspname NOT LIKE 'pg_%%' AND n.nspname<>'information_schema' AND c.relkind IN ('r','p','v','m','f')
            ORDER BY 1,2,3""",
        """SELECT n.nspname,c.relname,a.attname,p,has_column_privilege(%s,c.oid,a.attnum,p),
            has_column_privilege(%s,c.oid,a.attnum,p || ' WITH GRANT OPTION') FROM pg_class c
            JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_attribute a ON a.attrelid=c.oid
            CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','REFERENCES']) p
            WHERE n.nspname NOT LIKE 'pg_%%' AND n.nspname<>'information_schema' AND a.attnum>0 AND NOT a.attisdropped
            AND c.relkind IN ('r','p','v','m','f') ORDER BY 1,2,3,4""",
        """SELECT nspname,p,has_schema_privilege(%s,oid,p),
            has_schema_privilege(%s,oid,p || ' WITH GRANT OPTION') FROM pg_namespace
            CROSS JOIN unnest(ARRAY['USAGE','CREATE']) p WHERE nspname NOT LIKE 'pg_%%'
            AND nspname<>'information_schema' ORDER BY 1,2""",
        """SELECT p,has_database_privilege(%s,current_database(),p),
            has_database_privilege(%s,current_database(),p || ' WITH GRANT OPTION')
            FROM unnest(ARRAY['CONNECT','CREATE','TEMP']) p ORDER BY p""",
        """SELECT n.nspname,p.proname,pg_get_function_identity_arguments(p.oid),has_function_privilege(%s,p.oid,'EXECUTE'),
            has_function_privilege(%s,p.oid,'EXECUTE WITH GRANT OPTION')
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname NOT LIKE 'pg_temp_%%' ORDER BY 1,2,3""",
        """SELECT n.nspname,c.relname,p,has_sequence_privilege(%s,c.oid,p),
            has_sequence_privilege(%s,c.oid,p || ' WITH GRANT OPTION') FROM pg_class c
            JOIN pg_namespace n ON n.oid=c.relnamespace CROSS JOIN unnest(ARRAY['USAGE','SELECT','UPDATE']) p
            WHERE c.relkind='S' AND n.nspname NOT LIKE 'pg_%%' ORDER BY 1,2,3""",
    ):
        cur.execute(query, (role, role))
        data.append(cur.fetchall())
    return digest(data)


@dataclass(frozen=True)
class TargetApproval:
    """Trusted out-of-band release/target document, never supplied by work items."""
    document: str

    def validate(self, config):
        # A dataclass can be constructed directly; never trust that callers used
        # parse() before requesting credentials or connecting.
        approved, doc = json.loads(self.document), Configuration.parse(config.document, service=config.service).value
        require(approved['environment'] == 'isolated_nonproduction' and approved['database'] == doc['database'],
                'target not approved as isolated nonproduction')
        logins = approved['logins'] if config.service is None else {config.service: approved['logins'][config.service]}
        require(logins == {k: v['login'] for k, v in doc['identities'].items()}, 'unapproved login identity')
        require(approved['authority'] == doc['authority'], 'unapproved authenticated domain authority')
        require(approved['handlers'] == json.loads(canonical(versioned_dispatch.HANDLERS)), 'unsupported pinned implementation manifest')
        return approved


def connections(config, approval, secret_provider=environment_secret):
    require(config.service is None or secret_provider is not environment_secret, 'host requires an explicit vault provider')
    approval.validate(config)  # Before any credential retrieval or connection.
    doc = config.value
    factories = {}
    for service, identity in doc['identities'].items():
        def connect(*, connect_timeout=5, identity=identity):
            password = secret_provider(identity['secret_ref'])
            require(isinstance(password, str) and bool(password), 'required service secret unavailable')
            try:
                return psycopg2.connect(**doc['database'], user=identity['login'], password=password,
                    connect_timeout=connect_timeout, application_name='corner-deployment-acceptance')
            except psycopg2.Error:
                raise ReadinessError('service connection failed') from None
        factories[service] = connect
    return factories


def check_identity(cur, service, login, approved):
    cur.execute('SELECT session_user,current_user,current_database()')
    require(cur.fetchone() == (login, login, approved['database']['dbname']), 'effective session identity/target mismatch')
    roles = approved['profiles']
    cur.execute("""WITH RECURSIVE ancestry AS (
        SELECT roleid,member,admin_option,inherit_option,set_option FROM pg_auth_members WHERE member=%s::regrole
        UNION SELECT m.roleid,m.member,m.admin_option,m.inherit_option,m.set_option
        FROM pg_auth_members m JOIN ancestry a ON m.member=a.roleid)
        SELECT roleid::regrole::text,member::regrole::text,admin_option,inherit_option,set_option FROM ancestry""", (login,))
    edges = cur.fetchall()
    expected = {roles[x] for x in INHERITANCE[service]}
    require({e[0] for e in edges} == expected and {e[0] for e in edges if e[1] == login} == {roles[SERVICES[service]]}
            and all(not admin and inherit and switch for _, _, admin, inherit, switch in edges), 'unexpected effective role membership')
    cur.execute('''SELECT rolname,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,rolcanlogin,rolinherit
        FROM pg_roles WHERE rolname=ANY(%s)''', (sorted(expected | {login}),))
    require(all(not any(r[1:6]) and r[6] == (r[0] == login) and r[7] for r in cur.fetchall()), 'elevated role attributes')
    cur.execute("""SELECT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname NOT LIKE 'pg_%%' AND n.nspname<>'information_schema' AND pg_has_role(%s,c.relowner,'MEMBER'))
        OR EXISTS(SELECT 1 FROM pg_namespace WHERE nspname NOT LIKE 'pg_%%' AND nspname<>'information_schema'
        AND pg_has_role(%s,nspowner,'MEMBER'))
        OR EXISTS(SELECT 1 FROM pg_database WHERE datname=current_database() AND pg_has_role(%s,datdba,'MEMBER'))""",
        (login, login, login))
    require(not cur.fetchone()[0], 'runtime ownership prohibited')
    require(privilege_digest(cur, login) == approved['privileges'][service], 'unexpected effective privileges')


def readiness(config, approval, factories):
    approved = approval.validate(config)
    require(set(factories) == (set(SERVICES) if config.service is None else {config.service}), 'exact connection identities required')
    for service, connect in factories.items():
        conn = connect(connect_timeout=config.value['polling']['connect_timeout_seconds'])
        try:
            require(not conn.autocommit, 'transactional connection required')
            with conn.cursor() as cur:
                cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                cur.execute("SET LOCAL statement_timeout='5s'")
                cur.execute("SET LOCAL search_path=pg_catalog,public")
                cur.execute('SHOW server_version_num')
                require(180000 <= int(cur.fetchone()[0]) < 190000, 'PostgreSQL 18 required')
                check_identity(cur, service, config.value['identities'][service]['login'], approved)
                require(catalog_digest(cur) == approved['catalog_sha256'], 'schema differs from approved migration contract')
        finally:
            try: conn.rollback()
            finally: conn.close()
    return {'ready': True, 'mode': 'isolated_nonproduction', 'production_positive_authorization': False,
            'configuration_sha256': digest(config.value), 'scope': 'database_and_installed_build_checks'}


def build_poller(config, approval, secret_provider=environment_secret, *, stop=None):
    """No claims until all identities/readiness and initial read-only health pass."""
    require(config.service is None, 'combined runner is acceptance-only')
    from corner.health import read_health
    factories = connections(config, approval, secret_provider)
    readiness(config, approval, factories)
    read_health(factories['health'])
    doc = config.value
    settings = polling.PollSettings(**doc['polling'])
    stop = stop if stop is not None else polling.Stop()
    process_id = str(uuid4())
    w = doc['worker']
    worker_settings = worker.WorkerSettings(process_id, channels.ChannelAuthority(**doc['authority']),
        timedelta(seconds=w['lease_seconds']), timedelta(seconds=w['retry_seconds']), w['max_retries'],
        timedelta(seconds=w['statement_timeout_seconds']))
    backend = polling.DatabaseBackend(discover_connect=factories['discovery'], execute_connect=factories['execution'],
        worker_settings=worker_settings, settings=settings, stop=stop)
    # No implicit evidence source: frozen work remains executable; fresh positive
    # captures cannot borrow a production catalog from configuration.
    poller = polling.Poller(backend, settings=settings, stop=stop, kinds=doc['work_kinds'],
                           partitions=[polling.Partition(**p) for p in doc['partitions']])
    return poller, process_id
