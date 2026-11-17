import { useState } from "react";
import type { Citation, HistoryEvent } from "../types";
import { Badge, fmtTime } from "./ui";

/**
 * Consistent vocabulary for where a piece of information comes from, so the UI never presents AI output,
 * retrieved evidence, deterministic checks, human decisions and external confirmations as the same thing.
 */
export type Provenance = "ai" | "evidence" | "verified" | "human" | "approved" | "submitted" | "pending" | "failed";

const PROVENANCE: Record<Provenance, { label: string; tone: string; hint: string }> = {
  ai: { label: "AI-generated", tone: "info", hint: "Written by the language model. Not a verified fact until a person confirms it." },
  evidence: { label: "Retrieved evidence", tone: "neutral", hint: "Passage retrieved from this tenant's documents." },
  verified: { label: "Verified", tone: "ok", hint: "Checked by deterministic code against stored data (for example a verbatim quote or a register entry)." },
  human: { label: "Human-reviewed", tone: "ok", hint: "A person made and justified this decision." },
  approved: { label: "Approved", tone: "ok", hint: "A person approved this action. It has not necessarily been sent anywhere yet." },
  submitted: { label: "Submitted", tone: "ok", hint: "The external system confirmed receipt and returned an identifier." },
  pending: { label: "Pending", tone: "warn", hint: "Waiting for a person or for a background process." },
  failed: { label: "Failed", tone: "bad", hint: "The operation failed; see the error." },
};

export function ProvenanceTag({ kind, children }: { kind: Provenance; children?: string }) {
  const p = PROVENANCE[kind];
  return <Badge tone={p.tone} title={p.hint}>{children ?? p.label}</Badge>;
}

const TICKET_STATES: Record<string, { label: string; tone: string }> = {
  DRAFT: { label: "Draft", tone: "neutral" },
  PENDING_APPROVAL: { label: "Awaiting approval", tone: "warn" },
  APPROVED: { label: "Approved · not yet submitted", tone: "warn" },
  SUBMITTING: { label: "Submitting…", tone: "warn" },
  SUBMITTED: { label: "Submitted", tone: "ok" },
  FAILED: { label: "Failed", tone: "bad" },
  RETRY_PENDING: { label: "Retry scheduled", tone: "warn" },
  REJECTED: { label: "Rejected", tone: "bad" },
  CANCELLED: { label: "Cancelled", tone: "neutral" },
};

/** A ticket is only shown as submitted when the backend says SUBMITTED AND returned an external identifier. */
export function TicketStateBadge({ state, externalId }: { state: string; externalId?: string | null }) {
  if (state === "SUBMITTED" && !externalId) return <Badge tone="warn" title="The backend reports SUBMITTED but no external id was stored">Submitted (no external id)</Badge>;
  const s = TICKET_STATES[state] ?? { label: state, tone: "neutral" };
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

const REVIEW: Record<string, { label: string; tone: string; hint: string }> = {
  pending_review: { label: "Evidence verified · ready for a ticket", tone: "ok", hint: "Registered asset and grounded, verified evidence." },
  needs_review: { label: "Blocked · human review required", tone: "bad", hint: "Missing evidence, unregistered asset or a validation problem. No ticket can be drafted until a supervisor reviews it." },
  accepted: { label: "Human-reviewed · accepted", tone: "ok", hint: "A supervisor accepted it with a written justification. This does not verify unsupported claims or an unregistered asset." },
  rejected: { label: "Rejected by reviewer", tone: "bad", hint: "Rejected incidents can never become tickets." },
};

export function ReviewBadge({ status }: { status: string }) {
  const r = REVIEW[status] ?? { label: status, tone: "neutral", hint: "" };
  return <Badge tone={r.tone} title={r.hint}>{r.label}</Badge>;
}

export function PriorityBadge({ priority }: { priority: string }) {
  const tone = priority === "P1" ? "bad" : priority === "P2" ? "warn" : "neutral";
  return <Badge tone={tone} title="Priority is decided by deterministic rules, never by the model">{priority}</Badge>;
}

export function CitationList({ citations, empty = "No citations." }: { citations: Citation[]; empty?: string }) {
  const [open, setOpen] = useState<number | null>(null);
  if (!citations.length) return <p className="muted">{empty}</p>;
  return (
    <ol className="citations" aria-label="Citations">
      {citations.map((c, i) => (
        <li key={`${c.marker}-${i}`}>
          <div className="row tight">
            <strong>[{c.marker}] {c.filename}</strong>
            <span className="muted">v{c.version}{c.page_number ? ` · page ${c.page_number}` : ""}{c.record_id ? ` · record ${c.record_id}` : ""}</span>
            <ProvenanceTag kind="evidence" />
            <ProvenanceTag kind="verified">Verbatim quote verified</ProvenanceTag>
            <button className="linklike small" aria-expanded={open === i} onClick={() => setOpen(open === i ? null : i)}>
              {open === i ? "Hide details" : "Inspect"}
            </button>
          </div>
          <blockquote>{c.quote}</blockquote>
          {open === i && (
            <dl className="kv compact" aria-label={`Citation ${c.marker} details`}>
              <div><dt>Source document</dt><dd>{c.filename} (version {c.version})</dd></div>
              <div><dt>Location</dt><dd>{c.page_number ? `page ${c.page_number}` : c.record_id ? `record ${c.record_id}` : "whole document"}</dd></div>
              <div><dt>Passage id</dt><dd><code>{c.chunk_id}</code></dd></div>
              <div><dt>Check</dt><dd>The quote was matched character-for-character against this tenant&apos;s stored passage before the answer was accepted.</dd></div>
            </dl>
          )}
        </li>
      ))}
    </ol>
  );
}

const ACTION_LABELS: Record<string, string> = {
  "incident.extracted": "Incident extracted (AI-assisted)",
  "incident.review_accept": "Human review: accepted",
  "incident.review_reject": "Human review: rejected",
  "incident.asset_reverified": "Asset re-verified against the register",
  "measurement.verified": "Measurement verified by a human reviewer",
  "measurement.rejected": "Measurement rejected by a human reviewer",
  "incident.priority_decided": "Priority decided by the deterministic rules",
  "ticket.drafted": "Ticket drafted",
  "ticket.edited": "Draft edited",
  "ticket.submit_requested": "Submission requested",
  "approval.approved": "Approval decision: approved",
  "approval.rejected": "Approval decision: rejected",
  "ticket.submitted": "Submitted to the external system (confirmed)",
  "submission.retry_scheduled": "Submission failed; retry scheduled",
  "submission.dead_lettered": "Submission failed permanently",
  "submission.blocked": "Submission blocked by a release control",
  "ticket.transition": "State changed",
};

export function Timeline({ events }: { events: HistoryEvent[] }) {
  if (!events.length) return <p className="muted">No recorded events.</p>;
  return (
    <ol className="timeline" aria-label="History">
      {events.map((e) => (
        <li key={e.id}>
          <strong>{ACTION_LABELS[e.action] ?? e.action}</strong>
          <span className="muted small"> · {e.actor} · {fmtTime(e.created_at)}</span>
          {typeof e.details?.from === "string" && typeof e.details?.to === "string" && <span className="small"> · {e.details.from} → {e.details.to}</span>}
          {typeof e.details?.measurement === "string" && <span className="small"> · {e.details.measurement}</span>}
          {typeof e.details?.priority_before === "string" && typeof e.details?.priority_after === "string" && <span className="small"> · priority {e.details.priority_before} → {e.details.priority_after}</span>}
          {typeof e.details?.comment === "string" && e.details.comment && <blockquote>{e.details.comment}</blockquote>}
          {typeof e.details?.external_ticket_id === "string" && <span className="small"> · external id <code>{e.details.external_ticket_id}</code></span>}
          {typeof e.details?.error === "string" && <span className="error small"> · {e.details.error}</span>}
        </li>
      ))}
    </ol>
  );
}

export function JsonView({ value }: { value: unknown }) {
  return <pre className="json" aria-label="Details">{JSON.stringify(value, null, 2)}</pre>;
}
