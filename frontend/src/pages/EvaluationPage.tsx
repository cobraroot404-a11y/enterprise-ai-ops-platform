import { useState } from "react";
import { Badge, Card, fmtNum, fmtPct, fmtTime, Notice, PageHeader, Status } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { api } from "../services/api";
import type { EvaluationReports, EvaluationRun, Metrics } from "../types";

const TONE: Record<string, string> = { MET: "ok", "NOT MET": "bad", "not measured": "neutral" };

export default function EvaluationPage() {
  const reports = useAsync(() => api<EvaluationReports>("/evaluation/reports"), []);
  const metrics = useAsync(() => api<Metrics>("/metrics"), []);
  const [showBaseline, setShowBaseline] = useState(false);
  const d = reports.data;
  const runs = (d?.runs ?? []).filter((r) => showBaseline || r.evidence_class === "real_ai");
  const fmtTarget = (t: { id: string; value: number }) => (t.id === "duplicate_tickets" ? String(t.value) : fmtPct(t.value, 0));
  const fmtActual = (t: NonNullable<EvaluationReports["targets"]>[number]) =>
    !t.actual ? "–" : t.id === "duplicate_tickets" ? `${t.actual.min}–${t.actual.max}` : `${fmtPct(t.actual.min)}–${fmtPct(t.actual.max)}`;

  return (
    <section aria-labelledby="ev-h">
      <PageHeader title="Evaluation Dashboard" intro="Measured results read from the committed evaluation artifacts, plus this tenant's live operational figures. Nothing here is estimated." />
      <Status state={reports} label="evaluation reports" />
      {d && !d.available && <Notice tone="info">No evaluation artifacts were found on the server. Nothing is shown rather than inventing numbers.</Notice>}
      {d && <Notice tone="warn">{d.disclaimer}</Notice>}

      {d?.available && (
        <>
          <Card title="Targets versus measured results" id="ev-targets">
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Targets and measured results (scrollable)">
            <table>
              <caption className="sr-only">Targets and measured results</caption>
              <thead><tr><th scope="col">Measure</th><th scope="col">Proposed target</th><th scope="col">Measured (range over real-AI runs)</th><th scope="col">Status</th></tr></thead>
              <tbody>
                {d.targets.map((t) => (
                  <tr key={t.id}>
                    <td>{t.label}</td><td>{t.op === "==" ? "exactly " : "at least "}{fmtTarget(t)}</td>
                    <td>{fmtActual(t)}{t.actual ? <span className="muted small"> ({t.actual.runs} runs)</span> : null}</td>
                    <td><Badge tone={TONE[t.status] ?? "neutral"}>{t.status}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
            <p className="muted small">Targets are proposals from the specification, not results. Only measures with evidence are scored; the rest are shown as “not measured” here (cross-tenant isolation and authorization are verified by the test-suite, not by this table).</p>
          </Card>

          <Card title="Benchmark runs" id="ev-runs" actions={<label className="inline small"><input type="checkbox" checked={showBaseline} onChange={(e) => setShowBaseline(e.target.checked)} /> Include deterministic baseline (functional only)</label>}>
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Benchmark runs (scrollable)">
              <table>
                <caption className="sr-only">Benchmark runs</caption>
                <thead><tr><th scope="col">Run</th><th scope="col">Backends</th><th scope="col">Recall@5</th><th scope="col">MRR</th><th scope="col">Citation correctness</th><th scope="col">Grounded</th><th scope="col">Structured valid</th><th scope="col">LLM median / p95 (s)</th><th scope="col">E2E median (s)</th></tr></thead>
                <tbody>{runs.map((r) => <RunRow key={`${r.group}-${r.id}`} run={r} />)}</tbody>
              </table>
            </div>
            {runs[0] && <p className="muted small">Dataset {runs[0].dataset} (synthetic, author-labelled). Model {runs.find((r) => r.versions.ollama_model)?.versions.ollama_model ?? "n/a"}; hardware: {String(runs.find((r) => r.hardware.cpu)?.hardware.cpu ?? "n/a")}. Rows marked “note” carry a data-quality note in their report folder.</p>}
          </Card>

          <div className="grid-2">
            <Card title="Smoke tests (functional)" id="ev-smoke">
              {d.smoke.length === 0 && <p className="muted empty">No smoke runs recorded.</p>}
              {d.smoke.map((s) => (
                <p key={s.id}><Badge tone={s.checks_passed === s.checks_total ? "ok" : "bad"}>{s.checks_passed} of {s.checks_total} checks</Badge> <span className="muted small">{fmtTime(s.started_utc)}{s.failed.length ? ` · failed: ${s.failed.join(", ")}` : ""}</span></p>
              ))}
              <p className="muted small">Limited functional smoke testing; not a statistically representative AI-quality benchmark.</p>
            </Card>
            <Card title="Fault injection" id="ev-fi">
              {!d.fault_injection && <p className="muted empty">No fault-injection report found.</p>}
              {d.fault_injection && (
                <>
                  <p><Badge tone={d.fault_injection.failed === 0 ? "ok" : "bad"}>{d.fault_injection.passed} of {d.fault_injection.scenarios} scenarios passed</Badge></p>
                  <ul className="small">{d.fault_injection.items.map((i) => <li key={i.id}>{i.passed ? "✓" : "✗"} {i.id} {i.name}</li>)}</ul>
                </>
              )}
            </Card>
          </div>
        </>
      )}

      <Card title="This tenant, live" id="ev-live">
        <Status state={metrics} label="live metrics" />
        {metrics.data && (
          <ul className="plain">
            <li>Tickets submitted: {metrics.data.tickets_by_state.SUBMITTED ?? 0}; failed: {metrics.data.tickets_by_state.FAILED ?? 0}; submission attempts: {metrics.data.submission_attempts}</li>
            <li>Incidents needing human review: {metrics.data.incidents_by_review_status.needs_review ?? 0} of {metrics.data.incidents}</li>
            <li>Approvals decided: {metrics.data.approvals_decided}; average turnaround {metrics.data.avg_approval_turnaround_seconds === null ? "–" : `${fmtNum(metrics.data.avg_approval_turnaround_seconds / 60, 1)} minutes`}</li>
          </ul>
        )}
        <p className="muted small">Operational counts, not AI-quality measurements.</p>
      </Card>
    </section>
  );
}

function RunRow({ run }: { run: EvaluationRun }) {
  const m = run.metrics;
  const real = run.evidence_class === "real_ai";
  return (
    <tr>
      <td>
        <span title={run.command ?? undefined}>{run.group === "phase3" ? "Phase 3" : "Phase 4 re-measure"}</span>
        <div className="muted small">{fmtTime(run.started_utc)}{run.has_note ? " · note" : ""}</div>
      </td>
      <td>{run.backends ? `${run.backends.llm} + ${run.backends.embedding}` : "–"}{!real && <div><Badge tone="warn">functional only</Badge></div>}</td>
      <td>{fmtPct(m.recall_at_5)}</td><td>{fmtNum(m.mrr, 3)}</td><td>{fmtPct(m.citation_correctness)}</td><td>{fmtPct(m.groundedness_rate)}</td>
      <td>{fmtPct(m.structured_validity)}</td><td>{fmtNum(m.llm_inference_median_s, 1)} / {fmtNum(m.llm_inference_p95_s, 1)}</td><td>{fmtNum(m.e2e_median_s, 1)}</td>
    </tr>
  );
}
