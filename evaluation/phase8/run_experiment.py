"""Phase 8 development-split experiment runner (E1-E10, integrated candidate).

    # retrieval sweep: one ingestion, many tuning configurations (no model calls)
    python evaluation/phase8/run_experiment.py --id E2 --phases retrieval --sweep configs/e2.json
    # generation / extraction runs: one tuning configuration
    python evaluation/phase8/run_experiment.py --id E7 --tuning '{"quote_snap": true}' --phases qa --reps 1

Dev split only: this runner has no way to select another split. Raw per-item outputs are written exactly as for the baseline; all metrics are
computed afterwards by score_baseline.py. Every run directory gets a manifest with the tuning, its hash, commit and environment.
"""
import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import logging
import os
import platform
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "evaluation" / "phase8"))
import run_baseline as rb  # noqa: E402  (also sets up sys.path for backend, mocks and scripts)

import score_baseline as sc  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.database.session import Database  # noqa: E402
from app.main import create_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

p3 = rb.p3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True, help="experiment id, e.g. E3 or CAND1")
    ap.add_argument("--tuning", default="{}", help="JSON tuning for single-configuration runs and for ingestion")
    ap.add_argument("--sweep", help="JSON file: list of {name, tuning} retrieval configurations (retrieval phase only)")
    ap.add_argument("--phases", default="retrieval,qa,extraction")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--split", default="dev", choices=["dev", "test"], help="the challenge split is not selectable; test requires --allow-heldout")
    ap.add_argument("--allow-heldout", action="store_true", help="only for the single approved held-out evaluation")
    ap.add_argument("--out-root", default=str(ROOT / "evaluation" / "reports" / "phase8"))
    args = ap.parse_args()
    if args.split != "dev" and not args.allow_heldout:
        sys.exit("refusing to run a held-out split without --allow-heldout")
    phases = set(args.phases.split(","))
    verify = subprocess.run([sys.executable, str(ROOT / "evaluation" / "phase8" / "validate_dataset.py"), "--verify"], capture_output=True, text=True, cwd=ROOT)
    if verify.returncode != 0:
        sys.exit("frozen dataset hashes do not match; refusing to run: " + verify.stdout.strip())
    ingest_tuning = args.tuning
    os.environ["EAOP_TUNING"] = ingest_tuning if ingest_tuning != "{}" else ""
    from app.ai.tuning import get_tuning, tuning_hash

    started = dt.datetime.now(dt.timezone.utc)
    run_id = f"exp-{args.id}-{started:%Y%m%dT%H%M%SZ}"
    out = Path(args.out_root) / run_id
    out.mkdir(parents=True, exist_ok=True)
    print("run", run_id, "tuning", ingest_tuning, flush=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "backend", "evaluation/phase8", "evaluation/datasets"], capture_output=True, text=True, cwd=ROOT).stdout.strip()

    p3.BENCH_DB = rb.EVAL_DB
    base = get_settings(rb.EVAL_DB)
    settings = dataclasses.replace(base, jwt_secret="eval2-" + uuid.uuid4().hex, llm_backend="ollama", embedding_backend="sentence_transformers")
    p3.setup(settings)
    owner = create_engine(settings.url("owner"))
    app_db, worker_db = Database(settings, role="app"), Database(settings, role="worker")
    from app.ai.embeddings import get_embedder
    from app.ai.llm import get_llm
    embedder = get_embedder("sentence_transformers")
    llm = rb.RecordingLLM(get_llm("ollama"))
    rb.domain_routes.get_llm = lambda _name: llm
    client = TestClient(create_app(settings, app_db))
    logging.getLogger("eaop").setLevel(logging.ERROR)
    tenants, servers, urls = rb.tenants_setup(settings, owner, client)
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

    passages = rb.load("passages.jsonl")
    headers = rb.FreshHeaders(client, tenants, "support_engineer")
    ingest_rows = []
    with phase("ingestion"):
        for t in ("apex", "meridian"):
            rb.ingest_corpus(client, headers[t], t, passages, "", ingest_rows)
    with owner.begin() as c:
        c.execute(text("ANALYZE document_chunks"))
    queries = [q for q in rb.load("queries.jsonl") if q["split"] == args.split]
    cases = [c for c in rb.load("incidents.jsonl") if c["split"] == args.split]
    results = {"run_id": run_id, "experiment": args.id, "split": args.split, "ingest_seconds": round(sum(r["seconds"] for r in ingest_rows), 1)}

    if "retrieval" in phases:
        configs = json.loads(Path(args.sweep).read_text(encoding="utf-8")) if args.sweep else [{"name": "default", "tuning": json.loads(ingest_tuning)}]
        scores = {}
        qa_ids = [q for q in queries]
        for cfg in configs:
            os.environ["EAOP_TUNING"] = json.dumps(cfg["tuning"]) if cfg["tuning"] else ""
            rows = []
            with phase(f"retrieval_{cfg['name']}"):
                for t in ("apex", "meridian"):
                    rb.retrieval_pass(app_db, tenants[t], embedder, [q for q in qa_ids if q["tenant"] == t], rows, modes=("hybrid",))
            (out / f"retrieval_{cfg['name']}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
            scores[cfg["name"]] = {"tuning": cfg["tuning"], "tuning_hash": tuning_hash(get_tuning()),
                                   **{scope or "combined": sc.score_retrieval(rows, None, queries, scope) for scope in (None, "apex", "meridian")}}
            h = scores[cfg["name"]]["combined"]["hybrid"]
            print(f"  {cfg['name']}: R@1 {h['recall@1']} R@5 {h['recall@5']} MRR {h['mrr']} nDCG@5 {h['ndcg@5']} leak {scores[cfg['name']]['combined']['cross_tenant_leakage']['foreign']}", flush=True)
        (out / "retrieval_scores.json").write_text(json.dumps(scores, indent=1), encoding="utf-8")
        os.environ["EAOP_TUNING"] = ingest_tuning if ingest_tuning != "{}" else ""

    if phases & {"qa", "extraction"}:
        with phase("warmup"):
            llm.inner.calls.clear()
            client.post("/api/v1/ai/ask", headers=headers["apex"], json={"question": "warm-up question about pump lubrication"})
            llm.inner.calls.clear()
            llm.extract_log.clear()
            llm.answer_log.clear()
        for rep in range(1, args.reps + 1):
            if "qa" in phases:
                with phase(f"qa_rep{rep}"):
                    rows = []
                    rb.qa_pass(client, headers, llm, queries, rows, rep)
                (out / f"qa_rep{rep}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
                print(f"qa rep {rep} done", flush=True)
            if "extraction" in phases:
                with phase(f"extraction_rep{rep}"):
                    erows = []
                    rb.extraction_pass(client, headers, llm, cases, erows, rep)
                (out / f"extraction_rep{rep}.jsonl").write_text("\n".join(json.dumps(r) for r in erows) + "\n", encoding="utf-8")
                print(f"extraction rep {rep} done", flush=True)
    if "workflow" in phases:
        with phase("workflow"):
            wf = rb.workflow_pass(client, headers, tenants, cases, llm, worker_db, out)
        (out / "workflow.json").write_text(json.dumps(wf, indent=1), encoding="utf-8")
        results["external"] = {"ticketing_tickets": len(servers["ticketing"][1].state.mock.tickets),
                               "servicedesk_tickets": len(servers["servicedesk"][1].state.mock.tickets)}
    sampler.stop()
    results["resources"] = {name: sampler.window(*w) for name, w in windows.items()}
    results["window_seconds"] = {name: round(w[1] - w[0], 1) for name, w in windows.items()}
    results["ingestion"] = ingest_rows
    finished = dt.datetime.now(dt.timezone.utc)
    manifest = {"run_id": run_id, "experiment": args.id, "command": "python " + " ".join(sys.argv), "started_utc": started.isoformat(), "finished_utc": finished.isoformat(),
                "duration_s": round((finished - started).total_seconds(), 1), "git_commit": commit, "uncommitted_changes_in_scope": dirty.splitlines(),
                "python": platform.python_version(), "versions": rb.p3.versions(llm.inner, embedder), "tuning_at_ingestion": json.loads(ingest_tuning),
                "tuning_hash_at_ingestion": tuning_hash(get_tuning()), "reps": args.reps, "phases": sorted(phases),
                "dataset": {"name": "eval-v2", "split": args.split, "queries": len(queries), "cases": len(cases),
                            "manifest_sha256": hashlib.sha256((rb.DS / "MANIFEST.sha256").read_bytes()).hexdigest(),
                            "frozen_splits_sha256": hashlib.sha256((rb.DS / "frozen_splits.json").read_bytes()).hexdigest()},
                "runtime": {"ollama_options": getattr(llm.inner, "options", None), "evidence_threshold": embedder.evidence_threshold}}
    (out / "results.json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str), encoding="utf-8")
    print("written", out, flush=True)
    app_db.dispose()
    worker_db.dispose()


if __name__ == "__main__":
    main()
