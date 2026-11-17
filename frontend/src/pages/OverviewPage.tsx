import { useAsync } from "../hooks/useAsync";
import { assetLabel, useTenantProfile } from "../hooks/useTenantProfile";
import { api, qs } from "../services/api";
import { can } from "../services/rbac";
import type { Metrics, OnboardingHealth, Page, AuditRow, Ticket } from "../types";
import { Badge, Card, fmtNum, fmtTime, PageHeader, Status } from "../components/ui";
import { TicketStateBadge } from "../components/provenance";
import type { Session } from "../types";

const LINKS = { needs_review: "#/incidents?review=needs_review", approvals: "#/approvals" };

export default function OverviewPage({ session }: { session: Session }) {
  const metrics = useAsync(() => api<Metrics>("/metrics"), []);
  const profile = useTenantProfile();
  const health = useAsync(() => api<OnboardingHealth>("/onboarding/health"), []);
  const pending = useAsync(() => api<Page<Ticket>>(`/approvals${qs({ limit: 5 })}`), []);
  const recent = useAsync(() => api<Page<Ticket>>(`/tickets${qs({ limit: 5, sort: "updated_at", order: "desc" })}`), []);
  const audit = useAsync(() => (can(session.role, "audit:read") ? api<Page<AuditRow>>(`/audit${qs({ limit: 6 })}`) : Promise.resolve(null)), [session.role]);
  const label = assetLabel(profile.data);
  const m = metrics.data;
  const needsReview = m?.incidents_by_review_status?.needs_review ?? 0;

  return (
    <section aria-labelledby="ov-h">
      <PageHeader
        title="Overview"
        intro={`Live operational summary for ${session.tenant}. Every number is computed from this tenant's own records.`}
        actions={<button className="secondary" onClick={() => { metrics.reload(); health.reload(); pending.reload(); recent.reload(); audit.reload(); }}>Refresh</button>}
      />
      <Status state={metrics} label="metrics" />
      {m && (
        <div className="stats" role="list" aria-label="Key figures">
          <Stat label="Documents" value={m.documents} />
          <Stat label={`${label.charAt(0).toUpperCase()}${label.slice(1)} incidents`} value={m.incidents} />
          <Stat label="Awaiting incident review" value={needsReview} tone={needsReview ? "bad" : undefined} href={LINKS.needs_review} />
          <Stat label="Awaiting ticket approval" value={m.tickets_by_state?.PENDING_APPROVAL ?? 0} tone={m.tickets_by_state?.PENDING_APPROVAL ? "warn" : undefined} href={LINKS.approvals} />
          <Stat label="Submitted tickets" value={m.tickets_by_state?.SUBMITTED ?? 0} />
          <Stat label="Failed / dead-lettered" value={(m.tickets_by_state?.FAILED ?? 0) + m.dead_letters} tone={(m.tickets_by_state?.FAILED ?? 0) + m.dead_letters ? "bad" : undefined} />
          <Stat label="Avg approval turnaround" value={m.avg_approval_turnaround_seconds === null ? "–" : `${fmtNum(m.avg_approval_turnaround_seconds / 60, 1)} min`} note={`${m.approvals_decided} decided`} />
        </div>
      )}

      <div className="grid-2">
        <Card title="Onboarding health" id="ov-onb">
          <Status state={health} label="onboarding health" />
          {health.data && (
            <>
              <p><Badge tone={health.data.passed === health.data.total ? "ok" : "warn"}>{health.data.passed} of {health.data.total} checks passing</Badge></p>
              <ul className="plain">
                {health.data.checks.filter((c) => c.status === "fail").map((c) => <li key={c.id} className="warn">✗ {c.label}</li>)}
              </ul>
              <a href="#/onboarding">Open Customer Onboarding</a>
            </>
          )}
        </Card>

        <Card title="Incident review load" id="ov-rev">
          {m && Object.keys(m.incidents_by_review_status).length === 0 && <p className="muted empty">No incidents have been extracted yet.</p>}
          {m && Object.entries(m.incidents_by_review_status).map(([k, v]) => (
            <p key={k} className="row tight"><Badge tone={k === "needs_review" ? "bad" : k === "rejected" ? "bad" : "ok"}>{k.replace("_", " ")}</Badge> {v}</p>
          ))}
          <p className="muted small">An incident needs human review when evidence is missing, the asset is not in the register, or model output failed validation.</p>
        </Card>
      </div>

      <div className="grid-2">
        <Card title="Recently updated tickets" id="ov-tix">
          <Status state={recent} label="tickets" empty={recent.data && recent.data.items.length === 0 ? "No tickets yet." : undefined} />
          {recent.data && recent.data.items.length > 0 && (
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table"><table>
              <thead><tr><th scope="col">Title</th><th scope="col">State</th><th scope="col">Updated</th></tr></thead>
              <tbody>
                {recent.data.items.map((t) => (
                  <tr key={t.id}><td><a href={`#/tickets?id=${t.id}`}>{t.title}</a></td><td><TicketStateBadge state={t.state} externalId={t.external_ticket_id} /></td><td>{fmtTime(t.updated_at)}</td></tr>
                ))}
              </tbody>
            </table></div>
          )}
        </Card>

        {can(session.role, "audit:read") ? (
          <Card title="Latest audit events" id="ov-aud">
            <Status state={audit} label="audit events" />
            {audit.data && (
              <ul className="plain">
                {audit.data.items.map((a) => <li key={a.id}><code>{a.action}</code> <span className="muted small">{a.actor} · {fmtTime(a.created_at)}</span></li>)}
              </ul>
            )}
            <a href="#/audit">Open Audit Logs</a>
          </Card>
        ) : (
          <Card title="Awaiting approval" id="ov-pend">
            <Status state={pending} label="approvals" empty={pending.data && pending.data.items.length === 0 ? "Nothing is waiting for approval." : undefined} />
            {pending.data && pending.data.items.map((t) => <p key={t.id}><a href={`#/approvals`}>{t.title}</a></p>)}
          </Card>
        )}
      </div>
    </section>
  );
}

function Stat({ label, value, tone, href, note }: { label: string; value: number | string; tone?: string; href?: string; note?: string }) {
  const body = (
    <>
      <span className={`stat-value ${tone ? `tone-${tone}` : ""}`}>{value}</span>
      <span className="stat-label">{label}</span>
      {note && <span className="muted small">{note}</span>}
    </>
  );
  return <div role="listitem" className="stat">{href ? <a href={href} className="stat-link">{body}</a> : body}</div>;
}
