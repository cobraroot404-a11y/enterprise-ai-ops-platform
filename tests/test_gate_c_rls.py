import json

import gate_c_rls as rls
import pytest


@pytest.fixture
def catalog():
    return {
        "relations": [
            {"name": name, "owner": rls.OWNER, "rls": True, "forced": name in rls.EXPECTED_FORCE_RLS}
            for name in sorted(rls.EXPECTED_RLS)
        ],
        "roles": [
            dict.fromkeys(("superuser", "bypassrls", "createrole", "createdb", "replication"), False) | {"name": role}
            for role in sorted(rls.ROLES)
        ],
        "memberships": [],
        "grants": [
            {"relation": table, "role": role, "privilege": privilege, "column": column}
            for table, role, privilege, column in rls.expected_grants()
        ],
        "policies": [
            {"tablename": table, "policyname": name, "roles": [role], "cmd": verb,
             "permissive": "PERMISSIVE",
             "qual": "true" if name == "worker_access" else "(tenant_id = app_current_tenant())",
             "with_check": (
                 None if name == "worker_tenant_scoped" and table.startswith("webhook_")
                 else "true" if name == "worker_access" else "(tenant_id = app_current_tenant())"
             )}
            for table, name, role, verb in rls.expected_policies()
        ],
        "webhook_lookup": [{
            "owner": rls.OWNER, "definer": True, "arguments": "uuid", "configuration": ["search_path=public, pg_temp"],
            "app_execute": True, "worker_execute": False, "public_execute": False,
        }],
    }


def test_owner_approved_catalog_passes(catalog):
    result = rls.evaluate_catalog(json.dumps(catalog), 0)
    assert result["result"] == "PASS"
    assert len(result["actual_rls"]) == 19
    assert len(result["actual_force_rls"]) == 16
    assert result["actual_exceptions"] == ["tenants", "users", "webhook_endpoints"]
    assert len(catalog["policies"]) == 39


@pytest.mark.parametrize(("name", "flag", "value", "expected_error"), [
    ("documents", "forced", False, "FORCE RLS: missing ['documents']"),
    ("users", "forced", True, "FORCE RLS: missing [], unexpected ['users']"),
    ("users", "rls", False, "RLS: missing ['users']"),
    ("new_table", "rls", True, "RLS: missing [], unexpected ['new_table']"),
])
def test_relation_set_drift_fails(catalog, name, flag, value, expected_error):
    row = next((row for row in catalog["relations"] if row["name"] == name), None)
    if row is None:
        row = {"name": name, "owner": rls.OWNER, "rls": False, "forced": False}
        catalog["relations"].append(row)
    row[flag] = value
    result = rls.evaluate_catalog(json.dumps(catalog), 0)
    assert result["disposition"] == "SECURITY_MISMATCH"
    assert any(error.startswith(expected_error) for error in result["errors"])


def test_wrong_exception_manifest_fails_independently(catalog):
    result = rls.evaluate_catalog(json.dumps(catalog), 0, expected_exceptions={"users", "tenants"})
    assert result["disposition"] == "SECURITY_MISMATCH"
    assert result["errors"] == ["non-forced exceptions: missing [], unexpected ['webhook_endpoints']"]


@pytest.mark.parametrize("privilege", ["superuser", "bypassrls"])
def test_runtime_role_flags_fail_closed(catalog, privilege):
    catalog["roles"][1][privilege] = True
    assert rls.evaluate_catalog(json.dumps(catalog), 0)["disposition"] == "SECURITY_MISMATCH"


def test_ownership_membership_grant_policy_and_lookup_changes_fail(catalog):
    catalog["relations"][0]["owner"] = "eaop_app"
    catalog["memberships"].append({"member": 10, "roleid": 20})
    catalog["grants"].append({"relation": "users", "role": "eaop_app", "privilege": "UPDATE", "column": None})
    catalog["policies"].pop()
    catalog["webhook_lookup"][0]["worker_execute"] = True
    result = rls.evaluate_catalog(json.dumps(catalog), 0)
    assert result["disposition"] == "SECURITY_MISMATCH"
    assert len(result["errors"]) == 5


def test_webhook_policy_requires_tenant_predicate(catalog):
    for policy in catalog["policies"]:
        if policy["tablename"] == "webhook_endpoints":
            policy["qual"] = "true"
    assert rls.evaluate_catalog(json.dumps(catalog), 0)["disposition"] == "SECURITY_MISMATCH"


@pytest.mark.parametrize("stdout", ["", "{invalid", "[]", '{"relations":[{"name":"users"}]}'])
def test_malformed_database_evidence_fails_closed(stdout):
    assert rls.evaluate_catalog(stdout, 0) == {"result": "FAIL", "disposition": "PARSE_ERROR"}


def test_command_failure_is_distinct_from_parse_error():
    assert rls.evaluate_catalog("", 2) == {"result": "FAIL", "disposition": "COMMAND_FAILED"}
