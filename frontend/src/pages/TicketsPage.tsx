import { useState } from "react";
import type { FormEvent } from "react";
import ConfirmDialog from "../components/ConfirmDialog";
import { PriorityBadge, Timeline, TicketStateBadge } from "../components/provenance";
import { Card, Field, fmtTime, KeyValues, Notice, PageHeader, Pager, SortHeader, Status } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { useDebounced } from "../hooks/useDebounced";
import { hashParam } from "../hooks/useRoute";
import { usePagedList } from "../hooks/usePagedList";
import { usePoll } from "../hooks/usePoll";
import { api, patch, post } from "../services/api";
import { can } from "../services/rbac";
import type { Session, Ticket, TicketHistory } from "../types";

const STATES = ["DRAFT", "PENDING_APPROVAL", "APPROVED", "REJECTED", "SUBMITTING", "SUBMITTED", "FAILED", "RETRY_PENDING", "CANCELLED"];
type Action = "request" | "cancel" | "retry";

export default function TicketsPage({ session }: { session: Session }) {
  const [state, setState] = useState(hashParam("state") ?? "");
  const [priority, setPriority] = useState("");
  const [search, setSearch] = useState("");
  const q = useDebounced(search);
  const [reload, setReload] = useState(0);
  const list = usePagedList<Ticket>("/tickets", { state, priority, q }, { defaultSort: "updated_at", defaultOrder: "desc", refreshKey: reload });
  const [selectedId, setSelectedId] = useState<string | null>(hashParam("id"));
  const detail = useAsync(() => (selectedId ? api<Ticket>(`/tickets/${selectedId}`) : Promise.resolve(null)), [selectedId, reload]);
  const history = useAsync(() => (selectedId ? api<TicketHistory>(`/tickets/${selectedId}/history`) : Promise.resolve(null)), [selectedId, reload]);
  const [pending, setPending] = useState<Action | null>(null);
  const [message, setMessage] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const t = detail.data;
  // Approved tickets are sent by a background worker: keep the page honest by refreshing until the backend reports a final state.
  usePoll(!!t && ["APPROVED", "SUBMITTING", "RETRY_PENDING"].includes(t.state), 2500, () => setReload((n) => n + 1));
  const canWrite = can(session.role, "tickets:write");
  const canRetry = can(session.role, "tickets:retry");


  async function run(action: Action) {
    if (!t) return;
    setBusy(true);
    try {
      const path = action === "request" ? "request-approval" : action;
      await post(`/tickets/${t.id}/${path}`);
      setMessage({
        tone: "ok",
        text: action === "request" ? "Approval requested. A different person must approve before anything is sent." : action === "retry" ? "Retry queued. The worker will re-check the approval and the release controls before sending." : "Ticket cancelled.",
      });
      setReload((n) => n + 1);
    } catch (err) {
      setMessage({ tone: "bad", text: err instanceof Error ? err.message : "Action failed" });
    } finally {
      setBusy(false);
      setPending(null);
    }
  }

  const data = list.state.data;
  return (
    <section aria-labelledby="tix-h">
      <PageHeader title="Support Tickets" intro="Tickets are drafted from reviewed incidents and sent to the customer's external system only after a second person approves them." />
      {message && <Notice tone={message.tone} onDismiss={() => setMessage(null)}>{message.text}</Notice>}
      <Card title="Tickets" id="tix-list">
        <div className="row" role="search" aria-label="Filter tickets">
          <Field label="Search">{(p) => <input {...p} type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="title or external id" />}</Field>
          <Field label="State">{(p) => <select {...p} value={state} onChange={(e) => setState(e.target.value)}><option value="">All states</option>{STATES.map((s) => <option key={s}>{s}</option>)}</select>}</Field>
          <Field label="Priority">{(p) => <select {...p} value={priority} onChange={(e) => setPriority(e.target.value)}><option value="">All</option>{["P1", "P2", "P3", "P4"].map((x) => <option key={x}>{x}</option>)}</select>}</Field>
        </div>
        <Status state={list.state} label="tickets" empty={data && data.items.length === 0 ? (q || state || priority ? "No tickets match the filters." : "No tickets yet. Draft one from a reviewed incident.") : undefined} />
        {data && data.items.length > 0 && (
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
            <table>
              <caption className="sr-only">Tickets</caption>
              <thead>
                <tr>
                  <th scope="col">Title</th>
                  <SortHeader column="priority" label="Priority" sort={list.sort} order={list.order} onSort={list.toggleSort} />
                  <SortHeader column="state" label="State" sort={list.sort} order={list.order} onSort={list.toggleSort} />
                  <th scope="col">External id</th><th scope="col">Attempts</th>
                  <SortHeader column="updated_at" label="Updated" sort={list.sort} order={list.order} onSort={list.toggleSort} />
                </tr>
              </thead>
              <tbody>
                {data.items.map((x) => (
                  <tr key={x.id} className={selectedId === x.id ? "selected" : ""}>
                    <td><button className="linklike" aria-pressed={selectedId === x.id} onClick={() => setSelectedId(x.id)}>{x.title}</button></td>
                    <td><PriorityBadge priority={x.priority} /></td><td><TicketStateBadge state={x.state} externalId={x.external_ticket_id} /></td>
                    <td>{x.external_ticket_id ? <code>{x.external_ticket_id}</code> : "–"}</td><td>{x.attempts}</td><td>{fmtTime(x.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && <Pager total={data.total} limit={data.limit} offset={list.offset} onChange={list.setOffset} />}
      </Card>

      {selectedId && (
        <article className="card" aria-labelledby="tix-detail-h">
          <Status state={detail} label="ticket" />
          {t && (
            <>
              <h3 id="tix-detail-h">{t.title}</h3>
              <p className="row tight"><TicketStateBadge state={t.state} externalId={t.external_ticket_id} /> <PriorityBadge priority={t.priority} /></p>
              {t.state === "SUBMITTED" && t.external_ticket_id && <Notice tone="ok">Confirmed by the external system: <code>{t.external_ticket_id}</code> (submitted {fmtTime(t.submitted_at)}).</Notice>}
              {t.state === "APPROVED" && <Notice tone="warn">Approved, but not yet sent. The background worker submits approved tickets; this page does not claim success until the external system confirms.</Notice>}
              {(t.state === "SUBMITTING" || t.state === "RETRY_PENDING") && <Notice tone="warn">Submission is in progress or scheduled for retry ({t.attempts} attempt(s) so far).</Notice>}
              {t.state === "FAILED" && <Notice tone="bad">Submission failed after {t.attempts} attempt(s): {t.last_error ?? "no error recorded"}</Notice>}
              {t.last_error && t.state !== "FAILED" && <p className="warn small">Last error: {t.last_error}</p>}
              <KeyValues rows={[["Created", fmtTime(t.created_at)], ["Updated", fmtTime(t.updated_at)], ["Incident", <a key="i" href={`#/incidents?id=${t.incident_id}`}>open incident</a>]]} />

              {t.state === "DRAFT" && canWrite ? (
                <DraftForm key={`${t.id}-${t.updated_at}`} ticket={t} onSaved={() => { setMessage({ tone: "ok", text: "Draft saved." }); setReload((n) => n + 1); }}
                  onError={(text) => setMessage({ tone: "bad", text })} />
              ) : (
                <>
                  <h4>Content sent to the external system</h4>
                  <pre>{t.description}</pre>
                </>
              )}

              <div className="row">
                {t.state === "DRAFT" && canWrite && <button onClick={() => setPending("request")} disabled={busy}>Request approval…</button>}
                {["DRAFT", "PENDING_APPROVAL", "APPROVED"].includes(t.state) && canWrite && <button className="danger" onClick={() => setPending("cancel")} disabled={busy}>Cancel ticket…</button>}
                {t.state === "FAILED" && canRetry && <button onClick={() => setPending("retry")} disabled={busy}>Retry submission…</button>}
                {t.state === "PENDING_APPROVAL" && <a href="#/approvals" className="button-link">Go to the Approval Queue</a>}
              </div>

              <h4>Approval decisions</h4>
              {history.data && history.data.approvals.length === 0 && <p className="muted">No approval decision yet.</p>}
              {history.data && history.data.approvals.map((a, i) => (
                <p key={i}><strong>{a.decision}</strong> · {fmtTime(a.decided_at)}{a.comment ? ` · “${a.comment}”` : ""}</p>
              ))}
              <h4>History</h4>
              <Status state={history} label="history" />
              {history.data && <Timeline events={history.data.events} />}
            </>
          )}
        </article>
      )}

      <ConfirmDialog open={pending === "request"} title="Request approval?" confirmLabel="Request approval" busy={busy} onConfirm={() => void run("request")} onCancel={() => setPending(null)}>
        <p>The draft can no longer be edited and is sent to approvers. You cannot approve your own ticket.</p>
      </ConfirmDialog>
      <ConfirmDialog open={pending === "cancel"} tone="danger" title="Cancel this ticket?" confirmLabel="Cancel ticket" busy={busy} onConfirm={() => void run("cancel")} onCancel={() => setPending(null)}>
        <p>A cancelled ticket is never sent and cannot be reopened.</p>
      </ConfirmDialog>
      <ConfirmDialog open={pending === "retry"} title="Retry the submission?" confirmLabel="Retry" busy={busy} onConfirm={() => void run("retry")} onCancel={() => setPending(null)}>
        <p>The original approval is required again and the release controls are re-checked before anything is sent. A retry never creates a second external ticket.</p>
      </ConfirmDialog>
    </section>
  );
}

function DraftForm({ ticket, onSaved, onError }: { ticket: Ticket; onSaved: () => void; onError: (text: string) => void }) {
  const [edit, setEdit] = useState({ title: ticket.title, description: ticket.description, priority: ticket.priority });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  async function save(e: FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (edit.title.trim().length < 3) errs.title = "Title needs at least 3 characters.";
    if (edit.description.trim().length < 3) errs.description = "Description needs at least 3 characters.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    try {
      await patch(`/tickets/${ticket.id}`, { title: edit.title.trim(), description: edit.description, priority: edit.priority });
      onSaved();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} aria-label="Edit draft" noValidate>
      <Field label="Title" error={errors.title}>{(p) => <input {...p} value={edit.title} maxLength={200} onChange={(e) => setEdit({ ...edit, title: e.target.value })} />}</Field>
      <Field label="Priority">{(p) => <select {...p} value={edit.priority} onChange={(e) => setEdit({ ...edit, priority: e.target.value })}>{["P1", "P2", "P3", "P4"].map((x) => <option key={x}>{x}</option>)}</select>}</Field>
      <Field label="Description" error={errors.description}>{(p) => <textarea {...p} rows={10} className="mono" value={edit.description} maxLength={8000} onChange={(e) => setEdit({ ...edit, description: e.target.value })} />}</Field>
      <button type="submit" disabled={busy}>Save draft</button>
    </form>
  );
}
