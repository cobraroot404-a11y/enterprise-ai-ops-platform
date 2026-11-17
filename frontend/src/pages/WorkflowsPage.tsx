import { useState } from "react";
import { Badge, Card, Field, fmtTime, PageHeader, Pager, Status } from "../components/ui";
import { usePagedList } from "../hooks/usePagedList";
import { usePoll } from "../hooks/usePoll";
import type { WorkflowEvent } from "../types";

const STATUS_TONE: Record<string, string> = { pending: "warn", processing: "warn", done: "ok", dead: "bad" };
const STATUS_TEXT: Record<string, string> = {
  pending: "Queued",
  processing: "Being sent",
  done: "Completed",
  dead: "Dead-lettered (needs attention)",
};

export default function WorkflowsPage() {
  const [status, setStatus] = useState("");
  const [ticket, setTicket] = useState("");
  const idOk = ticket === "" || /^[0-9a-f-]{36}$/i.test(ticket);
  const [reload, setReload] = useState(0);
  const list = usePagedList<WorkflowEvent>("/workflows", { status, ticket_id: idOk ? ticket : "" }, { pageSize: 20, refreshKey: reload });
  const data = list.state.data;
  usePoll(!!data?.items.some((e) => e.status === "pending" || e.status === "processing"), 2500, () => setReload((n) => n + 1));
  return (
    <section aria-labelledby="wf-h">
      <PageHeader
        title="Workflow History"
        intro="The background submission queue: each approved ticket is sent by a worker with retries, backoff and a dead-letter state. Events are never edited."
        actions={<button className="secondary" onClick={() => setReload((n) => n + 1)}>Refresh</button>}
      />
      <Card id="wf-list" title="Submission events">
        <div className="row" role="search" aria-label="Filter events">
          <Field label="Status">
            {(p) => (
              <select {...p} value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="">All</option>
                {Object.entries(STATUS_TEXT).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            )}
          </Field>
          <Field label="Ticket id" error={idOk ? null : "Enter a full ticket id (UUID)."}>
            {(p) => <input {...p} value={ticket} onChange={(e) => setTicket(e.target.value.trim())} placeholder="paste a ticket id" />}
          </Field>
        </div>
        <Status state={list.state} label="workflow events" empty={data && data.items.length === 0 ? (status || ticket ? "No events match the filters." : "No submissions have been queued yet.") : undefined} />
        {data && data.items.length > 0 && (
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
            <table>
              <caption className="sr-only">Workflow events</caption>
              <thead><tr><th scope="col">Event</th><th scope="col">Ticket</th><th scope="col">Status</th><th scope="col">Attempts</th><th scope="col">Last error</th><th scope="col">Queued</th><th scope="col">Finished</th></tr></thead>
              <tbody>
                {data.items.map((e) => (
                  <tr key={e.id}>
                    <td>#{e.id} <span className="muted small">{e.topic}</span></td>
                    <td><a href={`#/tickets?id=${e.ticket_id}`}>open ticket</a></td>
                    <td><Badge tone={STATUS_TONE[e.status] ?? "neutral"}>{STATUS_TEXT[e.status] ?? e.status}</Badge></td>
                    <td>{e.attempts}</td><td className="small">{e.last_error ?? "–"}</td><td>{fmtTime(e.created_at)}</td><td>{fmtTime(e.processed_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && <Pager total={data.total} limit={data.limit} offset={list.offset} onChange={list.setOffset} />}
      </Card>
    </section>
  );
}
