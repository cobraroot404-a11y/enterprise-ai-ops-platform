"""V41-17.03 Batch 3: the OpenAPI success schemas are accurate, meaningful and enforced by runtime evidence.

* every success response (all 45 operations, including both 201 creations) declares a schema that resolves to a real object schema with properties (a bare `$ref` or an empty
  schema is not accepted);
* every captured runtime response is validated against that schema by an independent validator (types, required keys, nullable unions, nesting, arrays, enums, uuid/date-time
  formats, and strict detection of undeclared keys), and the validator itself is tested for detection power;
* free-form JSON is limited to a documented set; no response exposes credential fields; status codes and content types match what is documented."""
import json
import re

from test_api_response_contract import ISO_RE, UUID_RE, capture_all, recorder  # noqa: F401  (recorder is a fixture)

FORBIDDEN_KEYS = {"password", "password_hash", "secret", "secret_ref", "api_key", "jwt_secret", "private_key", "refresh_token"}


def _resolve(schema, spec):
    while "$ref" in schema:
        schema = spec["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
    return schema


def validate(value, schema, spec, path="$"):
    schema = _resolve(schema, spec)
    for key in ("anyOf", "oneOf"):
        if key in schema:
            attempts = [validate(value, sub, spec, path) for sub in schema[key]]
            return [] if any(not a for a in attempts) else [f"{path}: matches none of the {key} alternatives: {attempts[0][:2]} ..."]
    if "allOf" in schema:
        return [v for sub in schema["allOf"] for v in validate(value, sub, spec, path)]
    out = []
    typ = schema.get("type")
    if "enum" in schema and value not in schema["enum"]:
        return [f"{path}: {value!r} not in enum {schema['enum']}"]
    if "const" in schema and value != schema["const"]:
        return [f"{path}: {value!r} != const {schema['const']!r}"]
    if typ == "null":
        return [] if value is None else [f"{path}: expected null"]
    if typ == "string":
        if not isinstance(value, str):
            return [f"{path}: expected string, got {type(value).__name__}"]
        fmt = schema.get("format")
        if fmt == "uuid" and not UUID_RE.match(value):
            out.append(f"{path}: not a uuid")
        if fmt == "date-time" and not ISO_RE.match(value):
            out.append(f"{path}: not an ISO date-time")
        return out
    if typ == "integer":
        return [] if isinstance(value, int) and not isinstance(value, bool) else [f"{path}: expected integer, got {type(value).__name__}"]
    if typ == "number":
        return [] if isinstance(value, (int, float)) and not isinstance(value, bool) else [f"{path}: expected number, got {type(value).__name__}"]
    if typ == "boolean":
        return [] if isinstance(value, bool) else [f"{path}: expected boolean, got {type(value).__name__}"]
    if typ == "array":
        if not isinstance(value, list):
            return [f"{path}: expected array, got {type(value).__name__}"]
        for i, item in enumerate(value):
            out += validate(item, schema.get("items", {}), spec, f"{path}[{i}]")
        return out
    if typ == "object" or "properties" in schema:
        if not isinstance(value, dict):
            return [f"{path}: expected object, got {type(value).__name__}"]
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in value:
                out.append(f"{path}: missing required key {req!r}")
        extra = schema.get("additionalProperties")
        for k, v in value.items():
            if k in props:
                out += validate(v, props[k], spec, f"{path}.{k}")
            elif extra is True or extra == {}:
                continue
            elif isinstance(extra, dict):
                out += validate(v, extra, spec, f"{path}.{k}")
            else:
                out.append(f"{path}: undeclared key {k!r} (not in the documented schema)")
        return out
    return out


def _split_key(key):
    method, rest = key.split(" ", 1)
    return method.lower(), rest.split(" [")[0]


def _spec(client):
    return client.get("/openapi.json").json()


def _request_model_names(spec):
    """Component schemas used as request bodies (and everything they reference): excluded from response-side checks."""
    names = set()

    def walk(ref):
        n = ref.rsplit("/", 1)[-1]
        if n in names:
            return
        names.add(n)
        for r in re.findall(r'#/components/schemas/([^"]+)', json.dumps(spec["components"]["schemas"][n])):
            walk(r)
    for ops in spec["paths"].values():
        for method, op in ops.items():
            if method in ("get", "post", "put", "patch", "delete"):
                for media in op.get("requestBody", {}).get("content", {}).values():
                    if "$ref" in media["schema"]:
                        walk(media["schema"]["$ref"])
    return names


def _has_properties(schema, spec, seen=()):
    schema = _resolve(schema, spec)
    for key in ("anyOf", "oneOf"):
        if key in schema:
            return all(_has_properties(sub, spec) for sub in schema[key])
    return bool(schema.get("properties"))


def test_p1_every_success_response_declares_a_meaningful_typed_object_schema(client):
    """Converted from the Batch 2 strict expected failure V41-17.03-TYPED-RESPONSES only after the schemas existed and were validated against runtime responses."""
    spec = _spec(client)
    problems, count = [], 0
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            ok = [c for c in op["responses"] if c.startswith("2")]
            if not ok:
                problems.append(f"{method.upper()} {path}: no success response")
            for code in ok:
                count += 1
                sch = op["responses"][code].get("content", {}).get("application/json", {}).get("schema")
                if not sch or not _has_properties(sch, spec):
                    problems.append(f"{method.upper()} {path} [{code}]: no meaningful typed object schema")
    assert problems == [] and count == 56  # 55 since Batch 11B; 45 until Batch 8, 46 after it, 50 since Batch 9, 51 since Batch 11A


def test_p1_created_operations_document_201_and_others_200(client):
    spec = _spec(client)
    created = {("post", "/api/v1/connectors"), ("post", "/api/v1/documents"), ("post", "/api/v1/incidents/extract"), ("post", "/api/v1/tenants"),
               ("post", "/api/v1/tenants/{tenant_id}/members"), ("post", "/api/v1/tickets"), ("post", "/api/v1/webhook-endpoints")}
    accepted = {("post", "/api/v1/documents/{document_id}/reprocess"), ("post", "/api/v1/ingestion/jobs/{job_id}/retry"),
                ("post", "/api/v1/connectors/{connector_id}/sync"),
                ("post", "/api/v1/webhooks/{endpoint_id}")}  # Batch 9 and 11A: asynchronous, 202 Accepted
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            if method in ("get", "post", "put", "patch", "delete"):
                expect = "201" if (method, path) in created else "202" if (method, path) in accepted else "200"
                assert expect in op["responses"] and not ({"200", "201", "202"} - {expect}) & set(op["responses"]), (method, path, list(op["responses"]))


def test_p1_free_form_json_is_limited_to_the_documented_exceptions(client):
    from app.api.v1.response_models import FREE_FORM_EXCEPTIONS
    spec = _spec(client)
    found = set()
    requests = _request_model_names(spec)
    for name, sch in spec["components"]["schemas"].items():
        if name in requests:
            continue
        for prop, ps in sch.get("properties", {}).items():
            ps = _resolve(ps, spec)
            for sub in [ps] + [_resolve(x, spec) for x in ps.get("anyOf", [])]:
                if sub.get("type") == "object" and not sub.get("properties") and sub.get("additionalProperties") in (True, {}):
                    found.add(f"{name}.{prop}")
    assert found == FREE_FORM_EXCEPTIONS, (sorted(found - FREE_FORM_EXCEPTIONS), sorted(FREE_FORM_EXCEPTIONS - found))


def test_every_runtime_response_conforms_to_its_declared_openapi_schema(client, recorder):  # noqa: F811
    spec = _spec(client)
    violations, checked = {}, 0
    for key, rec in recorder.ops.items():
        method, path = _split_key(key)
        resp = spec["paths"][path][method]["responses"][str(rec["status"])]
        schema = resp["content"][rec["content_type"]]["schema"]
        found = validate(rec["body"], schema, spec)
        checked += 1
        if found:
            violations[key] = found[:4]
    assert violations == {} and checked >= 50, violations


def test_the_validator_detects_violations_so_the_conformance_test_is_meaningful(client):
    spec = _spec(client)
    schema = spec["paths"]["/api/v1/health"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    good = {"status": "ok", "llm_backend": "x", "embedding_backend": "y"}
    assert validate(good, schema, spec) == []
    assert any("undeclared key" in v for v in validate({**good, "leak": 1}, schema, spec))
    assert any("missing required" in v for v in validate({"status": "ok"}, schema, spec))
    assert any("expected string" in v for v in validate({**good, "llm_backend": 1}, schema, spec))
    assert any("enum" in v or "const" in v for v in validate({**good, "status": "down"}, schema, spec))
    inc = spec["paths"]["/api/v1/incidents"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert any("expected integer" in v for v in validate({"total": "3", "limit": 50, "offset": 0, "items": []}, inc, spec))
    assert any("not a uuid" in v or "missing" in v for v in validate({"total": 1, "limit": 50, "offset": 0, "items": [{"id": "x"}]}, inc, spec))


def _keys(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from _keys(v)
    elif isinstance(value, list):
        for v in value:
            yield from _keys(v)


def test_no_response_exposes_secret_or_credential_fields(recorder):  # noqa: F811
    exposed = {key: sorted(set(_keys(rec["body"])) & FORBIDDEN_KEYS) for key, rec in recorder.ops.items() if set(_keys(rec["body"])) & FORBIDDEN_KEYS}
    assert exposed == {}, exposed


def test_response_models_do_not_declare_credential_fields(client):
    spec = _spec(client)
    requests = _request_model_names(spec)  # request bodies legitimately carry a password or a secret reference
    declared = {f"{n}.{p}" for n, s in spec["components"]["schemas"].items() if n not in requests for p in s.get("properties", {}) if p in FORBIDDEN_KEYS}
    assert declared == set(), declared


def test_error_responses_are_unchanged_by_response_models(client):
    r = client.get("/api/v1/incidents")
    assert r.status_code == 401 and set(r.json()) == {"error"} and {"code", "message", "correlation_id"} <= set(r.json()["error"])
    assert client.get("/api/v1/nope").json()["error"]["code"] == "not_found"
    assert re.match(r"^[\w-]+$", client.get("/api/v1/health").headers["X-Correlation-ID"])


def _success_schema_names(spec):
    names = set()

    def walk(ref):
        n = ref.rsplit("/", 1)[-1]
        if n in names:
            return
        names.add(n)
        for r in re.findall(r'#/components/schemas/([^"]+)', json.dumps(spec["components"]["schemas"][n])):
            walk(r)
    for ops in spec["paths"].values():
        for method, op in ops.items():
            if method in ("get", "post", "put", "patch", "delete"):
                for code, resp in op["responses"].items():
                    if code.startswith("2"):
                        for r in re.findall(r'#/components/schemas/([^"]+)', json.dumps(resp)):
                            walk(r)
    return names


def test_published_schemas_are_closed_except_for_the_documented_open_models(client):
    from app.api.v1.response_models import EXTERNAL_MODELS, OPEN_MODELS
    spec = _spec(client)
    objects = {n: spec["components"]["schemas"][n] for n in _success_schema_names(spec) if spec["components"]["schemas"][n].get("properties") and n not in EXTERNAL_MODELS}
    open_found = {n for n, sch in objects.items() if sch.get("additionalProperties") is True}
    not_declared = {n for n, sch in objects.items() if "additionalProperties" not in sch}
    assert open_found == OPEN_MODELS and not_declared == set(), (sorted(open_found ^ OPEN_MODELS), sorted(not_declared))


def test_extra_keys_pass_through_at_runtime_but_are_flagged_against_the_closed_schema(client):
    """A handler that adds a field is never silently stripped from the response, and the conformance validator reports it as undeclared."""
    from app.api.v1.response_models import HealthResponse
    out = HealthResponse.model_validate({"status": "ok", "llm_backend": "x", "embedding_backend": "y", "added_later": 1}).model_dump(exclude_unset=True)
    assert out["added_later"] == 1
    spec = _spec(client)
    schema = spec["paths"]["/api/v1/health"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert any("undeclared key 'added_later'" in v for v in validate(out, schema, spec))
