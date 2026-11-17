import { useRef, useState } from "react";
import { Badge, Field, Notice } from "./ui";
import ConfirmDialog from "./ConfirmDialog";
import { PriorityBadge } from "./provenance";
import { ApiError, post } from "../services/api";
import { can } from "../services/rbac";
import type { HistoryEvent, Incident, Measurement, Session } from "../types";

/** Trust vocabulary shown to people. Every value here is server output; nothing in this file can change a trust classification. */
function trustBadge(m: Measurement) {
  const t = m.trust_status ?? "UNVERIFIED";
  if (t === "HUMAN_VERIFIED") return <Badge tone="ok" title="A reviewer verified this reading against its source. It is eligible for the numeric priority rules.">Human-verified</Badge>;
  if (t === "SIMULATED_VALIDATED") return <Badge tone="info" title="HMAC-signed simulation fixture; labelled SIMULATED and never presented as a real sensor.">Simulated (signed fixture)</Badge>;
  if (t === "SOURCE_AUTHENTICATED") return <Badge tone="ok" title="Reading from an authenticated source.">Source-authenticated</Badge>;
  if (t === "REJECTED") return <Badge tone="bad" title="A reviewer rejected this reading. It stays excluded from priority.">Rejected by reviewer</Badge>;
  if (t === "VALIDATED") return <Badge tone="warn" title="Submitted as a structured observation and shape-checked. A submission is not a verification: it still needs a human reviewer.">Submitted · awaiting verification</Badge>;
  return <Badge tone="warn" title="A number found in free text or proposed by the model. It is a candidate only and never changes priority by itself.">Unverified candidate</Badge>;
}

const PENDING = ["unverified", "submitted"];
const isPending = (m: Measurement) => PENDING.includes(m.status);
/** The API accepts exactly these two states as the guard of a decision. */
const guardable = (m: Measurement) => m.trust_status === "UNVERIFIED" || m.trust_status === "VALIDATED";

function fmtValue(m: Measurement): string {
  const v = m.candidate_value ?? m.value;
  if (v === null || v === undefined) return "no supported value";
  return `${v}${m.unit ? ` ${m.unit}` : ""}`;
}

function describeError(err: unknown): { text: string; refresh: boolean } {
  if (!(err instanceof ApiError)) return { text: "Action failed", refresh: false };
  if (err.status === 0) return { text: "Cannot reach the server. Nothing was changed; try again.", refresh: false };
  if (err.status === 403 && err.code === "separation_of_duties") return { text: "You created this incident, so you cannot verify its measurements. A different reviewer must do it.", refresh: false };
  if (err.status === 403) return { text: `The server refused this action for your role. ${err.message}`, refresh: false };
  if (err.status === 404) return { text: "This incident was not found in your tenant.", refresh: false };
  if (err.status === 409) return { text: `${err.message}. Someone else may already have decided; the latest state is shown below.`, refresh: true };
  if (err.status === 422) return { text: `The decision was not accepted: ${err.message}`, refresh: false };
  return { text: err.message, refresh: false };
}

interface Props {
  incident: Incident;
  events: HistoryEvent[];
  session: Session;
  onChanged: () => void;
}

export default function MeasurementPanel({ incident, events, session, onChanged }: Props) {
  const measurements = incident.measurements ?? [];
  const canReview = can(session.role, "incidents:review");
  // Usability aid only: the server enforces separation of duties. The creator is the actor of the incident.extracted audit event.
  const creator = events.find((e) => e.action === "incident.extracted")?.actor;
  const isCreator = !!creator && creator.toLowerCase() === session.email.toLowerCase();
  const [comments, setComments] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [pending, setPending] = useState<null | { name: string; decision: "approve" | "reject" }>(null);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const [message, setMessage] = useState<{ tone: "ok" | "bad" | "warn"; text: string } | null>(null);

  function ask(m: Measurement, decision: "approve" | "reject") {
    const text = (comments[m.name] ?? "").trim();
    if (text.length < 10 || text.length > 500) {
      setErrors({ ...errors, [m.name]: "Write a justification of 10 to 500 characters (for example what source you checked); it is recorded in the audit trail." });
      return;
    }
    setErrors({ ...errors, [m.name]: "" });
    setPending({ name: m.name, decision });
  }

  async function submit() {
    if (!pending || inFlight.current) return;
    const m = measurements.find((x) => x.name === pending.name);
    if (!m || !guardable(m)) return setPending(null);
    inFlight.current = true;
    setBusy(true);
    setMessage(null);
    try {
      const updated = await post<Incident>(`/incidents/${incident.id}/measurements/${m.name}/verify`, {
        decision: pending.decision, comment: (comments[m.name] ?? "").trim(), expected_trust_status: m.trust_status,
      });
      const v = updated.measurements?.find((x) => x.name === m.name)?.verification;
      setMessage({ tone: "ok", text: pending.decision === "approve"
        ? `Measurement verified. The server recalculated the incident priority${v ? `: ${v.priority_before} → ${v.priority_after}` : ""}.`
        : "Measurement rejected. It stays excluded from the priority calculation." });
      setComments({ ...comments, [m.name]: "" });
      onChanged();
    } catch (err) {
      const d = describeError(err);
      setMessage({ tone: "bad", text: d.text });
      if (d.refresh) onChanged();
    } finally {
      inFlight.current = false;
      setBusy(false);
      setPending(null);
    }
  }

  return (
    <section aria-labelledby="meas-h">
      <h4 id="meas-h">Numeric measurements</h4>
      <p className="muted small">A number in free text, or one proposed by the model, is only a candidate. Priority uses a number only after a person other than the incident&apos;s creator verifies it against its source. The current priority <PriorityBadge priority={incident.priority} /> is calculated by the server.</p>
      {incident.review_urgency === "urgent" && <p><Badge tone="bad" title="A flag asking a person to look soon. It is not a verified numeric priority.">Urgent review requested</Badge> <span className="muted small">This is a flag, not a verified priority.</span></p>}
      {message && <Notice tone={message.tone} onDismiss={() => setMessage(null)}>{message.text}</Notice>}
      {measurements.length === 0 && <p className="muted">No numeric measurements were recorded for this incident.</p>}
      {measurements.map((m) => {
        const prov = m.provenance ?? {};
        const fromSubmission = prov.source_type === "structured_observation";
        const err = errors[m.name];
        return (
          <article key={m.name} className="callout" aria-label={`Measurement ${m.name}`} data-measurement={m.name} data-trust={m.trust_status ?? ""}>
            <p className="row tight"><strong>{m.measurement_type ?? m.name}</strong> {trustBadge(m)}
              {m.evidence_class && <Badge tone="neutral" title="Evidence class assigned by the server">class {m.evidence_class}</Badge>}
              <Badge tone={m.eligible_for_numeric_priority ? "ok" : "neutral"}>{m.eligible_for_numeric_priority ? "Used for priority" : "Not used for priority"}</Badge></p>
            <dl className="kv compact">
              <div><dt>Candidate value</dt><dd>{fmtValue(m)}{m.original_value && m.original_value !== String(m.candidate_value) ? ` (reported as “${m.original_value}${m.original_unit ? ` ${m.original_unit}` : ""}”)` : ""}</dd></div>
              <div><dt>Asset</dt><dd>{m.asset_id ?? incident.asset_id}</dd></div>
              <div><dt>Evidence source</dt><dd>{fromSubmission ? `Structured observation submitted by ${prov.client_source_label ? `“${prov.client_source_label}”` : "an authenticated user"}` : prov.source_type === "simulation_fixture" ? `Signed simulation fixture${prov.simulation_source_id ? ` (${prov.simulation_source_id})` : ""}, labelled SIMULATED` : prov.source_type === "llm_proposal" ? "Proposed by the language model; the report does not support it" : "Found in the report text"}</dd></div>
              <div><dt>Source availability</dt><dd>{prov.source_available === false ? <span className="warn">Source not available{prov.source_missing_reason ? `: ${prov.source_missing_reason}` : ""}. Nothing to check this reading against; do not approve without another source.</span> : prov.evidence_span ? <>Reported text: <q>{prov.evidence_span}</q></> : m.source_text ? <>Reported text: <q>{m.source_text}</q></> : "Source recorded"}</dd></div>
              {m.observation_timestamp && <div><dt>Observed at</dt><dd>{m.observation_timestamp}</dd></div>}
              {m.reason && <div><dt>Review reason</dt><dd>{m.reason}</dd></div>}
              {isPending(m) && m.potentially_critical && m.implied_priority && <div><dt>Server hint</dt><dd>If verified, the rules would imply {m.implied_priority}. This is an estimate, not the incident&apos;s priority.</dd></div>}
            </dl>
            {m.verification && (
              <p className="small" aria-label={`Decision on ${m.name}`}>Decision: <strong>{m.verification.decision === "approve" ? "approved" : "rejected"}</strong> ({m.verification.transition}) on {m.verification.reviewed_at}. Priority {m.verification.priority_before} → {m.verification.priority_after} (rule: {m.verification.applied_rule}). Justification: “{m.verification.comment}”.
                {m.verification.audit_event_id != null ? <> Audit event <code>#{m.verification.audit_event_id}</code> (see History).</> : <> The decision is recorded in the audit history below.</>}</p>
            )}
            {isPending(m) && (
              !canReview ? <p className="muted small">Only supervisors and tenant administrators can verify measurements.</p>
                : isCreator ? <p className="muted small">You created this incident, so a different reviewer must verify its measurements.</p>
                : !guardable(m) ? <p className="muted small">This measurement is in a state that cannot be decided from here.</p>
                : (
                  <div>
                    <Field label={`Justification for ${m.measurement_type ?? m.name} (recorded in the audit trail)`} error={err} hint="Say what you checked, for example the maintenance printout or the gauge reading.">
                      {(p) => <textarea {...p} rows={2} maxLength={500} value={comments[m.name] ?? ""} onChange={(e) => setComments({ ...comments, [m.name]: e.target.value })} />}
                    </Field>
                    <button disabled={busy} onClick={() => ask(m, "approve")}>Verify measurement…</button>
                    <button className="danger" disabled={busy} onClick={() => ask(m, "reject")}>Reject measurement…</button>
                  </div>
                )
            )}
          </article>
        );
      })}
      <ConfirmDialog open={pending?.decision === "approve"} title="Verify this measurement?" confirmLabel="Verify measurement" busy={busy} onConfirm={() => void submit()} onCancel={() => setPending(null)}>
        <p>You are recording that you checked this reading against its source. The server will recalculate the incident priority; it never lowers an existing priority. You cannot undo this.</p>
        <blockquote>{pending ? comments[pending.name] : ""}</blockquote>
      </ConfirmDialog>
      <ConfirmDialog open={pending?.decision === "reject"} tone="danger" title="Reject this measurement?" confirmLabel="Reject measurement" busy={busy} onConfirm={() => void submit()} onCancel={() => setPending(null)}>
        <p>The reading stays excluded from the priority calculation. You cannot undo this.</p>
        <blockquote>{pending ? comments[pending.name] : ""}</blockquote>
      </ConfirmDialog>
    </section>
  );
}
