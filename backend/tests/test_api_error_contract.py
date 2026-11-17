"""V41-17.03 Batch 3.1: the OpenAPI error documentation describes the errors the API ACTUALLY returns.

Every operation is driven with failure scenarios (tests/api_error_probes.py); each observed error response is validated against the documented schema with the independent
validator from test_api_response_schemas, and the per-operation status table (app.api.v1.error_contracts.ERROR_STATUSES) is checked in both directions: every declared
status was produced by some scenario, and no produced status is undeclared. Runtime behaviour is not changed by the documentation (the success baseline comparison and the
standardized-error tests in test_api_contract still pass untouched). Test names are not test_pN_* so they are reported as supplementary evidence."""
import json
import re

import pytest
from api_error_probes import PUBLIC, inject_failures, probe_all
from app.api.v1.error_contracts import ERROR_STATUSES, RETRY_AFTER, STATUS_TEXT
from test_api_contract import operations, spec_of, strict_client, world  # noqa: F401  (fixtures)
from test_api_response_schemas import validate

SECRET_MARKERS = ("Traceback", 'File "', "sqlalchemy", "psycopg", "/etc/passwd", "secret internal detail", "password_hash", "SELECT ", "postgresql://")


@pytest.fixture()
def observed(client, strict_client, world, owner_engine, app_db, settings, monkeypatch, ticketing):  # noqa: F811
    probes, spec, ops, *_ = probe_all(client, strict_client, world, owner_engine, app_db, settings, monkeypatch, ticketing)
    injected, injected_bodies = inject_failures(strict_client, ops, world, monkeypatch, app_db)
    obs = {k: {s: list(v) for s, v in d.items()} for k, d in probes.obs.items()}
    for k, d in injected.items():
        for s, v in d.items():
            obs.setdefault(k, {}).setdefault(s, []).extend(v)
    return {"spec": spec, "obs": obs, "bodies": probes.bodies + injected_bodies}


def test_openapi_documents_the_standardized_error_envelope_not_the_framework_default(client):
    spec = spec_of(client)
    schemas = spec["components"]["schemas"]
    assert {"ErrorResponse", "ErrorInfo", "ErrorDetail"} <= set(schemas)
    assert "HTTPValidationError" not in schemas and "ValidationError" not in schemas
    assert "HTTPValidationError" not in json.dumps(spec)
    for name, required in (("ErrorResponse", {"error"}), ("ErrorInfo", {"code", "message", "correlation_id"}), ("ErrorDetail", {"loc", "msg"})):
        assert set(schemas[name]["required"]) == required and schemas[name]["additionalProperties"] is False
    assert "details" in schemas["ErrorInfo"]["properties"] and "details" not in schemas["ErrorInfo"]["required"]
    size = {"$ref": "#/components/schemas/SizeLimitErrorResponse"}
    assert schemas["SizeLimitErrorResponse"]["additionalProperties"] is False and set(schemas["SizeLimitErrorInfo"]["required"]) == {"code", "message"}
    for method, path, op in operations(spec):
        for code, resp in op["responses"].items():
            if code.startswith(("4", "5")):
                full = {"$ref": "#/components/schemas/ErrorResponse"}
                expected = full if code != "413" else ({"anyOf": [size, full]} if path == "/api/v1/documents" else size)
                assert resp["content"]["application/json"]["schema"] == expected, (method, path, code)
                assert "X-Correlation-ID" in resp["headers"]
                assert ("Retry-After" in resp["headers"]) == (int(code) in RETRY_AFTER), (method, path, code)
                assert resp["description"] == STATUS_TEXT[int(code)]


def test_the_declared_statuses_are_exactly_the_table_and_cover_every_operation(client):
    spec = spec_of(client)
    documented = {(m, p): tuple(sorted(int(c) for c in op["responses"] if c.startswith(("4", "5")))) for m, p, op in operations(spec)}
    assert documented == {k: tuple(sorted(v)) for k, v in ERROR_STATUSES.items()}
    assert len(documented) == 56  # 55 since Batch 11B (webhook endpoints: create, list, update; the signed receiver); 45 until Batch 8 (DELETE /documents/{id}), 50 since Batch 9 (reprocess, job list, job detail, job retry), 51 since Batch 11A (connector sync)
    for key, statuses in documented.items():
        assert statuses and set(statuses) <= set(STATUS_TEXT), key


def test_every_observed_error_response_conforms_to_the_documented_schema_and_headers(observed):
    spec = observed["spec"]
    failures, seen = [], 0
    for op, scenario, status, body, headers in observed["bodies"]:
        seen += 1
        parsed = json.loads(body)
        method, path = op.split(" ", 1)
        declared = spec["paths"][path][method.lower()]["responses"].get(str(status))
        if declared is None:
            failures.append(f"{op} {scenario}: status {status} is not documented")
            continue
        problems = validate(parsed, declared["content"]["application/json"]["schema"], spec)
        if problems:
            failures.append(f"{op} {scenario} {status}: {problems[:2]}")
        err = parsed.get("error") if isinstance(parsed, dict) else None
        if not isinstance(err, dict):
            continue  # reported by the schema validation above
        if not headers.get("x-correlation-id"):
            failures.append(f"{op} {scenario} {status}: no X-Correlation-ID header")
        if "correlation_id" in err and headers.get("x-correlation-id") != err["correlation_id"]:
            failures.append(f"{op} {scenario} {status}: correlation header {headers.get('x-correlation-id')} != body {err['correlation_id']}")
        if status in RETRY_AFTER and not headers.get("retry-after", "").isdigit():
            failures.append(f"{op} {scenario} {status}: missing or non-integer Retry-After")
        if status not in RETRY_AFTER and "retry-after" in headers:
            failures.append(f"{op} {scenario} {status}: undocumented Retry-After header")
        if err.get("code") == "payload_too_large" and "correlation_id" in err:
            failures.append(f"{op} {scenario} {status}: the size-limit body unexpectedly carries a correlation_id (update the documented model)")
        if (status == 422 and err["code"] == "validation_error") != ("details" in err):
            failures.append(f"{op} {scenario} {status}: details present iff validation_error")
        if any(marker in body for marker in SECRET_MARKERS):
            failures.append(f"{op} {scenario} {status}: internal detail in body")
    assert seen > 300, seen
    assert failures == [], failures[:8]


def test_declared_and_emitted_error_statuses_agree_in_both_directions(observed):
    declared = {f"{m.upper()} {p}": set(v) for (m, p), v in ERROR_STATUSES.items()}
    emitted = {op: {int(s) for s in d} for op, d in observed["obs"].items()}
    assert set(emitted) == set(declared)
    undeclared = {op: sorted(emitted[op] - declared[op]) for op in declared if emitted[op] - declared[op]}
    never_emitted = {op: sorted(declared[op] - emitted[op]) for op in declared if declared[op] - emitted[op]}
    assert undeclared == {}, f"emitted but not documented: {undeclared}"
    assert never_emitted == {}, f"documented but never emitted by any probe: {never_emitted}"


def test_every_observed_error_code_is_named_in_the_status_description(observed):
    unnamed = set()
    for _op, _scenario, status, body, _headers in observed["bodies"]:
        code = json.loads(body)["error"]["code"]
        if not re.search(rf"\b{re.escape(code)}\b", STATUS_TEXT[status]):
            unnamed.add((status, code))
    assert unnamed == set(), unnamed


def test_statuses_that_an_operation_cannot_produce_are_not_declared(client):
    spec = spec_of(client)
    for method, path, op in operations(spec):
        codes = {int(c) for c in op["responses"] if c.startswith(("4", "5"))}
        has_input = any(prm["in"] == "query" for prm in op.get("parameters", [])) or "requestBody" in op
        has_body = "requestBody" in op
        public = (method, path) in PUBLIC
        assert (401 in codes) == (not public or path == "/api/v1/auth/login"), (method, path)
        assert (422 in codes) == has_input, (method, path)            # nothing to validate, nothing to reject
        assert (413 in codes) == has_body, (method, path)             # only requests with a body can exceed the size limit
        if "{" not in path and method == "get":
            assert 409 not in codes and 415 not in codes, (method, path)
        assert {500, 503} <= codes, (method, path)                      # every operation reads the database


def test_status_counts_and_the_creating_operations_are_exactly_as_documented(client):
    spec = spec_of(client)
    ok = {}
    for method, path, op in operations(spec):
        success = tuple(sorted(c for c in op["responses"] if c.startswith("2")))
        assert len(success) == 1, (method, path)
        ok.setdefault(success[0], []).append(f"{method.upper()} {path}")
    assert {k: len(v) for k, v in ok.items()} == {"200": 45, "201": 7, "202": 4}  # Batch 11B: endpoint list and update (200), endpoint creation (201), the signed receiver (202); Batch 11A: the connector sync (202). Batch 8: DELETE document (200); Batch 9: two job reads (200) and two accepted asynchronous operations (202)
    assert sorted(ok["201"]) == sorted(["POST /api/v1/tenants", "POST /api/v1/tenants/{tenant_id}/members", "POST /api/v1/connectors", "POST /api/v1/documents",
                                        "POST /api/v1/incidents/extract", "POST /api/v1/tickets", "POST /api/v1/webhook-endpoints"])
