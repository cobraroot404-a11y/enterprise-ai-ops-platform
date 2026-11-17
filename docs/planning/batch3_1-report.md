# Accelerated Batch 3.1 report: final API contract documentation closure (V41-17.03)

Date: 2026-11-13 (EST). Starting HEAD `fba699d82c57708b7f0f66e0bdc679bb4dedd6c7` (branch `feat/apex-vertical-slice`, clean; specification SHA-256 `b1c573e2…` verified). No push, merge, publication or release. V41-14.02 stays PARTIAL. No runtime status code, response body, handler, authorization rule, endpoint, migration, business logic or numeric-safety change: the only application change is that `create_app` post-processes the OpenAPI document (`apply_error_contract`).

## 1. HTTP success statuses reconciled
The Batch 3 report said "40 returning 200, 5 returning 201" in one place and "six creating operations" in another. The live OpenAPI document and the tests show **39 operations return 200 and 6 return 201**: POST /tenants, POST /tenants/{tenant_id}/members, POST /connectors, POST /documents, POST /incidents/extract, POST /tickets. The runtime was not changed; the Batch 3 report carries an erratum, the inventory and evidence record the counts from the live document, and a test pins them.

## 2. Actual error-response inventory (executed probes, `backend/tests/api_error_probes.py`)
Every operation was driven with failure scenarios: no or invalid token, each of four tenant roles, a platform administrator, unknown ids with and without a valid body, invalid bodies, invalid query values, oversize JSON bodies and files, state conflicts, duplicates, login throttling, concurrency limits held at capacity, unsupported and unreadable uploads, rejected connector destinations, and an injected database outage and internal error on all 45 operations. Observed statuses per operation became the declared set (401 on 44 operations, 403 on 23, 404 on 19, 409 on 13, 413 on 15, 415 on 1, 422 on 22, 429 on 4, 500 and 503 on all 45). Statuses an operation cannot produce are not declared (for example no 422 where there is no body or query parameter, no 413 without a body, 415 only on upload). 405 and unknown-path 404 are routing errors, covered by the existing standardized-error tests, not per operation.

## 3. Models and OpenAPI changes
`backend/app/api/v1/error_contracts.py`: `ErrorResponse`/`ErrorInfo`/`ErrorDetail` (closed schemas; `details` only for validation errors), `SizeLimitErrorResponse` (the 413 body produced by the size-limit middleware has no `correlation_id` in the body; found by the probes; documented as it is, upload `file_too_large` uses the full envelope so POST /documents declares both), per-status descriptions naming the observed codes, `X-Correlation-ID` on every error response, `Retry-After` on 429 and 503. FastAPI's default 422 `HTTPValidationError` and `ValidationError` are no longer published. Reviewed snapshot diff against Batch 3: all 45 operations changed only in `responses`; success schemas, parameters, request bodies and security unchanged; schemas removed: HTTPValidationError, ValidationError; added: ErrorDetail, ErrorInfo, ErrorResponse, SizeLimitErrorInfo, SizeLimitErrorResponse; no existing schema changed.

## 4. Tests (`backend/tests/test_api_error_contract.py`, 7 tests)
Documented schemas and headers; the status table equals the document; every observed error body (more than 300) validates against its documented schema with the independent validator, correlation header present and equal to the body id, Retry-After exactly on 429/503, details iff validation error, no internals; declared and emitted statuses agree in both directions; every observed error code is named in its status description; undeclarable statuses are absent; 39/6 counts and the six creating operations.

## 5. Results (executed on the final code)
Backend 528 passed, 18 skipped (opt-in real-AI and acceptance harnesses), 0 failed, including the nine-property suite, the pre-Batch-3 baseline comparison, schema conformance, tenant isolation, RBAC, human-verification and numeric trust suites unchanged. Lint: 8 findings, all pre-existing. Root suites and evidence regeneration: see section 7.

## 6. Not re-run, and why
Real-AI (Ollama), real-stack customer acceptance and frontend checks were not re-run: the change is OpenAPI metadata only, no runtime response, inference path or frontend file changed. Their Batch 3 results are historical evidence, not new results.

## 7. Evidence
`evaluation/api-quality/api-quality-evidence.json` regenerated from the executed suites (now includes the error-contract tests, live status counts and the error-contract summary); `docs/api/response-inventory.md` gains the HTTP status section.

## 8. Remaining limitations
Handlers still return dictionaries validated at the framework boundary; the 413 size-limit body lacks `correlation_id` in the body (header only; fixing it would change a runtime body, which this batch forbids); error codes are an open vocabulary listed in descriptions rather than an enum; error documentation reflects scenarios the probes can reach (for example 503 `dependency_unavailable` for the embedding model is covered by the 503 status, not by a dedicated probe); same-author evidence.

## 9. Requirement status recommendation
Original V41-17.03 wording: typed contracts, validation, pagination, standardized errors, OpenAPI, migrations, transactions, constraints, indexes. All nine are verified by executed tests, success and error contracts are now documented and runtime-validated. **ELIGIBLE FOR VERIFIED.** Not changed: the status stays Partial in the records pending owner approval. V41-14.02 stays PARTIAL.

## 10. Files changed
New: `backend/app/api/v1/error_contracts.py`, `backend/tests/api_error_probes.py`, `backend/tests/test_api_error_contract.py`, `docs/planning/batch3_1-report.md`. Changed: `backend/app/main.py` (one import, one call), `backend/tests/snapshots/openapi_contract.json`, `scripts/api_quality_report.py`, `scripts/api_response_inventory.py`, `docs/api/api-quality.md`, `docs/api/response-inventory.md`, `docs/planning/batch3-report.md` (erratum), `pyproject.toml` (E501 exemption), requirement and traceability data and generated documents, evidence JSON.

## 11. Reproduce
```
cd backend && python -m pytest tests/test_api_contract.py tests/test_api_response_schemas.py tests/test_api_response_contract.py tests/test_api_error_contract.py
cd .. && python scripts/api_quality_report.py && python scripts/api_response_inventory.py
python -m pytest backend/tests -q && python -m pytest tests -q
```

## 12. Recommended next independent work package
The local-demo documentation set (README sections, architecture diagrams, runbook, troubleshooting), or the decisions that unlock document deletion (V41-12.05).
