import { useState } from "react";
import type { FormEvent } from "react";
import ConfirmDialog from "../components/ConfirmDialog";
import { IngestionActivityCard, WebhookEndpointsCard } from "../components/IntegrationPanels";
import { Badge, Card, Field, KeyValues, Notice, PageHeader, Status } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { api, post } from "../services/api";
import { can } from "../services/rbac";
import type { Connector, ConnectorHealth, IngestionJob, Metrics, Session } from "../types";

const KINDS = ["ticketing", "inventory", "crm", "fleet", "rest", "csv", "webhook"];

export default function DataSourcesPage({ session }: { session: Session }) {
  const isAdmin = can(session.role, "connectors:read");
  const connectors = useAsync(() => (isAdmin ? api<{ items: Connector[] }>("/connectors") : Promise.resolve(null)), [isAdmin]);
  const health = useAsync(() => (isAdmin ? api<{ items: ConnectorHealth[] }>("/connectors/health") : Promise.resolve(null)), [isAdmin]);
  const metrics = useAsync(() => api<Metrics>("/metrics"), []);
  const [form, setForm] = useState({ kind: "rest", name: "", base_url: "", secret_ref: "", config: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [serverError, setServerError] = useState<string | null>(null);
  const [created, setCreated] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [activityKey, setActivityKey] = useState(0);
  const canSync = can(session.role, "connectors:sync");

  async function synchronise(c: Connector) {
    setSyncError(null);
    try {
      const job = await post<IngestionJob>(`/connectors/${c.id}/sync`);
      setSyncMessage(`Synchronisation of "${c.name}" queued (job ${job.status}). It is processed by the worker; follow it under recent synchronisations.`);
      setActivityKey((k) => k + 1);
    } catch (err) {
      setSyncError(err instanceof Error ? err.message : "Could not start the synchronisation");
    }
  }

  function validate(): Record<string, unknown> | null {
    const e: Record<string, string> = {};
    if (form.name.trim().length < 2) e.name = "Enter a name of at least 2 characters.";
    if (!/^https?:\/\/\S+$/.test(form.base_url)) e.base_url = "Enter an http(s) URL.";
    if (form.secret_ref && !/^[A-Z][A-Z0-9_]{2,60}$/.test(form.secret_ref)) e.secret_ref = "Use an environment variable NAME such as PARTNER_API_KEY (the secret value is never entered here).";
    let config: Record<string, unknown> = {};
    if (form.config.trim()) {
      try { config = JSON.parse(form.config); } catch { e.config = "Configuration must be valid JSON."; }
    }
    setErrors(e);
    return Object.keys(e).length ? null : { kind: form.kind, name: form.name.trim(), base_url: form.base_url, secret_ref: form.secret_ref || undefined, config };
  }

  async function create() {
    const body = validate();
    if (!body) { setConfirm(false); return; }
    setBusy(true);
    setServerError(null);
    try {
      await post("/connectors", body);
      setCreated(`Connector "${form.name}" created.`);
      setForm({ kind: "rest", name: "", base_url: "", secret_ref: "", config: "" });
      connectors.reload();
      health.reload();
    } catch (err) {
      setServerError(err instanceof Error ? err.message : "Could not create the connector");
    } finally {
      setBusy(false);
      setConfirm(false);
    }
  }

  const statusById = Object.fromEntries((health.data?.items ?? []).map((h) => [h.id, h]));
  return (
    <section aria-labelledby="ds-h">
      <PageHeader title="Data Sources" intro="Documents and connectors this tenant uses. Connector destinations must be approved by the server's egress allow-list; tenants cannot widen it." />
      <Card title="Ingested documents by kind" id="ds-docs">
        <Status state={metrics} label="ingestion summary" />
        {metrics.data && (Object.keys(metrics.data.documents_by_kind).length ? (
          <KeyValues rows={Object.entries(metrics.data.documents_by_kind).map(([k, v]) => [k, `${v} document(s)`])} />
        ) : <p className="muted empty">No documents ingested yet. Add them in the Document Library.</p>)}
        <a href="#/documents">Open Document Library</a>
      </Card>

      {!isAdmin && <Notice tone="info">Connector configuration is visible to tenant administrators only.</Notice>}
      {isAdmin && (
        <>
          <Card title="Connectors" id="ds-conn">
            <Status state={connectors} label="connectors" empty={connectors.data && connectors.data.items.length === 0 ? "No connectors configured." : undefined} />
            {connectors.data && connectors.data.items.length > 0 && (
              <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
                <table>
                  <thead><tr><th scope="col">Name</th><th scope="col">Kind</th><th scope="col">Destination</th><th scope="col">Secret</th><th scope="col">Status</th><th scope="col">Actions</th></tr></thead>
                  <tbody>
                    {connectors.data.items.map((c) => {
                      const h = statusById[c.id];
                      return (
                        <tr key={c.id}>
                          <td>{c.name}</td><td>{c.kind}</td><td><code>{c.base_url}</code></td>
                          <td>{c.has_secret ? "referenced by name" : "none"}</td>
                          <td>{h ? <Badge tone={h.status === "ok" ? "ok" : h.status === "degraded" ? "warn" : "bad"} title={h.destination_reason ?? undefined}>{h.status}</Badge> : "–"}</td>
                          <td>{canSync && (c.kind === "rest" || c.kind === "csv") && (c.config.records || c.config.csv) ? <button className="secondary small" onClick={() => synchronise(c)} aria-label={`Synchronise ${c.name}`}>Synchronise</button> : "–"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
          {syncMessage && <Notice tone="ok" onDismiss={() => setSyncMessage(null)}>{syncMessage}</Notice>}
          {syncError && <p role="alert" className="error">{syncError}</p>}
          <Card title="Add a connector" id="ds-new">
            {created && <Notice tone="ok" onDismiss={() => setCreated(null)}>{created}</Notice>}
            <form onSubmit={(e: FormEvent) => { e.preventDefault(); if (validate()) setConfirm(true); }} aria-label="Add connector" noValidate>
              <div className="row">
                <Field label="Kind">{(p) => <select {...p} value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>{KINDS.map((k) => <option key={k}>{k}</option>)}</select>}</Field>
                <Field label="Name" error={errors.name}>{(p) => <input {...p} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />}</Field>
              </div>
              <Field label="Base URL" error={errors.base_url} hint="Must be an origin the server has approved for this tenant.">{(p) => <input {...p} value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} placeholder="https://partner.example.com" />}</Field>
              <Field label="Secret reference (optional)" error={errors.secret_ref} hint="The NAME of a server environment variable; secrets are never stored or shown here.">{(p) => <input {...p} value={form.secret_ref} onChange={(e) => setForm({ ...form, secret_ref: e.target.value })} />}</Field>
              <Field label="Configuration JSON (optional)" error={errors.config} hint="Ticketing: create_path, id_field, payload_map, priority_map. REST pull: a records object (path, id_field, pagination...). CSV pull: a csv object (path, id_field, max_rows...).">{(p) => <textarea {...p} rows={4} className="mono" value={form.config} onChange={(e) => setForm({ ...form, config: e.target.value })} />}</Field>
              {serverError && <p role="alert" className="error">{serverError}</p>}
              <button type="submit">Review and add…</button>
            </form>
          </Card>
          <WebhookEndpointsCard />
        </>
      )}
      <IngestionActivityCard refreshKey={activityKey} />
      <ConfirmDialog open={confirm} title="Add this connector?" confirmLabel="Add connector" busy={busy} onConfirm={create} onCancel={() => setConfirm(false)}>
        <p>The platform will make server-side requests to <code>{form.base_url}</code> for this tenant. The server rejects destinations that are not on its allow-list, and every request is re-checked when it is made.</p>
      </ConfirmDialog>
    </section>
  );
}
