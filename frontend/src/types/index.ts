export interface Session {
  token: string;
  role: string;
  tenant: string;
  tenantId: string | null;
  email: string;
  userId: string;
  /** Unix seconds from the token's exp claim (a usability hint; the server validates the token). */
  expiresAt: number | null;
}

export interface Page<T> {
  total: number;
  limit: number;
  offset: number;
  items: T[];
}

export interface DocumentRow {
  id: string;
  filename: string;
  kind: string;
  current_version: number;
  chunk_count: number | null;
  page_count: number | null;
  created_at: string;
}

export interface DocumentDetail {
  id: string;
  filename: string;
  kind: string;
  current_version: number;
  versions: { version: number; sha256: string; chunks: number; size_bytes: number; embedding_backend: string; created_at: string }[];
}

export interface Citation {
  marker: number;
  chunk_id: string;
  document_id?: string;
  filename: string;
  version: number;
  page_number: number | null;
  record_id: string | null;
  quote: string;
}

export interface AnswerResult {
  answer: string;
  grounded: boolean;
  insufficient_evidence: boolean;
  citations: Citation[];
  excluded_suspicious: string[];
  llm_backend: string;
  embedding_backend: string;
  problems: string[];
}

export interface SearchHit {
  chunk_id: string;
  document_id: string;
  filename: string;
  page_number: number | null;
  record_id: string | null;
  text: string;
  similarity: number;
  suspicious: boolean;
  version?: number;
  kind?: string;
}

export interface RelatedIncident {
  record_id: string | null;
  summary: string;
  filename: string;
  same_asset: boolean;
}

/** Subset of the server's measurement record (GET /incidents/{id}). Every trust field is read-only server output; the UI never writes any of it. */
export interface MeasurementProvenance {
  source_type?: string | null;
  source_available?: boolean;
  source_missing_reason?: string | null;
  evidence_span?: string | null;
  extraction_origin?: string | null;
  channel?: string | null;
  client_source_label?: string | null;
  submitted_by?: string | null;
  simulation_source_id?: string | null;
}

export interface MeasurementVerification {
  decision: string;
  transition: string;
  reviewer_id: string;
  reviewed_at: string;
  comment: string;
  priority_before: string;
  priority_after: string;
  applied_rule: string;
  audit_event_id?: number | null;
}

export interface Measurement {
  name: string;
  status: string;
  trust_status?: string | null;
  evidence_class?: string | null;
  eligible_for_numeric_priority?: boolean | null;
  measurement_type?: string | null;
  asset_id?: string | null;
  value?: number | null;
  candidate_value?: number | null;
  unit?: string | null;
  original_value?: string | null;
  original_unit?: string | null;
  source_text?: string | null;
  observation_timestamp?: string | null;
  reason?: string | null;
  implied_priority?: string | null;
  potentially_critical?: boolean | null;
  simulated?: boolean | null;
  provenance?: MeasurementProvenance | null;
  verification?: MeasurementVerification | null;
}

export interface Incident {
  id: string;
  asset_id: string;
  asset_verified: boolean;
  category: string;
  symptoms: string[];
  related_incidents: RelatedIncident[];
  priority: string;
  citations: Citation[];
  recommended_action: string;
  review_status: string;
  /** "urgent" flags that a person should look soon; it is not a verified numeric priority. */
  review_urgency?: "urgent" | "routine" | "none";
  measurements?: Measurement[];
  notes: string[];
  report_text: string;
  extraction_backend: string;
  created_at: string;
}

export interface Ticket {
  id: string;
  incident_id: string;
  title: string;
  description: string;
  priority: string;
  state: string;
  external_ticket_id: string | null;
  attempts: number;
  last_error: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  submitted_at: string | null;
}

export interface HistoryEvent {
  id: number;
  action: string;
  actor: string;
  actor_type: string;
  details: Record<string, unknown>;
  created_at: string;
}

export interface TicketHistory {
  ticket_id: string;
  events: HistoryEvent[];
  approvals: { decision: string; decided_by: string; comment: string | null; decided_at: string }[];
}

export interface IncidentHistory {
  incident_id: string;
  events: HistoryEvent[];
  tickets: { id: string; state: string; external_ticket_id: string | null }[];
}

export interface ApprovalRecord {
  ticket_id: string;
  decision: string;
  decided_by: string;
  comment: string | null;
  decided_at: string;
}

export interface WorkflowEvent {
  id: number;
  topic: string;
  ticket_id: string;
  status: string;
  attempts: number;
  last_error: string | null;
  created_at: string;
  processed_at: string | null;
}

export interface AuditRow {
  id: number;
  action: string;
  entity_type: string;
  entity_id: string | null;
  actor: string;
  actor_type: string;
  details: Record<string, unknown>;
  correlation_id: string | null;
  created_at: string;
}

export interface Metrics {
  tickets_by_state: Record<string, number>;
  incidents_by_review_status: Record<string, number>;
  incidents_by_priority: Record<string, number>;
  outbox_by_status: Record<string, number>;
  documents_by_kind: Record<string, number>;
  documents: number;
  incidents: number;
  dead_letters: number;
  submission_attempts: number;
  tickets_needing_retries: number;
  approvals_decided: number;
  avg_approval_turnaround_seconds: number | null;
}

export interface TenantProfileInfo {
  version: number;
  using_defaults: boolean;
  updated_at: string | null;
  profile: null | {
    asset_label: string;
    register_kind: string;
    guidance_kinds: string[];
    history_kind: string | null;
    document_kinds: string[];
    categories?: { name: string; keywords: string[]; description?: string }[];
    signals?: { name: string; unit?: string }[];
    priority_rules?: { priority: string; any: Record<string, unknown>[] }[];
    enrichments?: { label: string; connector_kind: string }[];
    default_priority?: string;
  };
}

export interface Connector {
  id: string;
  kind: string;
  name: string;
  base_url: string;
  has_secret: boolean;
  config: Record<string, unknown>;
}

export interface LiveProbe {
  status: "ok" | "connectivity" | "authentication" | "rate_limited" | "schema" | "upstream_error" | "denied" | "not_configured";
  http_status: number | null;
  duration_ms: number;
  checked_at: string;
}

export interface SyncSummary {
  pages: number; seen: number; created: number; updated: number; unchanged: number; linked_duplicate: number; skipped_deleted: number;
  tombstoned_changed: number; duplicate_in_sync: number; conflict: number; invalid: number; rejections: Record<string, number>; truncated: boolean;
}

export interface IngestionJob {
  id: string;
  job_type: "ingest" | "reprocess" | "sync" | "webhook";
  status: "QUEUED" | "PROCESSING" | "RETRY_PENDING" | "COMPLETED" | "FAILED" | "CANCELLED";
  filename: string | null;
  attempts: number;
  max_attempts: number;
  error_code: string | null;
  outcome: string | null;
  connector_id: string | null;
  endpoint_id: string | null;
  sync: SyncSummary | null;
  created_at: string;
}

export interface WebhookEndpoint {
  id: string;
  name: string;
  status: "active" | "disabled";
  receive_path: string;
  secret_configured: boolean;
  has_previous_secret: boolean;
  config: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ConnectorHealth {
  id: string;
  kind: string;
  name: string;
  base_url: string;
  status: "ok" | "degraded" | "blocked";
  destination_authorized: boolean;
  destination_reason: string | null;
  secret_configured: boolean | null;
  has_secret_ref: boolean;
  probe: string;
  live_probe?: LiveProbe | null;
  delivery?: {
    submitted: number;
    failed: number;
    retry_pending: number;
    submitting: number;
    last_success_at: string | null;
    last_error: string | null;
  };
}

export interface OnboardingCheck {
  id: string;
  label: string;
  status: "pass" | "fail" | "unavailable";
  detail: string;
}

export interface OnboardingHealth {
  checks: OnboardingCheck[];
  passed: number;
  total: number;
}

export interface Member {
  user_id: string;
  email: string;
  full_name: string;
  role: string;
}

export interface EvaluationMetrics {
  recall_at_5: number | null;
  mrr: number | null;
  precision_at_5: number | null;
  citation_correctness: number | null;
  groundedness_rate: number | null;
  correct_refusals: string | null;
  structured_validity: number | null;
  duplicate_tickets: number | null;
  llm_inference_median_s: number | null;
  llm_inference_p95_s: number | null;
  e2e_median_s: number | null;
  e2e_p95_s: number | null;
}

export interface EvaluationRun {
  id: string;
  group: string;
  evidence_class: string | null;
  backends: { llm: string; embedding: string } | null;
  dataset: string | null;
  started_utc: string | null;
  command: string | null;
  has_note: boolean;
  versions: Record<string, string | null>;
  hardware: Record<string, string | number | null>;
  metrics: EvaluationMetrics;
}

export interface EvaluationReports {
  available: boolean;
  disclaimer: string;
  targets: { id: string; label: string; op: string; value: number; status: string; actual: { min: number; max: number; runs: number } | null }[];
  runs: EvaluationRun[];
  smoke: { id: string; label: string; started_utc: string; checks_passed: number; checks_total: number; failed: string[] }[];
  fault_injection: { scenarios: number; passed: number; failed: number; items: { id: string; name: string; passed: boolean }[] } | null;
}

export interface ObservabilitySummary {
  scope: string;
  process: {
    uptime_s: number;
    counters: { name: string; labels: Record<string, string>; value: number }[];
    timers: { name: string; labels: Record<string, string>; count: number; mean_s: number; p50_s: number; p95_s: number; max_s: number }[];
  };
  database: {
    submission: { submitted: number; retries_scheduled: number; dead_lettered: number; blocked_by_release_controls: number };
    incident_review: { extracted: number; needs_review_now: number; required_review: number; review_required_rate: number | null; accepted: number; rejected: number; cleared_without_review: number };
    approvals: { approved: number; rejected: number };
    ticket_transitions: { from: string; to: string; count: number }[];
    ticket_error_classes: Record<string, number>;
  };
}
