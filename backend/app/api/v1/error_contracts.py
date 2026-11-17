"""Standardized error contract (V41-17.03, Batch 3.1): the OpenAPI description of the error responses the API ACTUALLY emits.

Metadata only. The runtime bodies, status codes and handlers live in app.main and app.core.errors and are unchanged; this module only (1) types the envelope those handlers
already produce and (2) declares, per operation, the error statuses that were observed from that operation (tests/api_error_probes.py exercises every operation with failure
scenarios and tests/test_api_error_contract.py checks the table in both directions: every declared status is emitted by some scenario, every emitted status is declared).
A status an operation cannot produce is not declared (for example, 404 is declared only where a stored resource is looked up). FastAPI's default 422 `HTTPValidationError`
is replaced, because the application answers validation failures with the standardized envelope, not with FastAPI's default body."""
from pydantic import BaseModel, ConfigDict, Field


class ErrorDetail(BaseModel):
    """One validation problem (only on 422 `validation_error`): where it is in the request and what is wrong."""
    model_config = ConfigDict(extra="forbid")
    loc: list[str | int] = Field(description="Location of the problem: source (body, query, path) then field names and list indexes")
    msg: str


class ErrorInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(description="Machine-readable error code (stable; the set is open and grows with new rules)")
    message: str = Field(description="Human-readable explanation; never contains stack traces, SQL or internal paths")
    correlation_id: str = Field(description="Echo of the request's X-Correlation-ID (or a generated one); also returned in the X-Correlation-ID response header")
    details: list[ErrorDetail] | None = Field(default=None, description="Present only for validation errors (422 validation_error)")


class ErrorResponse(BaseModel):
    """The single error envelope returned for every 4xx and 5xx response."""
    model_config = ConfigDict(extra="forbid")
    error: ErrorInfo


class SizeLimitErrorInfo(BaseModel):
    """The 413 body is produced by the body-size middleware before request handling, so it carries no `correlation_id` (the X-Correlation-ID header is still set)."""
    model_config = ConfigDict(extra="forbid")
    code: str
    message: str


class SizeLimitErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    error: SizeLimitErrorInfo


STATUS_TEXT = {
    401: "Authentication failed or is missing: no bearer token, an invalid or expired token, or (login) invalid credentials; for the signed webhook receiver: invalid_signature (unknown or disabled endpoint, missing or wrong signature: deliberately indistinguishable) and timestamp_out_of_window (validly signed but outside the accepted window). Codes: unauthorized, invalid_token, token_expired, invalid_credentials, tenant_required, invalid_signature, timestamp_out_of_window.",
    403: "The caller is authenticated but not permitted. Codes: forbidden, insufficient_role, and rule-specific codes such as invalid_role, self_assignment, self_modification, self_approval, separation_of_duties.",
    404: "The addressed resource does not exist in the caller's tenant (another tenant's resource is reported the same way). Code: not_found.",
    409: "The request conflicts with the current state of the resource (a connector that cannot be synchronised: invalid_connector_config, connector_destination_not_allowed). Codes (webhooks): webhook_replayed (the delivery id was already received for this endpoint), secret_ref_reused. Codes: conflict, duplicate_ticket, not_editable, invalid_transition, not_pending_approval, approval_required, not_retryable, not_reviewable, stale_measurement_state, measurement_not_pending, incident_needs_review, job_not_retryable, source_not_retained, invalid_job_transition.",
    413: "The request body exceeds the size limit. Codes: payload_too_large (raised by the size-limit middleware; the body has no correlation_id, use the header), file_too_large (standard envelope).",
    415: "Unsupported file type (code unsupported_file_type) or, for webhook deliveries, a body that is not application/json (code unsupported_media_type).",
    422: "The request failed validation (code validation_error with `details`) or violated a content rule (code invalid or a rule-specific code such as invalid_payload (webhook delivery that can never be processed), invalid_extraction, empty_document, unparseable_document, connector_destination_not_allowed, invalid_connector_config).",
    429: "Too many requests: sign-in throttling (too_many_attempts), the per-organisation request rate (rate_limited) or the server's concurrency limit (server_busy) or, for a webhook endpoint, its delivery rate limit (webhook_rate_limited). Retry-After gives the seconds to wait.",
    500: "Unexpected server error. Code: internal_error. The body never contains internal detail; use the correlation id to find the log entry.",
    503: "A required dependency is unavailable (database_unavailable, or dependency_unavailable and rule-specific codes such as embedding_unavailable for the embedding model and ingestion_in_progress when the same content is being processed). Retry-After gives the seconds to wait.",
}
RETRY_AFTER = {429, 503}

# (method, path) -> the error statuses the operation emits. Verified in both directions by tests/test_api_error_contract.py.
ERROR_STATUSES: dict[tuple[str, str], tuple[int, ...]] = {
    ("post", "/api/v1/auth/login"): (401, 413, 422, 429, 500, 503),
    ("get", "/api/v1/auth/me"): (401, 500, 503),
    ("post", "/api/v1/tenants"): (401, 403, 409, 413, 422, 500, 503),
    ("get", "/api/v1/tenants/mine"): (401, 500, 503),
    ("get", "/api/v1/tenants/{tenant_id}/members"): (401, 403, 404, 500, 503),
    ("post", "/api/v1/tenants/{tenant_id}/members"): (401, 403, 404, 409, 413, 422, 500, 503),
    ("patch", "/api/v1/tenants/{tenant_id}/members/{user_id}"): (401, 403, 404, 413, 422, 500, 503),
    ("delete", "/api/v1/tenants/{tenant_id}/members/{user_id}"): (401, 403, 404, 500, 503),
    ("get", "/api/v1/platform/audit"): (401, 403, 422, 500, 503),
    ("get", "/api/v1/connectors"): (401, 403, 500, 503),
    ("post", "/api/v1/connectors"): (401, 403, 409, 413, 422, 500, 503),
    ("get", "/api/v1/health"): (500, 503),
    ("post", "/api/v1/documents"): (401, 403, 413, 415, 422, 429, 500, 503),
    ("get", "/api/v1/documents"): (401, 422, 500, 503),
    ("get", "/api/v1/documents/{document_id}"): (401, 404, 500, 503),
    ("delete", "/api/v1/documents/{document_id}"): (401, 403, 404, 500, 503),
    ("post", "/api/v1/documents/{document_id}/reprocess"): (401, 403, 404, 409, 500, 503),
    ("get", "/api/v1/ingestion/jobs"): (401, 422, 500, 503),
    ("get", "/api/v1/ingestion/jobs/{job_id}"): (401, 404, 500, 503),
    ("post", "/api/v1/ingestion/jobs/{job_id}/retry"): (401, 403, 404, 409, 500, 503),
    ("get", "/api/v1/ingestion/status"): (401, 500, 503),
    ("post", "/api/v1/search"): (401, 413, 422, 500, 503),
    ("post", "/api/v1/ai/ask"): (401, 413, 422, 429, 500, 503),
    ("post", "/api/v1/incidents/extract"): (401, 403, 413, 422, 429, 500, 503),
    ("get", "/api/v1/incidents"): (401, 422, 500, 503),
    ("get", "/api/v1/incidents/{incident_id}"): (401, 404, 500, 503),
    ("post", "/api/v1/incidents/{incident_id}/review"): (401, 403, 404, 409, 413, 422, 500, 503),
    ("post", "/api/v1/incidents/{incident_id}/measurements/{name}/verify"): (401, 403, 404, 409, 413, 422, 500, 503),
    ("post", "/api/v1/incidents/{incident_id}/verify-asset"): (401, 403, 404, 409, 500, 503),
    ("post", "/api/v1/tickets"): (401, 403, 404, 409, 413, 422, 500, 503),
    ("get", "/api/v1/tickets"): (401, 422, 500, 503),
    ("get", "/api/v1/tickets/{ticket_id}"): (401, 404, 500, 503),
    ("patch", "/api/v1/tickets/{ticket_id}"): (401, 403, 404, 409, 413, 422, 500, 503),
    ("post", "/api/v1/tickets/{ticket_id}/request-approval"): (401, 403, 404, 409, 500, 503),
    ("post", "/api/v1/tickets/{ticket_id}/cancel"): (401, 403, 404, 409, 500, 503),
    ("post", "/api/v1/tickets/{ticket_id}/submit"): (401, 403, 404, 409, 500, 503),
    ("post", "/api/v1/tickets/{ticket_id}/retry"): (401, 403, 404, 409, 500, 503),
    ("get", "/api/v1/approvals"): (401, 422, 500, 503),
    ("post", "/api/v1/approvals/{ticket_id}/decision"): (401, 403, 404, 409, 413, 422, 500, 503),
    ("get", "/api/v1/workflows"): (401, 422, 500, 503),
    ("get", "/api/v1/audit"): (401, 403, 422, 500, 503),
    ("get", "/api/v1/metrics"): (401, 500, 503),
    ("get", "/api/v1/tenant-profile"): (401, 500, 503),
    ("put", "/api/v1/tenant-profile"): (401, 403, 413, 422, 500, 503),
    ("get", "/api/v1/tickets/{ticket_id}/history"): (401, 404, 500, 503),
    ("get", "/api/v1/incidents/{incident_id}/history"): (401, 404, 500, 503),
    ("get", "/api/v1/connectors/health"): (401, 403, 422, 500, 503),
    ("post", "/api/v1/connectors/{connector_id}/sync"): (401, 403, 404, 409, 500, 503),
    ("post", "/api/v1/webhook-endpoints"): (401, 403, 409, 413, 422, 500, 503),
    ("get", "/api/v1/webhook-endpoints"): (401, 403, 500, 503),
    ("patch", "/api/v1/webhook-endpoints/{endpoint_id}"): (401, 403, 404, 409, 413, 422, 500, 503),
    ("post", "/api/v1/webhooks/{endpoint_id}"): (401, 409, 413, 415, 422, 429, 500, 503),
    ("get", "/api/v1/onboarding/health"): (401, 500, 503),
    ("get", "/api/v1/evaluation/registry"): (401, 403, 422, 500, 503),
    ("get", "/api/v1/evaluation/reports"): (401, 500, 503),
    ("get", "/api/v1/observability/summary"): (401, 500, 503),
}


def _headers(status: int) -> dict:
    headers = {"X-Correlation-ID": {"description": "The request's correlation id (also in `error.correlation_id`)", "schema": {"type": "string"}}}
    if status in RETRY_AFTER:
        headers["Retry-After"] = {"description": "Seconds to wait before retrying", "schema": {"type": "integer"}}
    return headers


def apply_error_contract(schema: dict) -> dict:
    """Replace each operation's error responses in a generated OpenAPI document with the declared, typed ones (in place; returns the document)."""
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    model = ErrorResponse.model_json_schema(ref_template="#/components/schemas/{model}")
    for name, sub in model.pop("$defs", {}).items():
        components[name] = sub
    components["ErrorResponse"] = model
    size_model = SizeLimitErrorResponse.model_json_schema(ref_template="#/components/schemas/{model}")
    for name, sub in size_model.pop("$defs", {}).items():
        components[name] = sub
    components["SizeLimitErrorResponse"] = size_model
    ref = {"$ref": "#/components/schemas/ErrorResponse"}
    for path, ops in schema["paths"].items():
        for method, op in ops.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            responses = op["responses"]
            for code in [c for c in responses if c.startswith(("4", "5"))]:
                del responses[code]
            for status in ERROR_STATUSES[(method, path)]:
                body = ref
                if status == 413:  # the middleware body has no correlation_id; the upload handler's own file_too_large uses the full envelope
                    size_ref = {"$ref": "#/components/schemas/SizeLimitErrorResponse"}
                    body = {"anyOf": [size_ref, ref]} if path == "/api/v1/documents" else size_ref
                responses[str(status)] = {"description": STATUS_TEXT[status], "headers": _headers(status), "content": {"application/json": {"schema": body}}}
    for name in ("HTTPValidationError", "ValidationError"):
        if name in components and name not in str(schema["paths"]):
            del components[name]
    return schema
