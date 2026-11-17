import { Badge, Card, fmtTime, KeyValues, Notice, PageHeader, Status } from "../components/ui";
import { useState } from "react";
import { useAsync } from "../hooks/useAsync";
import { api } from "../services/api";
import { can } from "../services/rbac";
import type { ConnectorHealth, Metrics, ObservabilitySummary, Session } from "../types";
import { fmtNum, fmtPct } from "../components/ui";

interface ApiHealth {
  status: string;
  [key: string]: unknown;
}

export default function IntegrationHealthPage({ session }: { session: Session }) {
  const isAdmin = can(session.role, "connectors:read");
  const platform = useAsync(() => api<ApiHealth>("/health"), []);
  const connectors = useAsync(() => (isAdmin ? api<{ items: ConnectorHealth[] }>("/connectors/health") : Promise.resolve(null)), [isAdmin]);
  const metrics = useAsync(() => api<Metrics>("/metrics"), []);
  const obs = useAsync(() => api<ObservabilitySummary>("/observability/summary"), []);
  const [probed, setProbed] = useState<ConnectorHealth[] | null>(null);
  const [probing, setProbing] = useState(false);
  const [probeError, setProbeError] = useState<string | null>(null);
  async function runProbe() {
    setProbing(true);
    setProbeError(null);
    try {
      setProbed((await api<{ items: ConnectorHealth[] }>("/connectors/health?probe=true")).items);
    } catch (err) {
      setProbeError(err instanceof Error ? err.message : "The live probe failed");
    } finally { setProbing(false); }
  }
  const reload = () => { platform.reload(); connectors.reload(); metrics.reload(); obs.reload(); setProbed(null); };
  const probeById = Object.fromEntries((probed ?? []).map((c) => [c.id, c.live_probe]));

  return (
    <section aria-labelledby="ih-h">
      <PageHeader title="Integration Health" intro="Configuration and delivery health of the connectors this tenant uses." actions={<button className="secondary" onClick={reload}>Refresh</button>} />
      <Notice tone="info">Nothing is sent to the external systems unless you press "Run live probe" (tenant administrators, REST and CSV sources only: one bounded read each, nothing ingested). Otherwise status reflects whether the destination is authorized, whether the secret is configured on the server, and the results of recent real submissions.</Notice>
      {isAdmin && <p><button onClick={runProbe} disabled={probing}>{probing ? "Probing…" : "Run live probe"}</button></p>}
      {probeError && <p role="alert" className="error">{probeError}</p>}

      <Card title="Platform" id="ih-plat">
        <Status state={platform} label="platform health" />
        {platform.data && (
          <p className="row tight">
            <Badge tone={platform.data.status === "ok" ? "ok" : "bad"}>API {platform.data.status}</Badge>
            <span className="muted small">language model backend: {String(platform.data.llm_backend ?? "unknown")} · embeddings: {String(platform.data.embedding_backend ?? "unknown")}</span>
          </p>
        )}
      </Card>

      <Card title="Delivery and retries (this tenant)" id="ih-del">
        <Status state={metrics} label="delivery metrics" />
        {metrics.data && (
          <KeyValues rows={[
            ["Submitted tickets", metrics.data.tickets_by_state.SUBMITTED ?? 0],
            ["Failed tickets", metrics.data.tickets_by_state.FAILED ?? 0],
            ["Retry scheduled", metrics.data.tickets_by_state.RETRY_PENDING ?? 0],
            ["Tickets that needed more than one attempt", metrics.data.tickets_needing_retries],
            ["Total submission attempts", metrics.data.submission_attempts],
            ["Dead-lettered events", metrics.data.dead_letters],
          ]} />
        )}
      </Card>

      <Card title="Operational telemetry (this tenant)" id="ih-obs">
        <Status state={obs} label="telemetry" />
        {obs.data && <Telemetry data={obs.data} />}
      </Card>

      {!isAdmin && <Notice tone="info">Per-connector status is visible to tenant administrators only.</Notice>}
      {isAdmin && (
        <>
          <Status state={connectors} label="connector health" empty={connectors.data && connectors.data.items.length === 0 ? "No connectors configured." : undefined} />
          {connectors.data?.items.map((c) => (
            <article key={c.id} className="card" aria-label={`Connector ${c.name}`}>
              <h3>{c.name} <Badge tone={(probed?.find((p) => p.id === c.id)?.status ?? c.status) === "ok" ? "ok" : (probed?.find((p) => p.id === c.id)?.status ?? c.status) === "degraded" ? "warn" : "bad"}>{probed?.find((p) => p.id === c.id)?.status ?? c.status}</Badge></h3>
              <KeyValues rows={[
                ["Kind", c.kind],
                ["Destination", <code key="d">{c.base_url}</code>],
                ["Destination authorized by the server", c.destination_authorized ? "yes" : `NO: ${c.destination_reason ?? "not allowed"}`],
                ["Secret", c.has_secret_ref ? (c.secret_configured ? "configured on the server" : "MISSING on the server") : "none required"],
                ...(probeById[c.id] ? ([["Live probe", `${probeById[c.id]!.status} (${probeById[c.id]!.duration_ms} ms${probeById[c.id]!.http_status ? `, HTTP ${probeById[c.id]!.http_status}` : ""}) at ${fmtTime(probeById[c.id]!.checked_at)}`]] as [string, string][]) : []),
                ...(c.delivery ? ([
                  ["Submitted / failed / retry scheduled", `${c.delivery.submitted} / ${c.delivery.failed} / ${c.delivery.retry_pending}`],
                  ["Last confirmed submission", fmtTime(c.delivery.last_success_at)],
                  ["Last error", c.delivery.last_error ?? "–"],
                ] as [string, string][]) : []),
              ]} />
            </article>
          ))}
        </>
      )}
    </section>
  );
}

const LATENCY = [
  ["retrieval_seconds", "Retrieval"], ["embedding_seconds", "Embedding"], ["llm_seconds", "Language model"],
  ["connector_seconds", "External connector call"], ["ingestion_seconds", "Document ingestion"], ["submission_seconds", "Ticket submission (worker)"],
] as const;

function Telemetry({ data }: { data: ObservabilitySummary }) {
  const db = data.database;
  const rows = LATENCY.flatMap(([name, label]) => {
    const series = data.process.timers.filter((t) => t.name === name);
    if (!series.length) return [];
    const count = series.reduce((n, t) => n + t.count, 0);
    const worst = Math.max(...series.map((t) => t.p95_s));
    const mean = series.reduce((n, t) => n + t.mean_s * t.count, 0) / count;
    return [{ label, count, mean, p95: worst }];
  });
  const outcomes = data.process.counters.filter((c) => c.name === "connector_calls_total");
  return (
    <>
      <p className="muted small">Scope: {data.scope}. Process figures reset when the API restarts and only cover activity since then; nothing is estimated.</p>
      {rows.length === 0 ? <p className="muted empty">No latency measurements recorded since this API process started.</p> : (
        <div className="table-wrap" tabIndex={0} role="region" aria-label="Latency measurements (scrollable)">
          <table>
            <caption className="sr-only">Latency since process start</caption>
            <thead><tr><th scope="col">Operation</th><th scope="col">Calls</th><th scope="col">Mean (s)</th><th scope="col">Worst p95 (s)</th></tr></thead>
            <tbody>{rows.map((r) => <tr key={r.label}><td>{r.label}</td><td>{r.count}</td><td>{fmtNum(r.mean, 3)}</td><td>{fmtNum(r.p95, 3)}</td></tr>)}</tbody>
          </table>
        </div>
      )}
      <KeyValues rows={[
        ["Incidents that required human review", db.incident_review.review_required_rate === null ? "no incidents yet" : `${db.incident_review.required_review} of ${db.incident_review.extracted} (${fmtPct(db.incident_review.review_required_rate)})`],
        ["Review decisions", `${db.incident_review.accepted} accepted, ${db.incident_review.rejected} rejected`],
        ["Submission outcomes", `${db.submission.submitted} submitted, ${db.submission.retries_scheduled} retries scheduled, ${db.submission.dead_lettered} dead-lettered, ${db.submission.blocked_by_release_controls} blocked by release controls`],
        ["Connector call outcomes (this process)", outcomes.length ? outcomes.map((c) => `${c.labels.outcome}: ${c.value}`).join(", ") : "none yet"],
        ["Ticket error classes", Object.keys(db.ticket_error_classes).length ? Object.entries(db.ticket_error_classes).map(([k, v]) => `${k}: ${v}`).join(", ") : "none"],
      ]} />
    </>
  );
}
