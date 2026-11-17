"""Phase 4 re-measurement on the FROZEN apex-eval-v1 held-out split.

Reuses the Phase 3 harness unchanged (run_phase3.py is not modified), so datasets, metrics, models, prompts
and the dev-only threshold calibration are identical. What differs is the code under test: the Phase 4
safeguards, review gate and identity hardening. This wrapper only adds MEASUREMENT: it records each incident's
review_status and runs the end-to-end step through the human-review gate (a supervisor review is recorded
whenever the platform requires one). Nothing here tunes prompts, thresholds or retrieval on the test split.

Usage (real AI only; Ollama is started with scripts/ollama_ctl.py start):
  python evaluation/benchmarks/run_phase4.py --embedding sentence_transformers --llm ollama --e2e-runs 5 --qa-repeats 2
Results go to evaluation/reports/phase4-remeasure/ (Phase 3 reports are never touched).
"""
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import run_phase3 as p3  # noqa: E402

ROOT = p3.ROOT
OUT_ROOT = ROOT / "evaluation" / "reports" / "phase4-remeasure"
_statuses: list[str] = []
_original_extract = p3.extract_incident
_original_structured = p3.structured_eval
_original_summary = p3.summarize_structured


def _extract_recording(session, **kwargs):
    incident = _original_extract(session, **kwargs)
    _statuses.append(incident.review_status)
    return incident


def _structured_with_review(db, tenant_id, embedder, llm, reports, user_id):
    _statuses.clear()
    rows = _original_structured(db, tenant_id, embedder, llm, reports, user_id)
    queue = list(_statuses)
    for row in rows:  # statuses were recorded in order, only for incidents that were actually created
        row["review_status"] = queue.pop(0) if row["pipeline"] == "ok" else "rejected_at_extraction"
    return rows


def _summary_with_review(rows):
    out = _original_summary(rows)
    n = len(rows)
    counts = {k: sum(1 for r in rows if r.get("review_status") == k)
              for k in ("pending_review", "needs_review", "rejected_at_extraction")}
    out["review"] = {**counts, "needs_review_rate": round(counts["needs_review"] / n, 4) if n else None,
                     "rejected_at_extraction_rate": round(counts["rejected_at_extraction"] / n, 4) if n else None,
                     "definition": "needs_review = incident created but blocked until a human accepts it; "
                                   "rejected_at_extraction = no incident created (e.g. equipment not identified)"}
    return out


def _e2e_with_review(client, slug, users, worker_db, ticketing, n_runs, report_text):
    eng = p3.login(client, slug, users, "support_engineer")
    sup = p3.login(client, slug, users, "maintenance_supervisor")
    cfg = p3.worker_mod.WorkerConfig(backoff_base=0, http_timeout=5)
    runs = []
    for i in range(n_runs):
        marks = {"start": time.perf_counter()}
        inc = client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": report_text})
        inc.raise_for_status()
        incident = inc.json()
        marks["extract"] = time.perf_counter()
        review_required = incident["review_status"] == "needs_review"
        if review_required:  # the platform demands a human decision before a ticket can exist
            client.post(f"/api/v1/incidents/{incident['id']}/review", headers=sup, json={
                "decision": "accept", "comment": "benchmark supervisor review"}).raise_for_status()
        marks["review"] = time.perf_counter()
        t = client.post("/api/v1/tickets", headers=eng, json={"incident_id": incident["id"]})
        t.raise_for_status()
        tid = t.json()["id"]
        client.post(f"/api/v1/tickets/{tid}/request-approval", headers=eng).raise_for_status()
        marks["draft_and_request"] = time.perf_counter()
        client.post(f"/api/v1/approvals/{tid}/decision", headers=sup,
                    json={"decision": "approved", "comment": "bench"}).raise_for_status()
        marks["approve"] = time.perf_counter()
        outcomes = p3.worker_mod.drain(worker_db, cfg)
        marks["submit"] = time.perf_counter()
        final = client.get(f"/api/v1/tickets/{tid}", headers=eng).json()
        runs.append({"run": i + 1, "state": final["state"], "external_ticket_id": final["external_ticket_id"],
                     "worker_outcomes": outcomes, "review_status_at_extraction": incident["review_status"],
                     "human_review_required": review_required,
                     "total_s": round(marks["submit"] - marks["start"], 3),
                     "extract_s": round(marks["extract"] - marks["start"], 3),
                     "review_s": round(marks["review"] - marks["extract"], 3),
                     "draft_and_request_s": round(marks["draft_and_request"] - marks["review"], 3),
                     "approve_s": round(marks["approve"] - marks["draft_and_request"], 3),
                     "submit_s": round(marks["submit"] - marks["approve"], 3),
                     "incident_citations": len(incident["citations"])})
    return runs, len(ticketing.state.mock.tickets)


p3.extract_incident = _extract_recording
p3.structured_eval = _structured_with_review
p3.summarize_structured = _summary_with_review
p3.e2e_eval = _e2e_with_review

if __name__ == "__main__":
    if "--out-root" not in sys.argv:
        sys.argv += ["--out-root", str(OUT_ROOT)]
    if "--qa-split" in sys.argv and sys.argv[sys.argv.index("--qa-split") + 1] != "test":
        sys.exit("Phase 4 re-measurement reports the held-out test split only.")
    p3.main()
