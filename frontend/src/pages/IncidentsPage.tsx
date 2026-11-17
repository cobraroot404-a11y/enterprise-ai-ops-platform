import { useRef, useState } from "react";
import type { FormEvent } from "react";
import ConfirmDialog from "../components/ConfirmDialog";
import MeasurementPanel from "../components/MeasurementPanel";
import ObservationForm, { toPayload, validateRow } from "../components/ObservationForm";
import type { ObservationRow } from "../components/ObservationForm";
import { CitationList, PriorityBadge, ProvenanceTag, ReviewBadge, Timeline } from "../components/provenance";
import { Badge, Card, Field, fmtTime, Notice, PageHeader, Pager, SortHeader, Status } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { useDebounced } from "../hooks/useDebounced";
import { hashParam } from "../hooks/useRoute";
import { usePagedList } from "../hooks/usePagedList";
import { assetLabel, useTenantProfile } from "../hooks/useTenantProfile";
import { api, post } from "../services/api";
import { can } from "../services/rbac";
import type { Incident, IncidentHistory, Session } from "../types";

export default function IncidentsPage({ session }: { session: Session }) {
  const profile = useTenantProfile();
  const label = assetLabel(profile.data);
  const [report, setReport] = useState("");
  const [reportError, setReportError] = useState<string | null>(null);
  const [rows, setRows] = useState<ObservationRow[]>([]);
  const [rowErrors, setRowErrors] = useState<Record<number, Record<string, string>>>({});
  const [locale, setLocale] = useState("");
  const submitting = useRef(false);
  const [search, setSearch] = useState("");
  const [review, setReview] = useState(hashParam("review") ?? "");
  const [priority, setPriority] = useState("");
  const q = useDebounced(search);
  const [reload, setReload] = useState(0);
  const list = usePagedList<Incident>("/incidents", { q, review_status: review, priority }, { defaultSort: "created_at", defaultOrder: "desc", refreshKey: reload });
  const [selectedId, setSelectedId] = useState<string | null>(hashParam("id"));
  const detail = useAsync(() => (selectedId ? api<Incident>(`/incidents/${selectedId}`) : Promise.resolve(null)), [selectedId, reload]);
  const history = useAsync(() => (selectedId ? api<IncidentHistory>(`/incidents/${selectedId}/history`) : Promise.resolve(null)), [selectedId, reload]);
  const [comment, setComment] = useState("");
  const [commentError, setCommentError] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<null | "accept" | "reject" | "draft">(null);
  const [message, setMessage] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const canWrite = can(session.role, "incidents:write");
  const canReview = can(session.role, "incidents:review");
  const canDraft = can(session.role, "tickets:write");
  const inc = detail.data;

  const select = (id: string) => { setSelectedId(id); setComment(""); setCommentError(null); };

  async function extract(e: FormEvent) {
    e.preventDefault();
    if (report.trim().length < 10) return setReportError("Describe the fault in at least 10 characters.");
    setReportError(null);
    const errs: Record<number, Record<string, string>> = {};
    for (const r of rows) { const e = validateRow(r); if (Object.keys(e).length) errs[r.key] = e; }
    setRowErrors(errs);
    if (Object.keys(errs).length) return;
    if (submitting.current) return;
    submitting.current = true;
    setBusy(true);
    setMessage(null);
    try {
      const created = await post<Incident>("/incidents/extract", {
        report_text: report.trim(),
        ...(rows.length ? { observations: rows.map(toPayload) } : {}),
        ...(locale ? { numeric_locale: locale } : {}),
      });
      setReport("");
      setRows([]);
      select(created.id);
      setReload((n) => n + 1);
      setMessage({ tone: "ok", text: created.review_status === "needs_review" ? "Incident created. It is blocked until a supervisor reviews it." : "Incident created from verified evidence." });
    } catch (err) {
      setMessage({ tone: "bad", text: err instanceof Error ? err.message : "Extraction failed" });
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  async function run(action: "accept" | "reject" | "draft" | "verify") {
    if (!inc) return;
    if ((action === "accept" || action === "reject") && comment.trim().length < 5) {
      setPendingAction(null);
      return setCommentError("Write a justification of at least 5 characters; it is recorded in the audit trail.");
    }
    setBusy(true);
    setMessage(null);
    try {
      if (action === "verify") {
        const res = await post<Incident>(`/incidents/${inc.id}/verify-asset`);
        setMessage(res.asset_verified ? { tone: "ok", text: `${label} is now verified against the register.` } : { tone: "bad", text: `${label} is still not in the authoritative register. Register it by ingesting an updated register, then verify again.` });
      } else if (action === "draft") {
        const t = await post<{ id: string }>("/tickets", { incident_id: inc.id });
        setMessage({ tone: "ok", text: "Ticket draft created. Open Support Tickets to edit and request approval." });
        window.location.hash = `#/tickets?id=${t.id}`;
      } else {
        await post(`/incidents/${inc.id}/review`, { decision: action, comment: comment.trim() });
        setMessage({ tone: "ok", text: action === "accept" ? "Incident accepted by human review. A ticket can now be drafted; it still needs its own approval." : "Incident rejected. It can never become a ticket." });
        setComment("");
      }
      setReload((n) => n + 1);
    } catch (err) {
      setMessage({ tone: "bad", text: err instanceof Error ? err.message : "Action failed" });
    } finally {
      setBusy(false);
      setPendingAction(null);
    }
  }

  const data = list.state.data;
  return (
    <section aria-labelledby="inc-h">
      <PageHeader title="Incident Explorer" intro={`Fault reports become structured incidents. A ${label} must be in the register and the guidance must be backed by verified evidence, or a person has to review the incident first.`} />
      {canWrite && (
        <Card title="Report a fault" id="inc-new">
          <form onSubmit={extract} aria-label="Report a fault" noValidate>
            <Field label="Fault report" error={reportError}>
              {(p) => <textarea {...p} rows={3} value={report} onChange={(e) => setReport(e.target.value)} maxLength={4000}
                placeholder={profile.data?.profile ? `Describe the fault and include the ${label} ID` : "Pump P-101 shows abnormal vibration at the drive end, measured at 8.4 mm/s, with a grinding noise."} />}
            </Field>
            <Field label="Number format used in the report text (optional)" hint="Only affects numbers written in the text, such as 8,4 (German) or 8.4 (English).">
              {(p) => <select {...p} value={locale} disabled={busy} onChange={(e) => setLocale(e.target.value)}><option value="">Detect automatically</option><option value="en">English (8.4)</option><option value="de">German (8,4)</option></select>}
            </Field>
            <ObservationForm rows={rows} errors={rowErrors} disabled={busy} onChange={setRows} />
            <button type="submit" disabled={busy}>{busy ? "Analysing…" : "Analyse report"}</button>
          </form>
        </Card>
      )}
      {message && <Notice tone={message.tone} onDismiss={() => setMessage(null)}>{message.text}</Notice>}

      <Card title="Incidents" id="inc-list">
        <div className="row" role="search" aria-label="Filter incidents">
          <Field label="Search">{(p) => <input {...p} type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder={`${label} id, category or text`} />}</Field>
          <Field label="Review status">
            {(p) => (
              <select {...p} value={review} onChange={(e) => setReview(e.target.value)}>
                <option value="">All</option><option value="needs_review">Blocked · needs review</option><option value="pending_review">Evidence verified</option><option value="accepted">Accepted by reviewer</option><option value="rejected">Rejected</option>
              </select>
            )}
          </Field>
          <Field label="Priority">{(p) => <select {...p} value={priority} onChange={(e) => setPriority(e.target.value)}><option value="">All</option>{["P1", "P2", "P3", "P4"].map((x) => <option key={x}>{x}</option>)}</select>}</Field>
        </div>
        <Status state={list.state} label="incidents" empty={data && data.items.length === 0 ? (q || review || priority ? "No incidents match the filters." : "No incidents yet.") : undefined} />
        {data && data.items.length > 0 && (
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
            <table>
              <caption className="sr-only">Incidents</caption>
              <thead>
                <tr>
                  <SortHeader column="asset_id" label={label} sort={list.sort} order={list.order} onSort={list.toggleSort} />
                  <th scope="col">Category</th>
                  <SortHeader column="priority" label="Priority" sort={list.sort} order={list.order} onSort={list.toggleSort} />
                  <SortHeader column="review_status" label="Status" sort={list.sort} order={list.order} onSort={list.toggleSort} />
                  <SortHeader column="created_at" label="Created" sort={list.sort} order={list.order} onSort={list.toggleSort} />
                </tr>
              </thead>
              <tbody>
                {data.items.map((i) => (
                  <tr key={i.id} className={selectedId === i.id ? "selected" : ""}>
                    <td><button className="linklike" aria-pressed={selectedId === i.id} onClick={() => select(i.id)}>{i.asset_id}</button></td>
                    <td>{i.category.replace(/_/g, " ")}</td><td><PriorityBadge priority={i.priority} /></td>
                    <td><ReviewBadge status={i.review_status} /></td><td>{fmtTime(i.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && <Pager total={data.total} limit={data.limit} offset={list.offset} onChange={list.setOffset} />}
      </Card>

      {selectedId && (
        <article className="card" aria-labelledby="inc-detail-h">
          <Status state={detail} label="incident" />
          {inc && (
            <>
              <h3 id="inc-detail-h">{inc.asset_id} · {inc.category.replace(/_/g, " ")}</h3>
              <p className="row tight"><PriorityBadge priority={inc.priority} /> <ReviewBadge status={inc.review_status} />
                {inc.asset_verified ? <Badge tone="ok" title="Found in the tenant's authoritative register">{label} verified in register</Badge> : <Badge tone="bad" title="Not found in the authoritative register">{label} NOT in register</Badge>}</p>

              <h4>Reported</h4>
              <blockquote>{inc.report_text}</blockquote>

              <h4>Extracted fields <ProvenanceTag kind="ai" /></h4>
              <p className="muted small">Produced by {inc.extraction_backend}. The asset id was checked against the report; priority comes from deterministic rules, not the model.</p>
              <ul>{inc.symptoms.map((s) => <li key={s}>{s}</li>)}</ul>

              <h4>Recommended action {inc.citations.length ? <ProvenanceTag kind="ai" /> : <Badge tone="warn">No verified evidence</Badge>}</h4>
              <p>{inc.recommended_action}</p>
              <CitationList citations={inc.citations} empty="No verified citations support this recommendation." />

              {inc.related_incidents.length > 0 && (
                <>
                  <h4>Related past incidents <ProvenanceTag kind="evidence" /></h4>
                  <ul>{inc.related_incidents.map((r) => <li key={r.record_id ?? r.summary}><strong>{r.record_id ?? "record"}</strong>{r.same_asset ? " (same asset)" : ""} <span className="muted">{r.filename}</span><div className="small">{r.summary}</div></li>)}</ul>
                </>
              )}
              {inc.notes.length > 0 && (<><h4>Notes</h4><ul className="small">{inc.notes.map((n, i) => <li key={i}>{n}</li>)}</ul></>)}

              <MeasurementPanel incident={inc} events={history.data?.events ?? []} session={session} onChanged={() => setReload((n) => n + 1)} />

              <h4>Human review</h4>
              {inc.review_status === "needs_review" && (
                <div className="callout callout-bad" role="group" aria-label="Review required">
                  <p><strong>This incident is blocked.</strong> No ticket can be drafted until a supervisor reviews it. Accepting does not verify unsupported claims or an unregistered {label}; the {label} must also be in the register before anything can be sent outside.</p>
                  {canReview ? (
                    <>
                      <Field label="Justification (recorded in the audit trail)" error={commentError}>
                        {(p) => <textarea {...p} rows={2} value={comment} onChange={(e) => setComment(e.target.value)} />}
                      </Field>
                      <button onClick={() => (comment.trim().length < 5 ? setCommentError("Write a justification of at least 5 characters; it is recorded in the audit trail.") : setPendingAction("accept"))}>Accept for ticketing…</button>
                      <button className="danger" onClick={() => (comment.trim().length < 5 ? setCommentError("Write a justification of at least 5 characters; it is recorded in the audit trail.") : setPendingAction("reject"))}>Reject…</button>
                    </>
                  ) : <p className="muted small">Only supervisors and tenant administrators can review.</p>}
                </div>
              )}
              {inc.review_status === "accepted" && <p>Accepted by human review. The review justification is in the notes and the history below.</p>}
              {inc.review_status === "rejected" && <p className="error">Rejected. This incident can never become a ticket.</p>}
              {inc.review_status === "pending_review" && <p>Evidence is verified and the {label} is registered, so no review is required before drafting a ticket.</p>}

              <div className="row">
                {!inc.asset_verified && inc.review_status !== "rejected" && canReview && (
                  <button className="secondary" onClick={() => void run("verify")} disabled={busy}>Re-check {label} against register</button>
                )}
                {["pending_review", "accepted"].includes(inc.review_status) && canDraft && (
                  <button onClick={() => setPendingAction("draft")} disabled={busy}>Create ticket draft…</button>
                )}
              </div>
              {inc.review_status === "accepted" && !inc.asset_verified && (
                <p className="warn small">The {label} is not in the register: a draft can be created, but the ticket cannot be approved or sent until the {label} is registered and re-verified.</p>
              )}

              {history.data && history.data.tickets.length > 0 && (
                <p>Tickets: {history.data.tickets.map((t) => <a key={t.id} href={`#/tickets?id=${t.id}`} className="chip">{t.state}{t.external_ticket_id ? ` · ${t.external_ticket_id}` : ""}</a>)}</p>
              )}
              <h4>History</h4>
              <Status state={history} label="history" />
              {history.data && <Timeline events={history.data.events} />}
            </>
          )}
        </article>
      )}

      <ConfirmDialog open={pendingAction === "accept"} title="Accept this incident?" confirmLabel="Accept incident" busy={busy} onConfirm={() => void run("accept")} onCancel={() => setPendingAction(null)}>
        <p>You are recording a human decision that this incident may proceed to a ticket draft. It does not make unsupported AI statements true, and it is separate from the later approval to send the ticket to the external system.</p>
        <blockquote>{comment}</blockquote>
      </ConfirmDialog>
      <ConfirmDialog open={pendingAction === "reject"} tone="danger" title="Reject this incident?" confirmLabel="Reject incident" busy={busy} onConfirm={() => void run("reject")} onCancel={() => setPendingAction(null)}>
        <p>A rejected incident can never become a ticket. This cannot be undone.</p>
        <blockquote>{comment}</blockquote>
      </ConfirmDialog>
      <ConfirmDialog open={pendingAction === "draft"} title="Create a ticket draft?" confirmLabel="Create draft" busy={busy} onConfirm={() => void run("draft")} onCancel={() => setPendingAction(null)}>
        <p>A draft is created for editing. Nothing is sent outside the platform until the ticket is approved by a second person.</p>
      </ConfirmDialog>
    </section>
  );
}
