"""Typed success-response contracts for every API operation (V41-17.03, Batch 3).

Design rules (the contract must describe the response the API ALREADY returns; nothing here changes behaviour):
  * Routes declare `response_model=...` with `response_model_exclude_unset=True`: a key a handler omits stays omitted and a key it sets to null stays null, so the JSON is
    byte-for-byte the same shape as before (proved by the pre-change baseline comparison in tests/test_api_response_contract.py).
  * Identifiers and timestamps are plain strings (the handlers already serialise them) with an OpenAPI `format` annotation, so nothing is re-parsed or re-formatted.
  * Numbers that may be int or float use `Number` so an int is never turned into a float.
  * Closed vocabularies enforced by the database or by code are `Literal` types; open vocabularies stay `str`.
  * Free-form JSON is typed `dict[str, Any]` ONLY where the content is genuinely open: audit-event `details`, connector `config`, and metric/label maps. Each is listed in
    FREE_FORM_EXCEPTIONS and checked by a test, so an exception cannot grow silently.
  * Models that describe stored JSON (measurement records) allow extra keys, so a newer record never makes a response fail; the contract test asserts every runtime key is declared."""
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.profile.schema import TenantProfile

T = TypeVar("T")


def _closed_schema(schema: dict) -> None:
    schema["additionalProperties"] = False


class Out(BaseModel):
    """Base of every response model. At RUNTIME extra keys pass through untouched (a handler that adds a field never silently loses it from the response); the PUBLISHED schema is
    closed (additionalProperties false), so any undeclared key a handler returns is reported by the runtime conformance tests instead of going unnoticed."""
    model_config = ConfigDict(extra="allow", json_schema_extra=_closed_schema)


def _open_schema(schema: dict) -> None:
    schema["additionalProperties"] = True


class OpenOut(BaseModel):
    """Base of models that deliberately describe open stored JSON: extra keys are allowed at runtime and in the published schema."""
    model_config = ConfigDict(extra="allow", json_schema_extra=_open_schema)


UUIDStr = Annotated[str, Field(json_schema_extra={"format": "uuid"})]
DateTimeStr = Annotated[str, Field(json_schema_extra={"format": "date-time"})]
Number = int | float
Priority = Literal["P1", "P2", "P3", "P4"]
TicketState = Literal["DRAFT", "PENDING_APPROVAL", "APPROVED", "REJECTED", "SUBMITTING", "SUBMITTED", "FAILED", "RETRY_PENDING", "CANCELLED"]
ReviewStatus = Literal["pending_review", "needs_review", "accepted", "rejected"]
OutboxStatus = Literal["pending", "processing", "done", "dead"]

# response models that deliberately describe open stored JSON (additionalProperties true in the published schema); every other response object is closed
OPEN_MODELS = {"EvidenceLocation", "ProvenanceEnvelope", "VerificationBlock", "MeasurementRecord", "EvaluationBackends", "EvaluationTarget"}

# the tenant profile is described by its own validated domain schema (app.profile.schema): the stored config was validated against it on write, so it is reused as is
EXTERNAL_MODELS = {"TenantProfile", "Category", "Condition", "Enrichment", "KindMapping", "PriorityRule", "Signal", "Symptom"}

# the only places where open JSON is accepted as dict[str, Any] (checked by test_p1_free_form_exceptions_are_exactly_the_documented_set)
FREE_FORM_EXCEPTIONS = {
    "AuditEventItem.details", "HistoryEvent.details", "PlatformAuditItem.details", "ConnectorItem.config", "CounterSample.labels", "TimerSummary.labels",
}


class CitationOut(Out):
    """A citation to a verbatim passage of an ingested document (same fields as the domain Citation)."""
    marker: int
    chunk_id: str
    document_id: str
    filename: str
    version: int
    page_number: int | None = None
    record_id: str | None = None
    quote: str


class RelatedIncidentOut(Out):
    record_id: str | None
    summary: str
    filename: str
    chunk_id: str
    same_asset: bool


class Page(Out, Generic[T]):
    """Common pagination envelope of every list endpoint."""
    total: int
    limit: int
    offset: int
    items: list[T]


# ---------------------------------------------------------------- session, tenants, members
class HealthResponse(Out):
    status: Literal["ok"]
    llm_backend: str
    embedding_backend: str


class LoginUser(Out):
    id: UUIDStr
    email: str
    full_name: str


class LoginResponse(Out):
    access_token: str
    token_type: str
    role: str | None = None
    tenant_id: UUIDStr | None = None
    user: LoginUser


class MeResponse(Out):
    id: UUIDStr
    email: str
    full_name: str
    role: str | None = None
    tenant_id: UUIDStr | None = None
    is_platform_admin: bool


class TenantMineItem(Out):
    id: UUIDStr
    slug: str
    name: str
    role: str


class TenantsMine(Out):
    items: list[TenantMineItem]


class TenantCreated(Out):
    id: UUIDStr
    slug: str
    name: str


class PlatformAuditItem(Out):
    id: int
    actor_id: UUIDStr | None = None
    action: str
    details: dict[str, Any]
    created_at: DateTimeStr


class Member(Out):
    user_id: UUIDStr
    email: str
    full_name: str
    role: str


class MembersList(Out):
    items: list[Member]


class MemberChange(Out):
    user_id: UUIDStr
    role: str


class MemberRemoved(Out):
    removed: UUIDStr


# ---------------------------------------------------------------- connectors, profile, onboarding
class ConnectorItem(Out):
    id: UUIDStr
    kind: str
    name: str
    base_url: str
    has_secret: bool
    config: dict[str, Any]


class ConnectorsList(Out):
    items: list[ConnectorItem]


class ConnectorCreated(Out):
    id: UUIDStr
    kind: str
    name: str


class ConnectorDelivery(Out):
    submitted: int
    failed: int
    retry_pending: int
    submitting: int
    last_success_at: DateTimeStr | None
    last_error: str | None


class LiveProbe(Out):
    """Result of one bounded real request to the external source (nothing ingested, nothing changed upstream); sanitised: a class and numbers only."""
    status: Literal["ok", "connectivity", "authentication", "rate_limited", "schema", "upstream_error", "denied", "not_configured"]
    http_status: int | None
    duration_ms: float
    checked_at: DateTimeStr


class ConnectorStatus(Out):
    id: UUIDStr
    kind: str
    name: str
    base_url: str
    destination_authorized: bool
    destination_reason: str | None
    secret_configured: bool | None
    has_secret_ref: bool
    probe: str
    status: Literal["ok", "blocked", "degraded"]
    delivery: ConnectorDelivery | None = None  # present for ticketing connectors only
    live_probe: LiveProbe | None = None  # present only when the request asked for probe=true and the connector is a REST records connector


class ConnectorsHealth(Out):
    items: list[ConnectorStatus]


class ProfileRead(Out):
    version: int
    using_defaults: bool
    profile: TenantProfile | None
    updated_at: DateTimeStr | None


class ProfileSaved(Out):
    version: int


class OnboardingCheck(Out):
    id: str
    label: str
    status: Literal["pass", "fail", "unavailable"]  # "unavailable": connector checks are visible to tenant administrators only
    detail: str


class OnboardingHealth(Out):
    checks: list[OnboardingCheck]
    passed: int
    total: int


# ---------------------------------------------------------------- documents, ingestion, search, ask
class DocumentRow(Out):
    id: UUIDStr
    filename: str
    kind: str
    current_version: int
    chunk_count: int | None
    page_count: int | None
    created_at: DateTimeStr


class DocumentUploaded(Out):
    document_id: UUIDStr
    version: int
    chunk_count: int
    status: str


class DocumentDeletion(Out):
    """State of a document deletion: logical deletion is immediate; `cleanup_state` says whether its content has been removed (pending, completed, failed)."""
    id: UUIDStr
    filename: str
    lifecycle_status: Literal["deleted"]
    cleanup_state: Literal["pending", "completed", "failed"]
    deleted_at: DateTimeStr
    cleanup_completed_at: DateTimeStr | None
    already_deleted: bool


class ProcessingConfig(Out):
    embedding_backend: str | None
    embedding_model: str | None
    index_prefix: bool | None
    safety_heuristics: str | None


class SyncSummary(Out):
    """Counts of a REST synchronisation (never record content)."""
    pages: int
    seen: int
    created: int
    updated: int
    unchanged: int
    linked_duplicate: int
    skipped_deleted: int
    tombstoned_changed: int
    duplicate_in_sync: int
    conflict: int
    invalid: int
    rejections: dict[str, int]
    truncated: bool


class WebhookConfigOut(Out):
    record_path: str | None
    id_field: str
    version_field: str | None
    required_fields: list[str]
    document_kind: str
    max_records: int
    max_record_bytes: int
    reject_policy: str


class WebhookEndpointOut(Out):
    """A provisioned inbound endpoint. The signing secret is never part of it: only whether the server has the named variable, and whether a rotation is in progress."""
    id: UUIDStr
    name: str
    status: Literal["active", "disabled"]
    receive_path: str
    secret_configured: bool
    has_previous_secret: bool
    config: WebhookConfigOut
    created_at: DateTimeStr
    updated_at: DateTimeStr


class WebhookEndpointsList(Out):
    items: list[WebhookEndpointOut]


class WebhookAccepted(Out):
    """A delivery that was durably queued (replay-protected, original stored). It does NOT mean the records were processed: follow `job_id` on GET /ingestion/jobs."""
    delivery_id: str
    job_id: UUIDStr
    status: Literal["QUEUED"]


class IngestionJobOut(Out):
    """A durable ingestion job (an upload attempt or a reprocessing request). Its status is server-controlled; no content is ever returned."""
    id: UUIDStr
    job_type: Literal["ingest", "reprocess", "sync", "webhook"]
    status: Literal["QUEUED", "PROCESSING", "RETRY_PENDING", "COMPLETED", "FAILED", "CANCELLED"]
    document_id: UUIDStr | None
    filename: str | None
    source_version: int | None
    attempts: int
    max_attempts: int
    next_attempt_at: DateTimeStr | None
    error_code: str | None
    error_detail: str | None
    outcome: str | None
    chunks: int | None
    from_generation: int | None
    to_generation: int | None
    connector_id: UUIDStr | None
    endpoint_id: UUIDStr | None
    sync: SyncSummary | None
    requested_by: UUIDStr | None
    correlation_id: str | None
    processing_config: ProcessingConfig
    created_at: DateTimeStr
    updated_at: DateTimeStr
    completed_at: DateTimeStr | None


class DocumentVersionRow(Out):
    version: int
    sha256: str
    chunks: int
    size_bytes: int
    embedding_backend: str
    created_at: DateTimeStr


class DocumentDetail(Out):
    id: UUIDStr
    filename: str
    kind: str
    current_version: int
    versions: list[DocumentVersionRow]


class IngestionStatus(Out):
    documents_versions: int
    chunks: int


class SearchHit(Out):
    chunk_id: UUIDStr
    document_id: UUIDStr
    filename: str
    kind: str
    version: int
    page_number: int | None
    record_id: str | None
    text: str
    score: Number
    similarity: Number
    overlap: Number
    suspicious: bool


class SearchResponse(Out):
    embedding_backend: str
    items: list[SearchHit]


class AskResponse(Out):
    answer: str
    grounded: bool
    insufficient_evidence: bool
    citations: list[CitationOut]
    excluded_suspicious: list[str]
    problems: list[str]
    llm_backend: str
    llm_model: str
    embedding_backend: str


# ---------------------------------------------------------------- incidents
class EvidenceLocation(OpenOut):
    """Offsets into the stored report text, or a field reference for structured observations."""
    start: int | None = None
    end: int | None = None
    value_start: int | None = None
    value_end: int | None = None
    field: str | None = None


class ProvenanceEnvelope(OpenOut):
    """Server-built provenance of one numeric candidate (documents origin; never establishes truth)."""
    envelope_version: int
    tenant_id: UUIDStr
    incident_id: UUIDStr
    observation_id: str
    source_type: str
    source_document_id: UUIDStr | None
    source_field: str | None
    evidence_span: str | None
    evidence_location: EvidenceLocation | None
    source_available: bool
    source_missing_reason: str | None
    extraction_origin: str
    trust_class: str | None
    original_status: str | None
    original_trust_status: str | None = None
    submitted_by: UUIDStr | None
    channel: str | None
    client_source_label: str | None
    simulation_source_id: str | None
    establishes_truth: bool


class VerificationBlock(OpenOut):
    decision: str
    transition: str
    reviewer_id: UUIDStr
    reviewed_at: DateTimeStr
    comment: str
    incident_id: UUIDStr
    observation_id: str | None
    priority_before: str
    priority_after: str
    applied_rule: str
    provenance_envelope_unchanged: bool
    audit_event_id: int | None = None


class MeasurementRecord(OpenOut):
    """One numeric measurement record of an incident (stored JSON; extra keys are allowed so a newer record never breaks a response)."""
    name: str
    status: str
    verification_status: str | None = None
    trust_status: str | None = None
    evidence_class: str | None = None
    eligible_for_numeric_priority: bool | None = None
    measurement_type: str | None = None
    asset_id: str | None = None
    value: Number | None = None
    candidate_value: Number | None = None
    candidate_values: list[Number] | None = None
    model_proposed_value: Number | None = None
    normalized_value: Number | None = None
    original_value: str | None = None
    original_unit: str | None = None
    unit: str | None = None
    normalized_unit: str | None = None
    converted: bool | None = None
    numeric_notation: str | None = None
    numeric_locale: str | None = None
    source_text: str | None = None
    context_type: str | None = None
    temporal_status: str | None = None
    observation_timestamp: str | None = None
    evidence_span: str | None = None
    evidence_location: EvidenceLocation | None = None
    reason: str | None = None
    verification_reason: str | None = None
    method: str | None = None
    source: str | None = None
    review_required: bool | None = None
    simulated: bool | None = None
    simulation_source_id: str | None = None
    implied_priority: Priority | None = None
    potentially_critical: bool | None = None
    tenant_id: UUIDStr | None = None
    incident_id: UUIDStr | None = None
    source_document_id: UUIDStr | None = None
    observation_id: str | None = None
    provenance: ProvenanceEnvelope | None = None
    verification: VerificationBlock | None = None
    verified_by: UUIDStr | None = None
    verified_at: DateTimeStr | None = None
    verification_comment: str | None = None


class IncidentOut(Out):
    id: UUIDStr
    asset_id: str
    asset_verified: bool
    category: str
    symptoms: list[str]
    related_incidents: list[RelatedIncidentOut]
    priority: Priority
    citations: list[CitationOut]
    recommended_action: str
    review_status: ReviewStatus
    review_urgency: Literal["urgent", "routine", "none"]
    notes: list[str]
    measurements: list[MeasurementRecord]
    report_text: str
    extraction_backend: str
    created_at: DateTimeStr


class AuditEventItem(Out):
    id: int
    action: str
    entity_type: str | None
    entity_id: str | None
    actor: str | None
    actor_type: str
    details: dict[str, Any]
    correlation_id: str | None
    created_at: DateTimeStr


class HistoryEvent(Out):
    id: int
    action: str
    actor: str | None
    actor_type: str
    details: dict[str, Any]
    created_at: DateTimeStr


class IncidentTicketRef(Out):
    id: UUIDStr
    state: TicketState
    external_ticket_id: str | None


class IncidentHistory(Out):
    incident_id: UUIDStr
    events: list[HistoryEvent]
    tickets: list[IncidentTicketRef]


# ---------------------------------------------------------------- tickets, approvals, workflows
class TicketOut(Out):
    id: UUIDStr
    incident_id: UUIDStr
    title: str
    description: str
    priority: Priority
    state: TicketState
    external_ticket_id: str | None
    attempts: int
    last_error: str | None
    created_by: UUIDStr | None
    created_at: DateTimeStr
    updated_at: DateTimeStr
    submitted_at: DateTimeStr | None


class ApprovalDecisionOut(Out):
    ticket_id: UUIDStr
    decision: Literal["approved", "rejected"]
    decided_by: UUIDStr
    comment: str | None
    decided_at: DateTimeStr


class ApprovalRecord(Out):
    decision: Literal["approved", "rejected"]
    decided_by: UUIDStr
    comment: str | None
    decided_at: DateTimeStr


class TicketHistory(Out):
    ticket_id: UUIDStr
    events: list[HistoryEvent]
    approvals: list[ApprovalRecord]


class WorkflowEvent(Out):
    id: int
    topic: str
    ticket_id: UUIDStr
    status: OutboxStatus
    attempts: int
    last_error: str | None
    created_at: DateTimeStr
    processed_at: DateTimeStr | None


# ---------------------------------------------------------------- metrics, observability, evaluation
class Metrics(Out):
    incidents_by_review_status: dict[str, int]
    incidents_by_priority: dict[str, int]
    outbox_by_status: dict[str, int]
    tickets_needing_retries: int
    documents_by_kind: dict[str, int]
    tickets_by_state: dict[str, int]
    documents: int
    incidents: int
    dead_letters: int
    submission_attempts: int
    approvals_decided: int
    avg_approval_turnaround_seconds: Number | None


class SubmissionCounts(Out):
    submitted: int
    retries_scheduled: int
    dead_lettered: int
    blocked_by_release_controls: int


class IncidentReviewCounts(Out):
    extracted: int
    needs_review_now: int
    required_review: int
    review_required_rate: Number | None
    accepted: int
    rejected: int
    cleared_without_review: int


class ApprovalCounts(Out):
    approved: int
    rejected: int


class TicketTransition(Out):
    model_config = ConfigDict(populate_by_name=True)
    from_: str = Field(alias="from")
    to: str
    count: int


class ObservabilityDatabase(Out):
    submission: SubmissionCounts
    incident_review: IncidentReviewCounts
    approvals: ApprovalCounts
    ticket_transitions: list[TicketTransition]
    ticket_error_classes: dict[str, int]


class TimerSummary(Out):
    name: str
    labels: dict[str, Any]
    count: int
    mean_s: Number
    p50_s: Number
    p95_s: Number
    max_s: Number
    window: int


class CounterSample(Out):
    name: str
    labels: dict[str, Any]
    value: Number


class ObservabilityProcess(Out):
    process_started_at: Number
    uptime_s: Number
    counters: list[CounterSample]
    timers: list[TimerSummary]


class ObservabilitySummary(Out):
    scope: str
    process: ObservabilityProcess
    database: ObservabilityDatabase


class EvaluationBackends(OpenOut):
    llm: str | None = None
    embedding: str | None = None


class EvaluationHardware(Out):
    cpu: str | None
    ram_gb: Number | None
    os: str | None
    gpu: str | None


class EvaluationVersions(Out):
    ollama: str | None
    ollama_model: str | None
    ollama_model_digest: str | None
    embedding_profile: str | None
    python: str | None
    postgres: str | None


class EvaluationMetrics(Out):
    recall_at_5: Number | None
    mrr: Number | None
    precision_at_5: Number | None
    citation_correctness: Number | None
    groundedness_rate: Number | None
    correct_refusals: str | None
    structured_validity: Number | None
    duplicate_tickets: Number | None
    llm_inference_median_s: Number | None
    llm_inference_p95_s: Number | None
    e2e_median_s: Number | None
    e2e_p95_s: Number | None


class EvaluationRun(Out):
    id: str
    group: str
    evidence_class: str | None
    backends: EvaluationBackends | None
    dataset: str | None
    started_utc: str | None
    command: str | None
    hardware: EvaluationHardware
    versions: EvaluationVersions
    has_note: bool
    metrics: EvaluationMetrics


class SmokeModels(Out):
    ollama_model: str | None
    embedding_profile: str | None


class SmokeRun(Out):
    id: str
    label: str | None
    started_utc: str | None
    checks_passed: int
    checks_total: int
    failed: list[str]
    models: SmokeModels


class FaultInjectionItem(Out):
    id: str | None
    name: str | None
    passed: bool | None


class FaultInjectionSummary(Out):
    scenarios: int | None
    passed: int | None
    failed: int | None
    generated_utc: str | None
    items: list[FaultInjectionItem]
    source: str


class TargetActual(Out):
    min: Number
    max: Number
    runs: int


class EvaluationTarget(OpenOut):
    id: str
    label: str
    op: str
    value: Number
    status: str
    actual: TargetActual | None


class EvaluationRegistryRun(Out):
    run_id: str
    suite: str
    label: str | None = None
    command: str | None = None
    dataset: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_s: float | None = None
    git_commit: str | None = None
    manifest_path: str
    manifest_sha256: str


class EvaluationRegistry(Out):
    total: int
    limit: int
    offset: int
    items: list[EvaluationRegistryRun]


class EvaluationReports(Out):
    available: bool
    disclaimer: str
    targets: list[EvaluationTarget]
    runs: list[EvaluationRun]
    smoke: list[SmokeRun]
    fault_injection: FaultInjectionSummary | None
