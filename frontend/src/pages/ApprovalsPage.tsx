import { useEffect, useRef, useState } from "react";
import ConfirmDialog from "../components/ConfirmDialog";
import { CitationList, PriorityBadge, ProvenanceTag, ReviewBadge } from "../components/provenance";
import { Badge, Card, Field, fmtTime, Notice, PageHeader, Pager, Status } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { usePagedList } from "../hooks/usePagedList";
import { api, post } from "../services/api";
import { can } from "../services/rbac";
import type { ApprovalRecord, Incident, Session, Ticket } from "../types";

export default function ApprovalsPage({ session }: { session: Session }) {
  const [tab, setTab] = useState<"pending" | "decided">("pending");
  const [reload, setReload] = useState(0);
  const pending = usePagedList<Ticket>("/approvals", { status: "pending" }, { pageSize: 10, refreshKey: reload });
  const decided = usePagedList<ApprovalRecord>("/approvals", { status: "decided" }, { pageSize: 15, refreshKey: reload });
  const canDecide = can(session.role, "approvals:decide");
  const [comments, setComments] = useState<Record<string, string>>({});
  const [confirm, setConfirm] = useState<{ ticket: Ticket; decision: "approved" | "rejected" } | null>(null);
  const [message, setMessage] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const pendingTab = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    // A successful decision removes its trigger. Focus the stable queue tab after the dialog closes.
    if (message?.tone === "ok") pendingTab.current?.focus();
  }, [message]);

  async function decide() {
    if (!confirm) return;
    setBusy(true);
    try {
      await post(`/approvals/${confirm.ticket.id}/decision`, { decision: confirm.decision, comment: comments[confirm.ticket.id]?.trim() || undefined });
      setMessage({
        tone: "ok",
        text: confirm.decision === "approved" ? "Approved. The ticket is queued for submission; its status will change to Submitted only when the external system confirms." : "Rejected. This ticket will never be submitted.",
      });
      setReload((n) => n + 1);
    } catch (err) {
      setMessage({ tone: "bad", text: err instanceof Error ? err.message : "Decision failed" });
    } finally {
      setBusy(false);
      setConfirm(null);
    }
  }

  return (
    <section aria-labelledby="apr-h">
      <PageHeader title="Approval Queue" intro="Nothing is sent to an external system without a recorded approval from someone other than the author." />
      {message && <Notice tone={message.tone} onDismiss={() => setMessage(null)}>{message.text}</Notice>}
      <div role="tablist" aria-label="Approval views" className="tabs">
        <button ref={pendingTab} role="tab" aria-selected={tab === "pending"} className={tab === "pending" ? "tab active" : "tab"} onClick={() => setTab("pending")}>Awaiting decision{pending.state.data ? ` (${pending.state.data.total})` : ""}</button>
        <button role="tab" aria-selected={tab === "decided"} className={tab === "decided" ? "tab active" : "tab"} onClick={() => setTab("decided")}>Decided</button>
      </div>
      {tab === "pending" && (
        <div role="tabpanel" aria-label="Awaiting decision">
          <Status state={pending.state} label="approvals" empty={pending.state.data && pending.state.data.items.length === 0 ? "Nothing is waiting for approval." : undefined} />
          {pending.state.data?.items.map((t) => (
            <PendingCard key={t.id} ticket={t} session={session} canDecide={canDecide} comment={comments[t.id] ?? ""}
              setComment={(v) => setComments({ ...comments, [t.id]: v })} onDecide={(d) => setConfirm({ ticket: t, decision: d })} />
          ))}
          {pending.state.data && <Pager total={pending.state.data.total} limit={pending.state.data.limit} offset={pending.offset} onChange={pending.setOffset} />}
        </div>
      )}
      {tab === "decided" && (
        <Card id="apr-decided" title="Recorded decisions">
          <Status state={decided.state} label="decisions" empty={decided.state.data && decided.state.data.items.length === 0 ? "No decisions recorded yet." : undefined} />
          {decided.state.data && decided.state.data.items.length > 0 && (
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
              <table>
                <thead><tr><th scope="col">Ticket</th><th scope="col">Decision</th><th scope="col">Comment</th><th scope="col">Decided</th></tr></thead>
                <tbody>
                  {decided.state.data.items.map((a, i) => (
                    <tr key={`${a.ticket_id}-${i}`}><td><a href={`#/tickets?id=${a.ticket_id}`}>open ticket</a></td><td><Badge tone={a.decision === "approved" ? "ok" : "bad"}>{a.decision}</Badge></td><td>{a.comment ?? "–"}</td><td>{fmtTime(a.decided_at)}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {decided.state.data && <Pager total={decided.state.data.total} limit={decided.state.data.limit} offset={decided.offset} onChange={decided.setOffset} />}
        </Card>
      )}

      <ConfirmDialog open={!!confirm} tone={confirm?.decision === "rejected" ? "danger" : "primary"} title={confirm?.decision === "approved" ? "Approve this ticket for submission?" : "Reject this ticket?"}
        confirmLabel={confirm?.decision === "approved" ? "Approve" : "Reject"} busy={busy} onConfirm={() => void decide()} onCancel={() => setConfirm(null)}>
        <p><strong>{confirm?.ticket.title}</strong></p>
        {confirm?.decision === "approved"
          ? <p>This authorizes the platform to create a ticket in the customer&apos;s external system. This decision is recorded and cannot be undone.</p>
          : <p>A rejected ticket is never submitted and cannot be reopened.</p>}
      </ConfirmDialog>
    </section>
  );
}

function PendingCard({ ticket, session, canDecide, comment, setComment, onDecide }: {
  ticket: Ticket; session: Session; canDecide: boolean; comment: string; setComment: (v: string) => void; onDecide: (d: "approved" | "rejected") => void;
}) {
  const incident = useAsync(() => api<Incident>(`/incidents/${ticket.incident_id}`), [ticket.incident_id]);
  const own = ticket.created_by === session.userId;
  const inc = incident.data;
  return (
    <article className="card" aria-label={`Approval request: ${ticket.title}`} data-ticket-id={ticket.id}>
      <h3>{ticket.title}</h3>
      <p className="row tight"><PriorityBadge priority={ticket.priority} /> <span className="muted small">requested {fmtTime(ticket.updated_at)}</span></p>
      <Status state={incident} label="incident context" />
      {inc && (
        <>
          <p className="row tight">
            <ReviewBadge status={inc.review_status} />
            {inc.asset_verified ? <Badge tone="ok">asset verified in register</Badge> : <Badge tone="bad">asset NOT in register · cannot be released</Badge>}
          </p>
          <h4>Recommended action <ProvenanceTag kind="ai" /></h4>
          <p>{inc.recommended_action}</p>
          <CitationList citations={inc.citations} empty="No verified evidence supports this recommendation." />
          {inc.notes.filter((n) => n.startsWith("Human review")).map((n, i) => <p key={i} className="small"><ProvenanceTag kind="human" /> {n}</p>)}
        </>
      )}
      <details>
        <summary>Exact content that will be sent</summary>
        <pre>{ticket.description}</pre>
      </details>
      {own && <Notice tone="warn">You created this ticket, so you cannot decide on it (separation of duties). Another approver must.</Notice>}
      {!canDecide && <p className="muted small">Your role cannot decide on approvals.</p>}
      {canDecide && !own && (
        <>
          <Field label="Comment (optional)">{(p) => <input {...p} value={comment} maxLength={1000} onChange={(e) => setComment(e.target.value)} />}</Field>
          <button onClick={() => onDecide("approved")}>Approve…</button>
          <button className="danger" onClick={() => onDecide("rejected")}>Reject…</button>
        </>
      )}
    </article>
  );
}
