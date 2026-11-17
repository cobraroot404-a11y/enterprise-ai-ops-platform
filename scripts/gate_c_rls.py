"""Owner-approved Gate C PostgreSQL catalog checks."""

import json
import re

EXCEPTIONS = frozenset({"users", "tenants", "webhook_endpoints"})
ROLES = frozenset({"eaop_app", "eaop_worker"})
OWNER = "gate_c_owner"
PRIVILEGES = {
    "S": "SELECT", "I": "INSERT", "U": "UPDATE", "D": "DELETE",
    "T": "TRUNCATE", "R": "REFERENCES", "G": "TRIGGER",
}

# Table privileges for app and worker, then the worker policy where present.
# Column grants are separate. See docs/security/identity-tables.md.
ACCESS = {
    "approvals": ("SIUD", "S", "worker_access"),
    "audit_events": ("SI", "SI", "worker_access"),
    "connector_sync_records": ("S", "SIU", "worker_tenant_scoped"),
    "connectors": ("SIUD", "S", "worker_access"),
    "document_chunks": ("SIUD", "SID", "worker_tenant_scoped"),
    "document_sources": ("SID", "SID", "worker_tenant_scoped"),
    "document_versions": ("SIUD", "SID", "worker_tenant_scoped"),
    "documents": ("SIUD", "SI", "worker_tenant_scoped"),
    "embedding_profiles": ("SIU", "SI", "worker_tenant_scoped"),
    "incidents": ("SIUD", "S", "worker_access"),
    "ingestion_jobs": ("SIU", "SU", "worker_access"),
    "memberships": ("SIUD", "", None),
    "outbox_events": ("SIUD", "SU", "worker_access"),
    "tenant_profiles": ("SIU", "", None),
    "tenants": ("S", "", None),
    "tickets": ("SIUD", "SU", "worker_access"),
    "users": ("S", "", None),
    "webhook_deliveries": ("SI", "S", "worker_tenant_scoped"),
    "webhook_endpoints": ("SI", "S", "worker_tenant_scoped"),
}
EXPECTED_RLS = frozenset(ACCESS)
EXPECTED_FORCE_RLS = EXPECTED_RLS - EXCEPTIONS
COLUMN_UPDATES = {
    ("connector_sync_records", "eaop_app"): "status",
    ("document_chunks", "eaop_worker"): "is_current",
    ("document_sources", "eaop_app"): "document_id version",
    ("document_sources", "eaop_worker"): "document_id version",
    ("document_versions", "eaop_worker"): "active_generation processing_job_id embedding_backend chunk_count source_id",
    ("documents", "eaop_worker"): "cleanup_state cleanup_completed_at current_version kind",
    ("incidents", "eaop_worker"): "citations related_incidents",
    ("webhook_endpoints", "eaop_app"): "secret_ref previous_secret_ref status updated_at",
}

CATALOG_SQL = """
WITH runtime AS (
    SELECT oid, rolname AS name, rolsuper AS superuser, rolbypassrls AS bypassrls,
           rolcreaterole AS createrole, rolcreatedb AS createdb, rolreplication AS replication
    FROM pg_roles WHERE rolname IN ('eaop_app', 'eaop_worker')
), relations AS (
    SELECT c.oid, c.relname AS name, c.relrowsecurity AS rls, c.relforcerowsecurity AS forced,
           pg_get_userbyid(c.relowner) AS owner, c.relacl AS acl
    FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p')
), privileges AS (
    SELECT t.name AS relation, r.name AS role, p.privilege, NULL::name AS column
    FROM relations t CROSS JOIN runtime r
    CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER']) p(privilege)
    WHERE (t.rls OR t.forced) AND has_table_privilege(r.oid, t.oid, p.privilege)
    UNION ALL
    SELECT t.name, r.name, p.privilege, a.attname
    FROM relations t JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum > 0 AND NOT a.attisdropped
    CROSS JOIN runtime r CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','REFERENCES']) p(privilege)
    WHERE (t.rls OR t.forced) AND has_column_privilege(r.oid, t.oid, a.attnum, p.privilege)
      AND NOT has_table_privilege(r.oid, t.oid, p.privilege)
)
SELECT json_build_object(
  'relations', (SELECT coalesce(json_agg(t ORDER BY name), '[]') FROM relations t),
  'roles', (SELECT coalesce(json_agg(r ORDER BY name), '[]') FROM runtime r),
  'memberships', (SELECT coalesce(json_agg(m), '[]') FROM pg_auth_members m
                  JOIN runtime r ON m.member = r.oid),
  'grants', (SELECT coalesce(json_agg(p ORDER BY relation, role, privilege, "column"), '[]') FROM privileges p),
  'webhook_lookup', (
    SELECT coalesce(json_agg(json_build_object(
      'owner', pg_get_userbyid(p.proowner), 'definer', p.prosecdef,
      'arguments', oidvectortypes(p.proargtypes), 'configuration', p.proconfig, 'acl', p.proacl,
      'app_execute', has_function_privilege('eaop_app', p.oid, 'EXECUTE'),
      'worker_execute', has_function_privilege('eaop_worker', p.oid, 'EXECUTE'),
      'public_execute', EXISTS (SELECT FROM aclexplode(coalesce(p.proacl, acldefault('f', p.proowner)))
                               WHERE grantee = 0 AND privilege_type = 'EXECUTE')
    )), '[]') FROM pg_proc p
    WHERE p.pronamespace = 'public'::regnamespace AND p.proname = 'webhook_endpoint_lookup'
  ),
  'policies', (SELECT coalesce(json_agg(p ORDER BY tablename, policyname), '[]') FROM pg_policies p
               JOIN relations t ON t.name = p.tablename WHERE p.schemaname = 'public' AND (t.rls OR t.forced))
);
"""


def expected_grants():
    return {
        (table, role, PRIVILEGES[flag], None)
        for table, (app, worker, _) in ACCESS.items()
        for role, flags in (("eaop_app", app), ("eaop_worker", worker))
        for flag in flags
    } | {
        (table, role, "UPDATE", column)
        for (table, role), columns in COLUMN_UPDATES.items()
        for column in columns.split()
    }


def expected_policies():
    policies = {
        (table, "tenant_isolation", "eaop_app", "ALL")
        for table in EXPECTED_RLS - {"memberships", "users", "tenants"}
    }
    policies.update(
        (table, worker, "eaop_worker", "ALL") for table, (_, _, worker) in ACCESS.items() if worker
    )
    policies.update(
        (table, f"{table}_select", "eaop_app", "SELECT") for table in ("users", "tenants")
    )
    policies.update(
        ("memberships", f"membership_{verb.lower()}", "eaop_app", verb)
        for verb in ("SELECT", "INSERT", "UPDATE", "DELETE")
    )
    policies.update(("audit_events", f"platform_audit_{verb.lower()}", "eaop_app", verb) for verb in ("SELECT", "INSERT"))
    return policies


def _unique_rows(rows, key):
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("invalid catalog row collection")
    indexed = {key(row): row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError("duplicate catalog row")
    return indexed


def _scope(expression):
    return re.sub(r"[\s()]", "", expression or "")


def evaluate_catalog(stdout, exit_code, *, expected_exceptions=EXCEPTIONS):
    if exit_code:
        return {"result": "FAIL", "disposition": "COMMAND_FAILED"}
    try:
        payload = json.loads(stdout)
        relations = _unique_rows(payload["relations"], lambda row: row["name"])
        roles = _unique_rows(payload["roles"], lambda row: row["name"])
        grants = _unique_rows(payload["grants"], lambda row: (row["relation"], row["role"], row["privilege"], row["column"]))
        policies = _unique_rows(payload["policies"], lambda row: (row["tablename"], row["policyname"]))
        flags = ("superuser", "bypassrls", "createrole", "createdb", "replication")
        if any(type(row[field]) is not bool for row in relations.values() for field in ("rls", "forced")):
            raise ValueError("invalid relation flags")
        if any(type(row[flag]) is not bool for row in roles.values() for flag in flags):
            raise ValueError("invalid role flags")
        if not isinstance(payload["memberships"], list):
            raise ValueError("invalid memberships")
        lookups = _unique_rows(payload["webhook_lookup"], lambda row: row["arguments"])
        actual_policies = {
            (table, name, tuple(row["roles"]), row["cmd"])
            for (table, name), row in policies.items()
        }
        actual_rls = {table for table, row in relations.items() if row["rls"]}
        actual_force = {table for table, row in relations.items() if row["forced"]}
        actual_exceptions = actual_rls - actual_force
        errors = []
        for label, actual, expected in (
            ("RLS", actual_rls, EXPECTED_RLS), ("FORCE RLS", actual_force, EXPECTED_FORCE_RLS),
            ("non-forced exceptions", actual_exceptions, expected_exceptions),
        ):
            if actual != expected:
                errors.append(f"{label}: missing {sorted(expected - actual)}, unexpected {sorted(actual - expected)}")
        if set(roles) != ROLES or any(row[flag] for row in roles.values() for flag in flags) or payload["memberships"]:
            errors.append("runtime roles are absent, privileged, or have role memberships")
        if any(row["owner"] != OWNER for table, row in relations.items() if table in EXPECTED_RLS):
            errors.append("protected relation ownership differs from the isolated migration owner")
        if grants.keys() != expected_grants():
            errors.append("protected table or column grants differ from the approved baseline")
        lookup = lookups.get("uuid")
        if (set(lookups) != {"uuid"} or lookup["owner"] != OWNER or lookup["definer"] is not True
                or lookup["configuration"] != ["search_path=public, pg_temp"]
                or lookup["app_execute"] is not True or lookup["worker_execute"] is not False
                or lookup["public_execute"] is not False):
            errors.append("webhook lookup ownership, definer scope or execution grants differ")
        expected = {(table, name, (role,), verb) for table, name, role, verb in expected_policies()}
        if actual_policies != expected or any(row["permissive"] != "PERMISSIVE" for row in policies.values()):
            errors.append("protected policy names, roles, commands or modes differ from the approved baseline")
        for (table, name), row in policies.items():
            if name in {"tenant_isolation", "worker_tenant_scoped", "worker_access"}:
                condition = "true" if name == "worker_access" else "tenant_id=app_current_tenant"
                expected_check = "" if name == "worker_tenant_scoped" and table.startswith("webhook_") else condition
                if (_scope(row["qual"]), _scope(row["with_check"])) != (condition, expected_check):
                    errors.append(f"{table}.{name}: policy predicate differs from the baseline")
    except (KeyError, TypeError, ValueError):
        return {"result": "FAIL", "disposition": "PARSE_ERROR"}
    return {
        "result": "FAIL" if errors else "PASS",
        "disposition": "SECURITY_MISMATCH" if errors else "CATALOG_MATCH",
        "expected_rls": sorted(EXPECTED_RLS),
        "actual_rls": sorted(actual_rls),
        "expected_force_rls": sorted(EXPECTED_FORCE_RLS),
        "actual_force_rls": sorted(actual_force),
        "expected_exceptions": sorted(expected_exceptions),
        "actual_exceptions": sorted(actual_exceptions),
        "errors": errors,
    }
