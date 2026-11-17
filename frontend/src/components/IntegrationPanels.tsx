import { useState } from "react";
import type { FormEvent } from "react";
import { Badge, Card, Field, fmtTime, Notice, Status } from "./ui";
import ConfirmDialog from "./ConfirmDialog";
import { useAsync } from "../hooks/useAsync";
import { api, patch, post, qs } from "../services/api";
import type { IngestionJob, Page, WebhookEndpoint } from "../types";

const DEFAULT_CONFIG = JSON.stringify({ id_field: "id", required_fields: ["title", "body"], version_field: "updated_at", document_kind: "other", max_records: 100 }, null, 2);

const tone = (status: string) => (status === "COMPLETED" ? "ok" : status === "FAILED" ? "bad" : status === "CANCELLED" ? "neutral" : "warn");

/** Recent synchronisations (REST and CSV pulls) and webhook deliveries: the durable jobs the worker runs. Counts only, never content. */
export function IngestionActivityCard({ refreshKey = 0 }: { refreshKey?: number }) {
  const jobs = useAsync(async () => {
    const [sync, hooks] = await Promise.all([
      api<Page<IngestionJob>>(`/ingestion/jobs${qs({ job_type: "sync", limit: 8 })}`),
      api<Page<IngestionJob>>(`/ingestion/jobs${qs({ job_type: "webhook", limit: 8 })}`),
    ]);
    return [...sync.items, ...hooks.items].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 10);
  }, [refreshKey]);
  return (
    <Card title="Recent synchronisations and webhook deliveries" id="ds-activity">
      <div className="row tight"><button className="secondary" onClick={jobs.reload}>Refresh</button></div>
      <Status state={jobs} label="ingestion activity" empty={jobs.data && jobs.data.length === 0 ? "No synchronisation or webhook delivery yet." : undefined} />
      {jobs.data && jobs.data.length > 0 && (
        <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
          <table>
            <thead><tr><th scope="col">Type</th><th scope="col">Source</th><th scope="col">Status</th><th scope="col">Result</th><th scope="col">Attempts</th><th scope="col">Created</th></tr></thead>
            <tbody>
              {jobs.data.map((j) => (
                <tr key={j.id}>
                  <td>{j.job_type}</td>
                  <td>{j.filename ?? "–"}</td>
                  <td><Badge tone={tone(j.status)}>{j.status}</Badge>{j.error_code ? <span className="muted small"> {j.error_code}</span> : null}</td>
                  <td>{j.sync ? `${j.outcome ?? "running"}: ${j.sync.created} created, ${j.sync.updated} updated, ${j.sync.unchanged} unchanged, ${j.sync.invalid} rejected, ${j.sync.skipped_deleted + j.sync.tombstoned_changed} kept deleted` : (j.outcome ?? "–")}</td>
                  <td>{j.attempts}/{j.max_attempts}</td>
                  <td>{fmtTime(j.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

/** Tenant administrators provision signed inbound webhook endpoints. Only the NAME of the signing-secret variable is entered; the secret is never stored or shown. */
export function WebhookEndpointsCard() {
  const list = useAsync(() => api<{ items: WebhookEndpoint[] }>("/webhook-endpoints"), []);
  const [form, setForm] = useState({ name: "", secret_ref: "", config: DEFAULT_CONFIG });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [serverError, setServerError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [rotating, setRotating] = useState<{ id: string; value: string } | null>(null);

  function validate(): Record<string, unknown> | null {
    const e: Record<string, string> = {};
    if (!/^[A-Za-z0-9][A-Za-z0-9 ._-]{1,59}$/.test(form.name)) e.name = "Use 2 to 60 letters, digits, spaces, dots, dashes or underscores.";
    if (!/^[A-Z][A-Z0-9_]{2,60}$/.test(form.secret_ref)) e.secret_ref = "Enter the NAME of a server environment variable such as PARTNER_WEBHOOK_SECRET (never the secret itself).";
    let config: Record<string, unknown> = {};
    try { config = JSON.parse(form.config); } catch { e.config = "Configuration must be valid JSON."; }
    if (!e.config && typeof config.id_field !== "string") e.config = "The configuration needs an id_field (source record identifiers are never invented).";
    setErrors(e);
    return Object.keys(e).length ? null : { name: form.name.trim(), secret_ref: form.secret_ref, config };
  }

  async function create() {
    const body = validate();
    if (!body) { setConfirm(false); return; }
    setBusy(true);
    setServerError(null);
    try {
      const made = await post<WebhookEndpoint>("/webhook-endpoints", body);
      setMessage(`Endpoint "${made.name}" created. Senders post signed deliveries to ${made.receive_path}.`);
      setForm({ name: "", secret_ref: "", config: DEFAULT_CONFIG });
      list.reload();
    } catch (err) {
      setServerError(err instanceof Error ? err.message : "Could not create the endpoint");
    } finally { setBusy(false); setConfirm(false); }
  }

  async function change(id: string, body: Record<string, unknown>, done: string) {
    setServerError(null);
    try {
      await patch(`/webhook-endpoints/${id}`, body);
      setMessage(done);
      setRotating(null);
      list.reload();
    } catch (err) {
      setServerError(err instanceof Error ? err.message : "Could not change the endpoint");
    }
  }

  return (
    <>
      <Card title="Webhook endpoints" id="ds-hooks">
        <Notice tone="info">Deliveries must be signed (HMAC-SHA256 over timestamp, delivery id and raw body). A 202 response means a delivery was queued, not processed; follow it under recent deliveries. Secrets are held by the server and referenced by name only.</Notice>
        {message && <Notice tone="ok" onDismiss={() => setMessage(null)}>{message}</Notice>}
        {serverError && <p role="alert" className="error">{serverError}</p>}
        <Status state={list} label="webhook endpoints" empty={list.data && list.data.items.length === 0 ? "No webhook endpoints yet." : undefined} />
        {list.data && list.data.items.length > 0 && (
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
            <table>
              <thead><tr><th scope="col">Name</th><th scope="col">Receive path</th><th scope="col">Status</th><th scope="col">Secret</th><th scope="col">Actions</th></tr></thead>
              <tbody>
                {list.data.items.map((e) => (
                  <tr key={e.id}>
                    <td>{e.name}</td>
                    <td><code>{e.receive_path}</code></td>
                    <td><Badge tone={e.status === "active" ? "ok" : "neutral"}>{e.status}</Badge></td>
                    <td>{e.secret_configured ? "configured on the server" : <Badge tone="bad">variable not set</Badge>}{e.has_previous_secret ? " · previous secret still accepted" : ""}</td>
                    <td>
                      <div className="row tight">
                        <button className="secondary small" onClick={() => change(e.id, { status: e.status === "active" ? "disabled" : "active" }, `Endpoint "${e.name}" is now ${e.status === "active" ? "disabled" : "active"}.`)}>{e.status === "active" ? "Disable" : "Enable"}</button>
                        <button className="secondary small" onClick={() => setRotating({ id: e.id, value: "" })} aria-label={`Rotate secret of ${e.name}`}>Rotate secret</button>
                        {e.has_previous_secret && <button className="secondary small" onClick={() => change(e.id, { drop_previous_secret: true }, `The previous secret of "${e.name}" is no longer accepted.`)}>Drop previous secret</button>}
                      </div>
                      {rotating?.id === e.id && (
                        <form className="row tight" aria-label={`Rotate secret of ${e.name}`} onSubmit={(ev: FormEvent) => { ev.preventDefault(); if (/^[A-Z][A-Z0-9_]{2,60}$/.test(rotating.value)) change(e.id, { secret_ref: rotating.value }, `Secret of "${e.name}" rotated; the old one stays accepted until dropped.`); }}>
                          <Field label="New secret variable name">{(p) => <input {...p} value={rotating.value} onChange={(ev) => setRotating({ id: e.id, value: ev.target.value })} />}</Field>
                          <button type="submit" className="small">Rotate</button>
                        </form>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <Card title="Add a webhook endpoint" id="ds-hook-new">
        <form onSubmit={(e: FormEvent) => { e.preventDefault(); if (validate()) setConfirm(true); }} aria-label="Add webhook endpoint" noValidate>
          <div className="row">
            <Field label="Endpoint name" error={errors.name}>{(p) => <input {...p} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />}</Field>
            <Field label="Signing secret variable name" error={errors.secret_ref} hint="The NAME of a server environment variable.">{(p) => <input {...p} value={form.secret_ref} onChange={(e) => setForm({ ...form, secret_ref: e.target.value })} />}</Field>
          </div>
          <Field label="Record configuration (JSON)" error={errors.config} hint="id_field is required; optional record_path, required_fields, version_field, document_kind, max_records, reject_policy.">{(p) => <textarea {...p} rows={7} className="mono" value={form.config} onChange={(e) => setForm({ ...form, config: e.target.value })} />}</Field>
          <button type="submit">Review and add…</button>
        </form>
      </Card>
      <ConfirmDialog open={confirm} title="Add this webhook endpoint?" confirmLabel="Add endpoint" busy={busy} onConfirm={create} onCancel={() => setConfirm(false)}>
        <p>This creates an endpoint that accepts signed deliveries for this tenant only. Anyone holding the signing secret can send records to it; keep the secret on the server and rotate it if it leaks.</p>
      </ConfirmDialog>
    </>
  );
}
