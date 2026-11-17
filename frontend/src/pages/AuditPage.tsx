import { useState } from "react";
import { JsonView } from "../components/provenance";
import { Card, Field, fmtTime, PageHeader, Pager, Status } from "../components/ui";
import { useDebounced } from "../hooks/useDebounced";
import { usePagedList } from "../hooks/usePagedList";
import type { AuditRow } from "../types";

const ENTITY_TYPES = ["ticket", "incident", "document", "user", "connector", "tenant_profile", "query", "tenant"];

export default function AuditPage() {
  const [search, setSearch] = useState("");
  const [entityType, setEntityType] = useState("");
  const [entityId, setEntityId] = useState("");
  const q = useDebounced(search);
  const list = usePagedList<AuditRow>("/audit", { q, entity_type: entityType, entity_id: entityId.trim() }, { pageSize: 20 });
  const [open, setOpen] = useState<number | null>(null);
  const data = list.state.data;
  return (
    <section aria-labelledby="aud-h">
      <PageHeader title="Audit Logs" intro="An append-only record of who did what and when. Entries cannot be edited or deleted, even by administrators." />
      <Card id="aud-list">
        <div className="row" role="search" aria-label="Filter audit log">
          <Field label="Action contains">{(p) => <input {...p} type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="e.g. approval" />}</Field>
          <Field label="Entity type">{(p) => <select {...p} value={entityType} onChange={(e) => setEntityType(e.target.value)}><option value="">All</option>{ENTITY_TYPES.map((t) => <option key={t}>{t}</option>)}</select>}</Field>
          <Field label="Entity id">{(p) => <input {...p} value={entityId} onChange={(e) => setEntityId(e.target.value)} placeholder="ticket or incident id" />}</Field>
        </div>
        <Status state={list.state} label="audit events" empty={data && data.items.length === 0 ? "No audit events match." : undefined} />
        {data && data.items.length > 0 && (
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
            <table>
              <caption className="sr-only">Audit events</caption>
              <thead><tr><th scope="col">When</th><th scope="col">Action</th><th scope="col">Actor</th><th scope="col">Entity</th><th scope="col">Details</th></tr></thead>
              <tbody>
                {data.items.map((a) => (
                  <tr key={a.id}>
                    <td>{fmtTime(a.created_at)}</td><td><code>{a.action}</code></td><td>{a.actor}</td>
                    <td>{a.entity_type}{a.entity_id ? <> <button className="linklike small" onClick={() => setEntityId(a.entity_id ?? "")} title="Filter to this entity">{a.entity_id.slice(0, 8)}…</button></> : null}</td>
                    <td>
                      <button className="linklike small" aria-expanded={open === a.id} onClick={() => setOpen(open === a.id ? null : a.id)}>{open === a.id ? "Hide" : "Show"}</button>
                      {open === a.id && (<><JsonView value={a.details} />{a.correlation_id && <p className="small muted">Correlation id <code>{a.correlation_id}</code></p>}</>)}
                    </td>
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
