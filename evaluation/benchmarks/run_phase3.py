"""Phase 3 evaluation harness: retrieval, grounded answers, citations, structured extraction, workflow latency.

Usage (see docs/evaluation/phase3-method.md):
  python evaluation/benchmarks/run_phase3.py --embedding sentence_transformers --llm ollama
  python evaluation/benchmarks/run_phase3.py --embedding deterministic --llm deterministic   # functional baseline

Runs in an ISOLATED database (eaop_bench, dropped and recreated every run) with its own tenant, so it
never touches the demo (apex-industrial) or UI fixture (apex-uitest) data. Every result file carries the
backends, model identifiers/digests, hardware, dataset hash, command and timestamp. Results from the
deterministic backends are labelled functional-only and are NOT AI performance.
"""
import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import logging
import statistics
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("backend", "mock-services/ticketing", "mock-services/inventory", "scripts"):
    sys.path.insert(0, str(ROOT / p))

import capture_hardware  # noqa: E402
import inventory_app  # noqa: E402
import ticketing_app  # noqa: E402
import uvicorn  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from app.ai import rules  # noqa: E402
from app.ai.embeddings import get_embedder  # noqa: E402
from app.ai.llm import LLMOutputInvalid, get_llm  # noqa: E402
from app.ai.rag import answer_question, has_evidence  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.errors import AppError  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.database.session import Database  # noqa: E402
from app.main import create_app  # noqa: E402
from app.retrieval.search import search  # noqa: E402
from app.services.incident_service import extract_incident  # noqa: E402
from app.workflows import worker as worker_mod  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

DATASET = ROOT / "evaluation" / "datasets" / "apex-eval-v1"
DEMO_SAMPLES = ROOT / "sample-data" / "customer-a"
BENCH_DB = "eaop_bench"
PASSWORD = "Bench-" + uuid.uuid4().hex[:12]  # generated per run, never stored
TICKETING_KEY = "bench-ticketing-" + uuid.uuid4().hex[:8]
KINDS = {  # file -> document kind
    "eval_equipment_register.csv": "equipment_register", "eval_incident_history.csv": "incident_history",
    "eval_inspection_2026q2.pdf": "inspection_report", "eval_inspection_2026q3.pdf": "inspection_report",
    **{n: "equipment_manual" for n in (
        "eval_cp200_pump_manual.pdf", "eval_em55_motor_manual.pdf", "eval_cc300_compressor_manual.pdf",
        "eval_cv400_conveyor_manual.pdf", "eval_gb500_gearbox_manual.pdf", "eval_ht600_heat_exchanger_manual.pdf")},
}
DEMO_KINDS = {"apex_cp200_pump_manual.pdf": "equipment_manual", "apex_inspection_report_2026q3.pdf": "inspection_report",
              "equipment_register.csv": "equipment_register", "incident_history.csv": "incident_history",
              "maintenance_log.csv": "maintenance_log"}


# ---------------------------------------------------------------------------------------------------------
def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return round(s[0], 4)
    pos = (len(s) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (pos - lo), 4)


def dist(values: list[float]) -> dict:
    return {"n": len(values), "median": pct(values, 0.5), "p95": pct(values, 0.95),
            "min": round(min(values), 4) if values else None, "max": round(max(values), 4) if values else None,
            "mean": round(statistics.mean(values), 4) if values else None}


class ServerThread:
    def __init__(self, app):
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self) -> str:
        self.thread.start()
        deadline = time.time() + 10
        while not self.server.started and time.time() < deadline:
            time.sleep(0.05)
        return f"http://127.0.0.1:{self.server.servers[0].sockets[0].getsockname()[1]}"


class Sampler:
    """Samples system CPU %, free RAM, Ollama and this process's working set every few seconds."""

    SCRIPT = (
        "$c=(Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor -Filter \"Name='_Total'\").PercentProcessorTime;"
        "$o=Get-CimInstance Win32_OperatingSystem;"
        "$p=(Get-Process | Where-Object {{ $_.ProcessName -match 'ollama|llama' }} | Measure-Object WorkingSet64 -Sum).Sum;"
        "$m=(Get-Process -Id {pid}).WorkingSet64;"
        "ConvertTo-Json -Compress @{{cpu=$c;free_kb=$o.FreePhysicalMemory;total_kb=$o.TotalVisibleMemorySize;"
        "ollama=$p;python=$m}}"
    )

    def __init__(self, interval: float = 3.0):
        self.interval, self.samples, self._stop = interval, [], threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        import os
        script = self.SCRIPT.format(pid=os.getpid())
        self.error = None
        while not self._stop.is_set():
            try:
                out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True,
                                     text=True, timeout=20, check=False).stdout
                d = json.loads(out)
                self.samples.append({"t": time.time(), "cpu_pct": d["cpu"], "free_mb": d["free_kb"] / 1024,
                                     "total_mb": d["total_kb"] / 1024,
                                     "ollama_mb": (d["ollama"] or 0) / 1048576, "python_mb": d["python"] / 1048576})
            except (OSError, ValueError, subprocess.SubprocessError, KeyError):
                pass
            self._stop.wait(self.interval)

    def start(self):
        self.thread.start()

    def stop(self):
        self._stop.set()
        self.thread.join(timeout=10)

    def window(self, t0: float, t1: float) -> dict:
        s = [x for x in self.samples if t0 <= x["t"] <= t1]
        if not s:
            return {"samples": 0}
        return {"samples": len(s), "cpu_pct_mean": round(statistics.mean(x["cpu_pct"] for x in s), 1),
                "cpu_pct_peak": max(x["cpu_pct"] for x in s),
                "ollama_working_set_mb_peak": round(max(x["ollama_mb"] for x in s), 1),
                "python_working_set_mb_peak": round(max(x["python_mb"] for x in s), 1),
                "system_free_ram_mb_min": round(min(x["free_mb"] for x in s), 1),
                "system_total_ram_mb": round(s[0]["total_mb"], 1)}


# ---------------------------------------------------------------------------------------------------------
def setup(settings):
    admin = create_engine(settings.url("owner").rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {BENCH_DB} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {BENCH_DB}"))
    admin.dispose()
    cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend" / "migrations"))
    cfg.attributes["url"] = settings.url("owner")
    command.upgrade(cfg, "head")


def make_tenant(owner, ticketing_url, inventory_url):
    slug = "apex-benchmark"
    with owner.begin() as conn:
        tid = conn.execute(text("INSERT INTO tenants (slug, name) VALUES (:s, :n) RETURNING id"),
                           {"s": slug, "n": "[BENCHMARK] Apex evaluation tenant (synthetic)"}).scalar()
        pw = hash_password(PASSWORD)
        users = {}
        for role in ("tenant_admin", "maintenance_supervisor", "support_engineer", "read_only_auditor"):
            email = f"{role}@bench.example.test"
            uid = conn.execute(text("INSERT INTO users (email, full_name, password_hash) VALUES (:e, :n, :p) RETURNING id"),
                               {"e": email, "n": role, "p": pw}).scalar()
            conn.execute(text("INSERT INTO memberships (tenant_id, user_id, role) VALUES (:t, :u, :r)"),
                         {"t": tid, "u": uid, "r": role})
            users[role] = email
        conn.execute(text("INSERT INTO connectors (tenant_id, kind, name, base_url, secret_ref) VALUES "
                          "(:t, 'ticketing', 'bench-ticketing', :u, 'BENCH_TICKETING_KEY')"), {"t": tid, "u": ticketing_url})
        conn.execute(text("INSERT INTO connectors (tenant_id, kind, name, base_url) VALUES (:t, 'inventory', "
                          "'bench-inventory', :u)"), {"t": tid, "u": inventory_url})
    return str(tid), slug, users


def login(client, slug, users, role):
    r = client.post("/api/v1/auth/login", json={"email": users[role], "password": PASSWORD, "tenant": slug})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def unit_of(filename, page, record_id):
    return (filename, page if page is not None else record_id)


# ---------------------------------------------------------------------------------------------------------
def retrieval_eval(db, tenant_id, embedder, queries, k=5, mode="hybrid"):
    rows, lat = [], []
    with db.session(tenant_id) as s:
        for q in queries:
            t0 = time.perf_counter()
            hits = search(s, tenant_id, q["query"], embedder, k=k, mode=mode)
            lat.append(time.perf_counter() - t0)
            retrieved = [unit_of(h.filename, h.page_number, h.record_id) for h in hits]
            relevant = {(r["file"], r["unit"]) for r in q["relevant"]}
            in_top = sum(1 for u in retrieved if u in relevant)  # chunk-level hits (several chunks may share a unit)
            found = relevant & set(retrieved)
            rank = next((i for i, u in enumerate(retrieved, 1) if u in relevant), None)
            gate = any((not h.suspicious) and has_evidence(h, embedder) for h in hits)
            rows.append({"id": q["id"], "type": q["type"], "answerable": q["answerable"], "retrieved": retrieved,
                         "relevant": sorted(map(list, relevant)), "recall": (len(found) / len(relevant)) if relevant else None,
                         "precision": in_top / k if relevant else None, "rank": rank, "evidence_gate": gate,
                         "top_similarity": round(hits[0].similarity, 4) if hits else None,
                         "latency_s": round(lat[-1], 4)})
    return rows, lat


def summarize_retrieval(rows):
    ans = [r for r in rows if r["answerable"]]
    unans = [r for r in rows if not r["answerable"]]
    out = {
        "answerable_queries": len(ans),
        "recall_at_5": round(statistics.mean(r["recall"] for r in ans), 4) if ans else None,
        "precision_at_5": round(statistics.mean(r["precision"] for r in ans), 4) if ans else None,
        "mrr": round(statistics.mean((1 / r["rank"]) if r["rank"] else 0 for r in ans), 4) if ans else None,
        "hit_at_1": sum(1 for r in ans if r["rank"] == 1),
        "queries_with_relevant_in_top5": sum(1 for r in ans if r["rank"]),
        "evidence_gate_pass_answerable": sum(1 for r in ans if r["evidence_gate"]),
        "unanswerable_queries": len(unans),
        "evidence_gate_blocks_unanswerable": sum(1 for r in unans if not r["evidence_gate"]),
        "by_type": {},
    }
    for t in sorted({r["type"] for r in ans}):
        sub = [r for r in ans if r["type"] == t]
        out["by_type"][t] = {"n": len(sub), "recall_at_5": round(statistics.mean(r["recall"] for r in sub), 4),
                             "precision_at_5": round(statistics.mean(r["precision"] for r in sub), 4)}
    return out


def calibrate_threshold(db, tenant_id, embedder, dev_queries):
    """Choose the evidence threshold on the DEV split only (max balanced accuracy; ties -> higher threshold)."""
    original = embedder.evidence_threshold
    table = []
    with db.session(tenant_id) as s:
        cached = [(q, search(s, tenant_id, q["query"], embedder, k=5)) for q in dev_queries]
    for thr in [round(0.15 + 0.05 * i, 2) for i in range(10)]:
        embedder.evidence_threshold = thr
        tp = sum(1 for q, h in cached if q["answerable"] and any((not x.suspicious) and has_evidence(x, embedder) for x in h))
        tn = sum(1 for q, h in cached if not q["answerable"] and not any((not x.suspicious) and has_evidence(x, embedder) for x in h))
        pos = sum(1 for q, _ in cached if q["answerable"]) or 1
        neg = sum(1 for q, _ in cached if not q["answerable"]) or 1
        table.append({"threshold": thr, "balanced_accuracy": round((tp / pos + tn / neg) / 2, 4),
                      "answerable_passed": tp, "unanswerable_blocked": tn})
    best = max(table, key=lambda r: (r["balanced_accuracy"], r["threshold"]))
    embedder.evidence_threshold = best["threshold"]
    return {"initial_threshold": original, "chosen_threshold": best["threshold"], "dev_table": table,
            "dev_queries": len(dev_queries)}


def qa_eval(db, tenant_id, embedder, llm, queries):
    rows = []
    with db.session(tenant_id) as s:
        for q in queries:
            n0 = len(getattr(llm, "calls", []))
            t0 = time.perf_counter()
            res = answer_question(s, tenant_id, q["query"], embedder, llm)
            wall = time.perf_counter() - t0
            stats = getattr(llm, "calls", [])[n0:]
            relevant = {(r["file"], r["unit"]) for r in q["relevant"]}
            cites = [{"unit": list(unit_of(c["filename"], c["page_number"], c["record_id"])),
                      "correct": unit_of(c["filename"], c["page_number"], c["record_id"]) in relevant} for c in res.citations]
            text_l = res.answer.lower()
            quotes_l = " ".join(c["quote"].lower() for c in res.citations)
            facts = q["key_facts"]
            rows.append({"id": q["id"], "answerable": q["answerable"], "grounded": res.grounded,
                         "insufficient_evidence": res.insufficient_evidence, "problems": res.problems,
                         "answer": res.answer, "citations": cites, "n_citations": len(cites),
                         "facts_in_answer": all(f.lower() in text_l for f in facts) if facts else None,
                         "facts_in_answer_or_quotes": all(f.lower() in text_l or f.lower() in quotes_l for f in facts) if facts else None,
                         "wall_s": round(wall, 3), "llm_calls": stats})
    return rows


def summarize_qa(rows):
    ans = [r for r in rows if r["answerable"]]
    unans = [r for r in rows if not r["answerable"]]
    cites = [c for r in ans for c in r["citations"]]
    llm_calls = [c for r in rows for c in r["llm_calls"]]
    return {
        "answerable_queries": len(ans), "unanswerable_queries": len(unans),
        "grounded_answers": sum(1 for r in ans if r["grounded"]),
        "groundedness_rate": round(sum(1 for r in ans if r["grounded"]) / len(ans), 4) if ans else None,
        "false_abstentions": sum(1 for r in ans if r["insufficient_evidence"]),
        "withheld_unverified_or_invalid": sum(1 for r in ans if not r["grounded"] and not r["insufficient_evidence"]),
        "correct_abstentions": sum(1 for r in unans if r["insufficient_evidence"]),
        "wrongly_answered_unanswerable": sum(1 for r in unans if r["grounded"]),
        "citations_emitted": len(cites),
        "citation_correctness": round(sum(1 for c in cites if c["correct"]) / len(cites), 4) if cites else None,
        "answers_with_all_key_facts": sum(1 for r in ans if r["facts_in_answer"]),
        "answers_with_all_key_facts_or_in_quotes": sum(1 for r in ans if r["facts_in_answer_or_quotes"]),
        "latency_wall_s": dist([r["wall_s"] for r in rows]),
        "llm_inference_s": dist([c["wall_s"] for c in llm_calls]) if llm_calls else None,
        "tokens_per_s": dist([c["tokens_per_s"] for c in llm_calls if c.get("tokens_per_s")]) if llm_calls else None,
        "output_tokens": dist([c["output_tokens"] for c in llm_calls if c.get("output_tokens") is not None]) if llm_calls else None,
        "prompt_tokens": dist([c["prompt_tokens"] for c in llm_calls if c.get("prompt_tokens") is not None]) if llm_calls else None,
        "llm_schema_valid": f"{sum(1 for c in llm_calls if c.get('valid'))}/{len(llm_calls)}" if llm_calls else None,
    }


def structured_eval(db, tenant_id, embedder, llm, reports, user_id):
    rows = []
    for rp in reports:
        row = {"id": rp["id"]}
        t0 = time.perf_counter()
        n0 = len(getattr(llm, "calls", []))
        try:
            f = llm.extract_fields(rp["text"])
            row["model_valid"] = True
            row["asset_ok"] = (f.get("asset_id") == rp["asset_id"])
            row["category_ok"] = (f.get("category") == rp["category"])
            row["symptoms_nonempty"] = bool(f.get("symptoms"))
            row["vibration_ok"] = (f.get("vibration_mm_s") == rp["vibration_mm_s"]) if rp["vibration_mm_s"] is not None else (f.get("vibration_mm_s") is None)
            row["smoke_ok"] = (bool(f.get("smoke_or_fire")) == rp["smoke_or_fire"])
            expected_fields = {"category": rp["category"], "vibration_mm_s": rp["vibration_mm_s"], "smoke_or_fire": rp["smoke_or_fire"]}
            row["priority_ok"] = rules.decide_priority(f) == rules.decide_priority(expected_fields)
        except LLMOutputInvalid as exc:
            row.update(model_valid=False, error=str(exc))
        row["extract_wall_s"] = round(time.perf_counter() - t0, 3)
        row["llm_calls"] = getattr(llm, "calls", [])[n0:]
        # Full pipeline outcome (retrieval + guidance + validation); incident rows go to the isolated bench DB.
        t1 = time.perf_counter()
        with db.session(tenant_id, user_id) as s:
            try:
                inc = extract_incident(s, tenant_id=tenant_id, user_id=user_id, report_text=rp["text"],
                                       embedder=embedder, llm=llm)
                s.commit()
                row["pipeline"] = "ok"
                row["pipeline_asset_ok"] = inc.asset_id == rp["asset_id"]
                row["pipeline_fallback"] = "rules-fallback" in inc.extraction_backend
            except AppError as exc:
                s.rollback()
                row["pipeline"] = exc.code
                row["pipeline_asset_ok"] = (rp["asset_id"] is None and exc.code == "asset_not_identified")
        row["pipeline_wall_s"] = round(time.perf_counter() - t1, 3)
        rows.append(row)
    return rows


def summarize_structured(rows):
    valid = [r for r in rows if r.get("model_valid")]
    n = len(rows)
    return {
        "reports": n, "model_output_schema_valid": len(valid),
        "model_output_validity_rate": round(len(valid) / n, 4) if n else None,
        "asset_id_correct": sum(1 for r in valid if r["asset_ok"]),
        "category_correct": sum(1 for r in valid if r["category_ok"]),
        "symptoms_present": sum(1 for r in valid if r["symptoms_nonempty"]),
        "vibration_correct": sum(1 for r in valid if r["vibration_ok"]),
        "smoke_flag_correct": sum(1 for r in valid if r["smoke_ok"]),
        "priority_correct": sum(1 for r in valid if r["priority_ok"]),
        "pipeline_ok_or_expected_rejection": sum(1 for r in rows if r["pipeline"] == "ok" or r["pipeline_asset_ok"]),
        "pipeline_used_rules_fallback": sum(1 for r in rows if r.get("pipeline_fallback")),
        "extract_latency_s": dist([r["extract_wall_s"] for r in rows]),
        "pipeline_latency_s": dist([r["pipeline_wall_s"] for r in rows]),
    }


def e2e_eval(client, slug, users, worker_db, ticketing, n_runs, report_text):
    eng, sup = login(client, slug, users, "support_engineer"), login(client, slug, users, "maintenance_supervisor")
    runs = []
    cfg = worker_mod.WorkerConfig(backoff_base=0, http_timeout=5)
    for i in range(n_runs):
        marks = {"start": time.perf_counter()}
        inc = client.post("/api/v1/incidents/extract", headers=eng, json={"report_text": report_text})
        inc.raise_for_status()
        marks["extract"] = time.perf_counter()
        t = client.post("/api/v1/tickets", headers=eng, json={"incident_id": inc.json()["id"]})
        t.raise_for_status()
        tid = t.json()["id"]
        client.post(f"/api/v1/tickets/{tid}/request-approval", headers=eng).raise_for_status()
        marks["draft_and_request"] = time.perf_counter()
        client.post(f"/api/v1/approvals/{tid}/decision", headers=sup, json={"decision": "approved", "comment": "bench"}).raise_for_status()
        marks["approve"] = time.perf_counter()
        outcomes = worker_mod.drain(worker_db, cfg)
        marks["submit"] = time.perf_counter()
        final = client.get(f"/api/v1/tickets/{tid}", headers=eng).json()
        runs.append({"run": i + 1, "state": final["state"], "external_ticket_id": final["external_ticket_id"],
                     "worker_outcomes": outcomes, "total_s": round(marks["submit"] - marks["start"], 3),
                     "extract_s": round(marks["extract"] - marks["start"], 3),
                     "draft_and_request_s": round(marks["draft_and_request"] - marks["extract"], 3),
                     "approve_s": round(marks["approve"] - marks["draft_and_request"], 3),
                     "submit_s": round(marks["submit"] - marks["approve"], 3),
                     "incident_citations": len(inc.json()["citations"])})
    return runs, len(ticketing.state.mock.tickets)


def versions(llm, embedder):
    v = {"python": sys.version.split()[0]}
    for mod in ("torch", "transformers", "sentence_transformers", "huggingface_hub", "numpy"):
        try:
            v[mod] = __import__(mod).__version__
        except ImportError:
            pass
    if hasattr(llm, "version"):
        v["ollama"] = llm.version()
        v["ollama_model"] = llm.model
        v["ollama_model_digest"] = llm.digest
        import hashlib as _h

        from app.ai import ollama_llm as _o
        v["prompt_version"] = _o.PROMPT_VERSION
        v["prompts_sha256"] = _h.sha256((_o.ANSWER_SYSTEM + _o.EXTRACT_SYSTEM + json.dumps(_o.ANSWER_SCHEMA)
                                         + json.dumps(_o.FIELDS_SCHEMA)).encode()).hexdigest()
        v["ollama_options"] = llm.options
    with create_engine(get_settings().url("owner")).connect() as c:
        v["postgres"] = c.execute(text("show server_version")).scalar()
        v["pgvector"] = c.execute(text("select extversion from pg_extension where extname='vector'")).scalar()
    v["embedding_profile"] = embedder.profile.label()
    v["embedding_evidence_threshold_used"] = embedder.evidence_threshold
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--embedding", required=True, choices=["deterministic", "sentence_transformers"])
    ap.add_argument("--llm", required=True, choices=["deterministic", "ollama"])
    ap.add_argument("--e2e-runs", type=int, default=5)
    ap.add_argument("--qa-repeats", type=int, default=1, help="extra QA passes used only for latency samples")
    ap.add_argument("--out-root", default=str(ROOT / "evaluation" / "reports" / "phase3"))
    ap.add_argument("--qa-split", choices=["test", "dev"], default="test",
                    help="dev is for prompt iteration only; reported results always use the held-out test split")
    ap.add_argument("--skip-qa", action="store_true")
    ap.add_argument("--skip-structured", action="store_true")
    args = ap.parse_args()

    real = args.llm == "ollama" and args.embedding == "sentence_transformers"
    started = dt.datetime.now(dt.timezone.utc)
    run_id = f"{started:%Y%m%dT%H%M%SZ}_{args.llm}_{args.embedding}"
    out = Path(args.out_root) / run_id
    out.mkdir(parents=True, exist_ok=True)
    print(f"run {run_id}")

    base = get_settings(BENCH_DB)
    settings = dataclasses.replace(base, jwt_secret="bench-" + uuid.uuid4().hex, llm_backend=args.llm,
                                   embedding_backend=args.embedding)
    import os
    os.environ["BENCH_TICKETING_KEY"] = TICKETING_KEY
    setup(settings)
    owner = create_engine(settings.url("owner"))
    t_app = ticketing_app.create_app(api_key=TICKETING_KEY)
    ticketing_url = ServerThread(t_app).start()
    inventory_url = ServerThread(inventory_app.create_app(api_key="")).start()
    tenant_id, slug, users = make_tenant(owner, ticketing_url, inventory_url)

    t_load = time.perf_counter()
    embedder = get_embedder(args.embedding)
    llm = get_llm(args.llm)
    embedder_load_s = round(time.perf_counter() - t_load, 3)
    sampler = Sampler()
    sampler.start()
    app_db, worker_db = Database(settings, role="app"), Database(settings, role="worker")
    client = TestClient(create_app(settings, app_db))
    logging.getLogger("eaop").setLevel(logging.WARNING)  # per-request logs would distort timing and flood output
    results = {"run_id": run_id, "evidence_class": "real_ai" if real else "functional_only_deterministic_not_ai_performance",
               "backends": {"llm": args.llm, "embedding": args.embedding}, "embedder_load_s": embedder_load_s, "phases": {}}
    windows = {}

    def phase(name):
        class P:
            def __enter__(self_):
                self_.t0 = time.time()

            def __exit__(self_, *a):
                windows[name] = (self_.t0, time.time())
        return P()

    queries = load_jsonl(DATASET / "queries.jsonl")
    dev = [q for q in queries if q["split"] == "dev"]
    test = [q for q in queries if q["split"] == "test"]
    reports = load_jsonl(DATASET / "reports.jsonl")

    # 1. ingestion
    eng = login(client, slug, users, "support_engineer")
    ingest_rows = []
    with phase("ingestion"):
        for folder, kinds in ((DATASET / "documents", KINDS), (DEMO_SAMPLES, DEMO_KINDS)):
            for name, kind in kinds.items():
                data = (folder / name).read_bytes()
                t0 = time.perf_counter()
                r = client.post("/api/v1/documents", headers=eng, data={"kind": kind}, files={"file": (name, data)})
                r.raise_for_status()
                ingest_rows.append({"file": name, "status": r.json()["status"], "chunks": r.json()["chunk_count"],
                                    "seconds": round(time.perf_counter() - t0, 3)})
    with app_db.session(tenant_id) as s:
        counts = dict(s.execute(text("SELECT (SELECT count(*) FROM documents) d, (SELECT count(*) FROM document_chunks) c, "
                                     "(SELECT count(*) FROM document_chunks WHERE vector_dims(embedding)=384) c384")).one()._mapping)
    results["corpus"] = {"documents": counts["d"], "chunks": counts["c"], "chunks_with_384_dim_embedding": counts["c384"],
                         "ingest": ingest_rows, "ingest_seconds": dist([r["seconds"] for r in ingest_rows]),
                         "includes_demo_corpus_as_distractors": True}

    # 2. calibration (dev split only) and retrieval (test split)
    with phase("retrieval"):
        if args.embedding == "sentence_transformers":
            results["calibration"] = calibrate_threshold(app_db, tenant_id, embedder, dev)
        dev_rows, _ = retrieval_eval(app_db, tenant_id, embedder, dev)
        test_rows, lat = retrieval_eval(app_db, tenant_id, embedder, test)
        ablation = {m: summarize_retrieval(retrieval_eval(app_db, tenant_id, embedder, test, mode=m)[0]) for m in ("vector", "fts")}
    results["retrieval"] = {"dev": summarize_retrieval(dev_rows), "test": summarize_retrieval(test_rows),
                            "latency_s": dist(lat), "test_split_queries": len(test), "ablation_test": ablation,
                            "definitions": {"recall_at_5": "per answerable query: relevant units found in top-5 / relevant units; averaged",
                                            "precision_at_5": "per answerable query: top-5 chunks that belong to a relevant unit / 5; averaged (ceiling < 1 when a query has one relevant unit)"}}
    (out / "retrieval_test.jsonl").write_text("\n".join(json.dumps(r) for r in test_rows), encoding="utf-8")

    # 3. grounded QA (test split)
    if not args.skip_qa:
        with phase("qa"):
            if args.llm == "ollama":  # warm-up: load the model once; recorded separately, not in latency stats
                t0 = time.perf_counter()
                llm.answer("warm up", [])  # type: ignore[arg-type]
                results["llm_cold_start_s"] = round(time.perf_counter() - t0, 3)
                llm.calls.clear()
            qa_rows = qa_eval(app_db, tenant_id, embedder, llm, test if args.qa_split == "test" else dev)
            extra = []
            for _ in range(max(0, args.qa_repeats - 1)):
                extra += [r["wall_s"] for r in qa_eval(app_db, tenant_id, embedder, llm, [q for q in test if q["answerable"]][:8])]
        results["qa"] = summarize_qa(qa_rows)
        results["qa"]["split"] = args.qa_split
        if extra:
            results["qa"]["extra_latency_samples_s"] = dist(extra)
        (out / "qa_test.jsonl").write_text("\n".join(json.dumps(r) for r in qa_rows), encoding="utf-8")

    # 4. structured extraction
    if not args.skip_structured:
        with owner.connect() as c:
            uid = c.execute(text("SELECT id FROM users WHERE email = :e"), {"e": users["support_engineer"]}).scalar()
        with phase("structured"):
            srows = structured_eval(app_db, tenant_id, embedder, llm, reports, uid)
        results["structured"] = summarize_structured(srows)
        (out / "structured.jsonl").write_text("\n".join(json.dumps(r) for r in srows), encoding="utf-8")

    # 5. end-to-end workflow
    with phase("e2e"):
        runs, external_count = e2e_eval(client, slug, users, worker_db, t_app, args.e2e_runs,
                                        "Pump P-101 shows abnormal vibration at the drive end, measured at 8.4 mm/s, with a grinding noise.")
    results["e2e"] = {"runs": runs, "all_submitted": all(r["state"] == "SUBMITTED" for r in runs),
                      "external_tickets_created": external_count, "expected_external_tickets": len(runs),
                      "duplicates": external_count - len(runs),
                      "total_s": dist([r["total_s"] for r in runs]), "extract_s": dist([r["extract_s"] for r in runs])}
    with app_db.session(tenant_id) as s:
        results["e2e"]["audit_events"] = s.execute(text("SELECT count(*) FROM audit_events")).scalar()

    sampler.stop()
    results["resources"] = {name: sampler.window(*w) for name, w in windows.items()}
    results["versions"] = versions(llm, embedder)

    finished = dt.datetime.now(dt.timezone.utc)
    dataset_hash = hashlib.sha256(b"".join(p.read_bytes() for p in sorted(DATASET.rglob("*")) if p.is_file()
                                           and p.suffix in (".jsonl", ".csv"))).hexdigest()
    manifest = {"run_id": run_id, "command": "python " + " ".join(sys.argv), "started_utc": started.isoformat(),
                "finished_utc": finished.isoformat(), "duration_s": round((finished - started).total_seconds(), 1),
                "evidence_class": results["evidence_class"], "backends": results["backends"],
                "dataset": {"name": "apex-eval-v1", "text_files_sha256": dataset_hash,
                            "documents": results["corpus"]["documents"], "chunks": results["corpus"]["chunks"],
                            "answerable_test": sum(1 for q in test if q["answerable"]),
                            "unanswerable_test": sum(1 for q in test if not q["answerable"]),
                            "answerable_dev": sum(1 for q in dev if q["answerable"]),
                            "unanswerable_dev": sum(1 for q in dev if not q["answerable"]), "fault_reports": len(reports),
                            "e2e_runs": args.e2e_runs, "qa_repeats": args.qa_repeats},
                "hardware": capture_hardware.collect(), "versions": results["versions"],
                "isolation": f"database {BENCH_DB}, tenant apex-benchmark (recreated every run)"}
    (out / "results.json").write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: results.get(k) for k in ("retrieval", "qa", "structured")}, indent=1, default=str)[:6000])
    print("e2e:", {k: v for k, v in results["e2e"].items() if k != "runs"})
    print("written:", out)
    app_db.dispose()
    worker_db.dispose()


if __name__ == "__main__":
    main()
