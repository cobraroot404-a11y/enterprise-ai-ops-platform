"""Phase 8 baseline runner: real Ollama + MiniLM against the eval-v2 DEV split, current system unchanged.

    python evaluation/phase8/run_baseline.py --reps 3                 # real AI baseline (needs Ollama; start with scripts/ollama_ctl.py)
    python evaluation/phase8/run_baseline.py --split dev --reps 1 --limit 6 --out-root <tmp>   # smoke run

This script only RECORDS raw per-item outputs (JSONL) and the environment; all metrics are computed by evaluation/phase8/score_baseline.py
from the raw files and the frozen labels. The test and challenge splits are never read for tuning: this runner refuses any split other than dev
unless --allow-heldout is passed (reserved for the single final evaluation).

Isolation: database eaop_eval2 (dropped and recreated each run), tenants created through the public onboarding path, mock external systems on loopback.
"""
import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import logging
import os
import platform
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("backend", "mock-services/ticketing", "mock-services/inventory", "mock-services/servicedesk", "mock-services/fleet", "mock-services/crm",
          "scripts", "evaluation/benchmarks", "evaluation/phase8"):
    sys.path.insert(0, str(ROOT / p))

import crm_app  # noqa: E402
import fleet_app  # noqa: E402
import inventory_app  # noqa: E402
import run_phase3 as p3  # noqa: E402  (re-used: ServerThread, Sampler, setup, hardware helpers)
import servicedesk_app  # noqa: E402
import ticketing_app  # noqa: E402
from app.api.v1 import domain_routes  # noqa: E402
from app.connectors import egress  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.database.session import Database  # noqa: E402
from app.main import create_app  # noqa: E402
from app.retrieval.search import search  # noqa: E402
from app.workflows import worker as worker_mod  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from onboard_tenant import onboard  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

DS = ROOT / "evaluation" / "datasets" / "eval-v2"
EVAL_DB = "eaop_eval2"
PASSWORD = "Eval2-" + uuid.uuid4().hex[:12]  # generated per run, never stored
TICKETING_KEY = "eval2-ticketing-" + uuid.uuid4().hex[:8]
SERVICEDESK_KEY = "eval2-servicedesk-" + uuid.uuid4().hex[:8]
APEX_KINDS = {"manual": "equipment_manual", "register": "equipment_register", "history": "incident_history", "log": "maintenance_log", "inspection": "inspection_report"}


def load(name):
    return [json.loads(x) for x in (DS / name).read_text(encoding="utf-8").splitlines() if x.strip()]


def file_kind(passages, tenant, fname):
    return next(p["kind"] for p in passages if p["tenant"] == tenant and p["file"] == fname)


class RecordingLLM:
    """Wraps the real Ollama client; records raw extraction validity and per-call stats without changing behaviour."""

    def __init__(self, inner):
        self.inner = inner
        self.extract_log: list[dict] = []
        self.answer_log: list[dict] = []
        self.lock = threading.Lock()

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def answer(self, question, passages):
        result = self.inner.answer(question, passages)
        with self.lock:  # raw model answer (before application verification) kept for diagnosis; question text is not stored
            self.answer_log.append({"text": result.text, "cited": [{"index": c.index, "quote": c.quote} for c in result.cited],
                                    "passages": len(passages)})
        return result

    def extract_fields(self, report_text, profile=None):
        from app.ai.llm import LLMOutputInvalid
        t0 = time.perf_counter()
        try:
            fields = self.inner.extract_fields(report_text, profile) if profile is not None else self.inner.extract_fields(report_text)
            entry = {"text_sha": hashlib.sha256(report_text.encode()).hexdigest()[:12], "valid": True, "fields": fields}
            return fields
        except LLMOutputInvalid as exc:
            entry = {"text_sha": hashlib.sha256(report_text.encode()).hexdigest()[:12], "valid": False, "error": str(exc)[:200]}
            raise
        finally:
            entry["seconds"] = round(time.perf_counter() - t0, 3)
            with self.lock:
                self.extract_log.append(entry)


def ingest_corpus(client, headers, tenant, passages, settings_note, rows):
    base = DS / "corpus" / tenant
    files = sorted(p for p in base.rglob("*") if p.is_file())
    files.sort(key=lambda p: (0 if "superseded" in p.parts else 1, p.name))  # superseded versions first, current versions after
    for path in files:
        kind = file_kind(passages, tenant, path.name)
        t0 = time.perf_counter()
        r = client.post("/api/v1/documents", headers=headers, data={"kind": kind}, files={"file": (path.name, path.read_bytes())})
        r.raise_for_status()
        rows.append({"tenant": tenant, "file": path.name, "superseded_copy": "superseded" in path.parts, "status": r.json()["status"],
                     "chunks": r.json()["chunk_count"], "seconds": round(time.perf_counter() - t0, 3)})


def tenants_setup(settings, owner, app_client):
    """Apex via the benchmark tenant helper; Meridian via the public onboarding path (profile only, documents ingested by this runner)."""
    p3.PASSWORD = PASSWORD
    urls = {}
    servers = {}
    t_app = ticketing_app.create_app(api_key=TICKETING_KEY)
    servers["ticketing"] = (p3.ServerThread(t_app), t_app)
    servers["inventory"] = (p3.ServerThread(inventory_app.create_app(api_key="")), None)
    sd_app = servicedesk_app.create_app(api_key=SERVICEDESK_KEY)
    servers["servicedesk"] = (p3.ServerThread(sd_app), sd_app)
    servers["fleet"] = (p3.ServerThread(fleet_app.create_app(api_key="")), None)
    servers["crm"] = (p3.ServerThread(crm_app.create_app(api_key="")), None)
    for name, (srv, _) in servers.items():
        urls[name] = srv.start()
    policy = egress.EgressPolicy(production=False)
    egress.set_policy(policy)
    for u in urls.values():
        policy.add_dev_mock("*", u)
    os.environ["BENCH_TICKETING_KEY"] = TICKETING_KEY
    os.environ["MERIDIAN_SERVICEDESK_KEY"] = SERVICEDESK_KEY
    apex_id, apex_slug, apex_users = p3.make_tenant(owner, urls["ticketing"], urls["inventory"])
    cfg = json.loads((ROOT / "onboarding" / "meridian.json").read_text(encoding="utf-8"))
    cfg["documents"] = []
    cfg["tenant"]["slug"] = "meridian-eval2"
    for m in cfg["members"]:
        m["email"] = m["email"].replace("@", ".eval2@")
    for c in cfg["connectors"]:
        c["base_url"] = {"ticketing": urls["servicedesk"], "fleet": urls["fleet"], "crm": urls["crm"]}[c["kind"]]
    platform_email = "platform.eval2@example.test"
    with owner.begin() as conn:
        conn.execute(text("INSERT INTO users (email, full_name, password_hash, is_platform_admin) VALUES (:e, 'Platform', :p, true) ON CONFLICT (email) DO NOTHING"),
                     {"e": platform_email, "p": hash_password(PASSWORD)})
    summary = onboard(cfg, app_client, password=PASSWORD, platform=(platform_email, PASSWORD), log=lambda *_: None)
    mer_users = {m["role"]: m["email"] for m in cfg["members"]}
    return {"apex": {"id": apex_id, "slug": apex_slug, "users": apex_users},
            "meridian": {"id": summary["tenant_id"], "slug": "meridian-eval2", "users": mer_users}}, servers, urls


def login(client, tenant, role):
    r = client.post("/api/v1/auth/login", json={"email": tenant["users"][role], "password": PASSWORD, "tenant": tenant["slug"]})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


class FreshHeaders(dict):
    """Per-tenant engineer auth headers; re-logs in before the access token (short-lived by design) can expire."""

    def __init__(self, client, tenants, role, max_age=480):
        super().__init__()
        self.client, self.tenants, self.role, self.max_age, self.issued = client, tenants, role, max_age, {}

    def __getitem__(self, tenant):
        if tenant not in self.issued or time.time() - self.issued[tenant] > self.max_age:
            super().__setitem__(tenant, login(self.client, self.tenants[tenant], self.role))
            self.issued[tenant] = time.time()
        return super().__getitem__(tenant)


def retrieval_pass(db, tenant, embedder, queries, out_rows, modes=("hybrid", "vector", "fts")):
    for q in queries:
        rec = {"id": q["id"], "tenant": q["tenant"], "modes": {}}
        for mode in modes:
            with db.session(tenant["id"]) as s:
                t0 = time.perf_counter()
                hits = search(s, tenant["id"], q["query"], embedder, k=10, mode=mode)
                dt_s = time.perf_counter() - t0
            rec["modes"][mode] = {"seconds": round(dt_s, 4),
                                  "ranked": [{"file": h.filename, "unit": h.page_number if h.page_number is not None else h.record_id,
                                              "similarity": round(h.similarity, 4), "suspicious": h.suspicious} for h in hits]}
        out_rows.append(rec)


def qa_pass(client, headers, llm, queries, out_rows, rep):
    for q in queries:
        n0 = len(getattr(llm.inner, "calls", []))
        a0 = len(llm.answer_log)
        t0 = time.perf_counter()
        r = client.post("/api/v1/ai/ask", headers=headers[q["tenant"]], json={"question": q["query"]})
        wall = time.perf_counter() - t0
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        out_rows.append({"id": q["id"], "tenant": q["tenant"], "rep": rep, "status": r.status_code, "wall_s": round(wall, 3),
                         "answer": body.get("answer"), "grounded": body.get("grounded"), "insufficient_evidence": body.get("insufficient_evidence"),
                         "citations": body.get("citations", []), "problems": body.get("problems", []), "excluded_suspicious": body.get("excluded_suspicious", []),
                         "error": body.get("error") if r.status_code >= 400 else None, "llm_calls": getattr(llm.inner, "calls", [])[n0:],
                         "raw_llm_answers": llm.answer_log[a0:]})


def extraction_pass(client, headers, llm, cases, out_rows, rep):
    for c in cases:
        n_raw = len(llm.extract_log)
        n_calls = len(getattr(llm.inner, "calls", []))
        t0 = time.perf_counter()
        r = client.post("/api/v1/incidents/extract", headers=headers[c["tenant"]], json={"report_text": c["text"]})
        wall = time.perf_counter() - t0
        body = r.json()
        row = {"id": c["id"], "tenant": c["tenant"], "rep": rep, "status": r.status_code, "wall_s": round(wall, 3),
               "raw": llm.extract_log[n_raw:], "llm_calls": getattr(llm.inner, "calls", [])[n_calls:]}
        if r.status_code < 300:
            row.update(incident_id=body["id"], asset_id=body.get("asset_id"), category=body.get("category"), priority=body.get("priority"),
                       review_status=body.get("review_status"), extraction_backend=body.get("extraction_backend"), n_citations=len(body.get("citations", [])),
                       asset_verified=body.get("asset_verified"), notes=body.get("notes", []), measurements=body.get("measurements"))
        else:
            row["error_code"] = (body.get("error") or {}).get("code")
        out_rows.append(row)


def workflow_pass(client, headers, tenants, cases, llm, worker_db, out, n_per_tenant=3):
    """Authorized path end to end (extract -> review if required -> draft -> approval -> outbox -> mock submission), plus negative checks."""
    results = []
    cfg = worker_mod.WorkerConfig(backoff_base=0, http_timeout=5)
    for tname in ("apex", "meridian"):
        picks = [c for c in cases if c["tenant"] == tname and c["review_expectation"] == "may_proceed" and c["expected_outcome"] == "incident"][:n_per_tenant]
        for c in picks:
            eng, sup = headers[tname], login(client, tenants[tname], "maintenance_supervisor")
            t0 = time.perf_counter()
            inc = client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": c["text"]}).json()
            if "review_status" not in inc:
                results.append({"case": c["id"], "tenant": tname, "error": inc.get("error"), "final_state": None})
                continue
            t_extract = time.perf_counter()
            reviewed = False
            if inc["review_status"] == "needs_review":
                reviewed = client.post(f"/api/v1/incidents/{inc['id']}/review", headers=sup, json={"decision": "accept", "comment": "baseline workflow review"}).status_code == 200
            t = client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc["id"]})
            row = {"case": c["id"], "tenant": tname, "review_required": inc["review_status"] == "needs_review", "reviewed": reviewed, "draft_status": t.status_code}
            if t.status_code == 201:
                tid = t.json()["id"]
                row["submit_before_approval"] = client.post(f"/api/v1/tickets/{tid}/submit", headers=eng).status_code
                client.post(f"/api/v1/tickets/{tid}/request-approval", headers=eng)
                row["engineer_approval_status"] = client.post(f"/api/v1/approvals/{tid}/decision", headers=eng, json={"decision": "approved"}).status_code
                t_appr = time.perf_counter()
                row["supervisor_approval_status"] = client.post(f"/api/v1/approvals/{tid}/decision", headers=sup, json={"decision": "approved"}).status_code
                outcomes = worker_mod.drain(worker_db, cfg)
                final = client.get(f"/api/v1/tickets/{tid}", headers=eng).json()
                row.update(worker_outcomes=outcomes, final_state=final["state"], external_ticket_id=final.get("external_ticket_id"),
                           extract_s=round(t_extract - t0, 3), approval_to_submitted_s=round(time.perf_counter() - t_appr, 3), total_s=round(time.perf_counter() - t0, 3))
            results.append(row)
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev")
    ap.add_argument("--allow-heldout", action="store_true", help="only for the single frozen final evaluation")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0, help="smoke runs only: take the first N queries/cases per tenant")
    ap.add_argument("--out-root", default=str(ROOT / "evaluation" / "reports" / "phase8"))
    ap.add_argument("--label", default="baseline")
    args = ap.parse_args()
    if args.split != "dev" and not args.allow_heldout:
        sys.exit("refusing to run a held-out split without --allow-heldout (protocol: dev only before the frozen final evaluation)")

    started = dt.datetime.now(dt.timezone.utc)
    run_id = f"{args.label}-{started:%Y%m%dT%H%M%SZ}"
    out = Path(args.out_root) / run_id
    out.mkdir(parents=True, exist_ok=True)
    print("run", run_id, flush=True)
    import subprocess
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "--", "backend", "frontend/src"], capture_output=True, text=True, cwd=ROOT).stdout.strip())

    p3.BENCH_DB = EVAL_DB
    base = get_settings(EVAL_DB)
    settings = dataclasses.replace(base, jwt_secret="eval2-" + uuid.uuid4().hex, llm_backend="ollama", embedding_backend="sentence_transformers")
    p3.setup(settings)
    owner = create_engine(settings.url("owner"))
    app_db, worker_db = Database(settings, role="app"), Database(settings, role="worker")
    from app.ai.embeddings import get_embedder
    from app.ai.llm import get_llm
    t_load = time.perf_counter()
    embedder = get_embedder("sentence_transformers")
    inner = get_llm("ollama")
    embedder_load_s = round(time.perf_counter() - t_load, 3)
    llm = RecordingLLM(inner)
    domain_routes.get_llm = lambda _name: llm
    app = create_app(settings, app_db)
    client = TestClient(app)
    logging.getLogger("eaop").setLevel(logging.WARNING)
    tenants, servers, urls = tenants_setup(settings, owner, client)
    sampler = p3.Sampler()
    sampler.start()
    windows = {}

    def phase(name):
        class P:
            def __enter__(self_):
                self_.t0 = time.time()

            def __exit__(self_, *a):
                windows[name] = (self_.t0, time.time())
        return P()

    passages = load("passages.jsonl")
    headers = FreshHeaders(client, tenants, "support_engineer")
    ingest_rows = []
    with phase("ingestion"):
        for t in ("apex", "meridian"):
            ingest_corpus(client, headers[t], t, passages, "", ingest_rows)
    with owner.connect() as c:
        storage = {r[0]: r[1] for r in c.execute(text(
            "SELECT relname, pg_total_relation_size(oid) FROM pg_class WHERE relname IN ('document_chunks','documents','document_versions')")).all()}
        chunk_counts = {r[0]: r[1] for r in c.execute(text("SELECT t.slug, count(*) FROM document_chunks c JOIN tenants t ON t.id = c.tenant_id GROUP BY t.slug")).all()}
        current_counts = {r[0]: r[1] for r in c.execute(text("SELECT t.slug, count(*) FROM document_chunks c JOIN tenants t ON t.id = c.tenant_id WHERE c.is_current GROUP BY t.slug")).all()}
    with owner.begin() as c:  # post-ingestion statistics refresh so planner choices are stable across the timed passes (recorded in the manifest)
        c.execute(text("ANALYZE document_chunks"))
    queries = [q for q in load("queries.jsonl") if q["split"] == args.split]
    cases = [c for c in load("incidents.jsonl") if c["split"] == args.split]
    if args.limit:
        queries = [q for t in ("apex", "meridian") for q in [x for x in queries if x["tenant"] == t][:args.limit]]
        cases = [c for t in ("apex", "meridian") for c in [x for x in cases if x["tenant"] == t][:args.limit]]

    results = {"run_id": run_id, "evidence_class": "real_ai", "split": args.split, "embedder_load_s": embedder_load_s}
    # retrieval (deterministic given the embeddings; also run twice to record determinism)
    with phase("retrieval"):
        ret_rows, ret_rows2 = [], []
        for t in ("apex", "meridian"):
            retrieval_pass(app_db, tenants[t], embedder, [q for q in queries if q["tenant"] == t], ret_rows)
        for t in ("apex", "meridian"):
            retrieval_pass(app_db, tenants[t], embedder, [q for q in queries if q["tenant"] == t], ret_rows2, modes=("hybrid",))
    (out / "retrieval.jsonl").write_text("\n".join(json.dumps(r) for r in ret_rows) + "\n", encoding="utf-8")
    (out / "retrieval_repeat.jsonl").write_text(chr(10).join(json.dumps(r) for r in ret_rows2) + chr(10), encoding="utf-8")
    # cold start (first call after load) recorded separately, then warm runs
    with phase("warmup"):
        t0 = time.perf_counter()
        client.post("/api/v1/ai/ask", headers=headers["apex"], json={"question": "warm-up question about pump lubrication"})
        results["llm_cold_start_s"] = round(time.perf_counter() - t0, 3)
        llm.inner.calls.clear()
        llm.extract_log.clear()
    qa_all, ex_all = [], []
    for rep in range(1, args.reps + 1):
        with phase(f"qa_rep{rep}"):
            rows = []
            qa_pass(client, headers, llm, queries, rows, rep)
        qa_all += rows
        (out / f"qa_rep{rep}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        print(f"qa rep {rep} done", flush=True)
        with phase(f"extraction_rep{rep}"):
            erows = []
            extraction_pass(client, headers, llm, cases, erows, rep)
        ex_all += erows
        (out / f"extraction_rep{rep}.jsonl").write_text("\n".join(json.dumps(r) for r in erows) + "\n", encoding="utf-8")
        print(f"extraction rep {rep} done", flush=True)
    with phase("workflow"):
        wf = workflow_pass(client, headers, tenants, cases, llm, worker_db, out)
    (out / "workflow.json").write_text(json.dumps(wf, indent=1), encoding="utf-8")
    # concurrency probe: N simultaneous ask requests; the application limits concurrent inference and answers 429 when busy
    conc = {}
    qs = [q for q in queries if q["answerable"]][:8]
    for n in (1, 2, 4):
        with phase(f"concurrency{n}"):
            lat, codes = [], []
            lock = threading.Lock()

            def one(q, lat=lat, codes=codes, lock=lock):
                t0 = time.perf_counter()
                r = client.post("/api/v1/ai/ask", headers=headers[q["tenant"]], json={"question": q["query"]})
                with lock:
                    lat.append(time.perf_counter() - t0)
                    codes.append(r.status_code)
            t_start = time.perf_counter()
            for i in range(0, len(qs), n):
                th = [threading.Thread(target=one, args=(q,)) for q in qs[i:i + n]]
                [x.start() for x in th]
                [x.join() for x in th]
            conc[n] = {"requests": len(qs), "wall_s": round(time.perf_counter() - t_start, 2), "latencies_s": [round(x, 3) for x in lat], "status_codes": codes}
    results["concurrency"] = conc
    sampler.stop()
    results["resources"] = {name: sampler.window(*w) for name, w in windows.items()}
    results["window_seconds"] = {name: round(w[1] - w[0], 1) for name, w in windows.items()}
    results["ingestion"] = ingest_rows
    results["storage_bytes"] = storage
    results["chunks"] = {"total_by_tenant": chunk_counts, "current_by_tenant": current_counts}
    with owner.connect() as c:
        results["external"] = {"ticketing_tickets": len(servers["ticketing"][1].state.mock.tickets),
                               "servicedesk_tickets": len(servers["servicedesk"][1].state.mock.tickets)}
    finished = dt.datetime.now(dt.timezone.utc)
    hw = p3.capture_hardware.collect()
    prompts = p3.versions(inner, embedder)
    manifest = {"run_id": run_id, "label": args.label, "command": "python " + " ".join(sys.argv), "started_utc": started.isoformat(),
                "finished_utc": finished.isoformat(), "duration_s": round((finished - started).total_seconds(), 1), "git_commit": commit,
                "working_tree_dirty_in_app_code": dirty, "python": platform.python_version(), "os": platform.platform(), "hardware": hw,
                "versions": prompts, "node": subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip(),
                "dataset": {"name": "eval-v2", "version": "eval-v2.0", "split": args.split, "manifest_sha256": hashlib.sha256((DS / "MANIFEST.sha256").read_bytes()).hexdigest(),
                            "frozen_splits_sha256": hashlib.sha256((DS / "frozen_splits.json").read_bytes()).hexdigest(), "queries": len(queries), "cases": len(cases)},
                "runtime": {"reps": args.reps, "ollama_options": getattr(inner, "options", None), "evidence_threshold": embedder.evidence_threshold,
                            "embedding_profile": embedder.profile.label(), "max_concurrent_llm": settings.max_concurrent_llm},
                "isolation": f"database {EVAL_DB}; tenants apex-benchmark and meridian-eval2; mocks on loopback; egress dev-mock policy for those origins only"}
    (out / "results.json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str), encoding="utf-8")
    print("written", out, flush=True)
    app_db.dispose()
    worker_db.dispose()


if __name__ == "__main__":
    main()
