"""Why do incidents lack grounded guidance (the main driver of the human-review rate)? Dev split only.

    python evaluation/phase8/diagnose_guidance.py

For every dev incident case this repeats the guidance step of incident extraction (same query construction, same retrieval, same model) and records where it
stops: no passage passes the evidence gate, the model answers INSUFFICIENT, the answer fails verification (and why), or it is grounded.
Nothing is changed; results go to evaluation/reports/phase8/diagnosis-guidance-<time>/guidance.jsonl.
"""
import dataclasses
import datetime as dt
import json
import logging
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "evaluation" / "phase8"))
import run_baseline as rb  # noqa: E402

from app.ai import rules  # noqa: E402
from app.ai.rag import has_evidence  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.database.session import Database  # noqa: E402
from app.main import create_app  # noqa: E402
from app.profile.service import get_profile  # noqa: E402
from app.retrieval.search import search  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

p3 = rb.p3


def main():
    out = ROOT / "evaluation" / "reports" / "phase8" / f"diagnosis-guidance-{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%SZ}"
    out.mkdir(parents=True)
    p3.BENCH_DB = rb.EVAL_DB
    settings = dataclasses.replace(get_settings(rb.EVAL_DB), jwt_secret="eval2-" + uuid.uuid4().hex, llm_backend="ollama", embedding_backend="sentence_transformers")
    p3.setup(settings)
    owner = create_engine(settings.url("owner"))
    app_db = Database(settings, role="app")
    from app.ai.embeddings import get_embedder
    from app.ai.llm import get_llm
    embedder, llm = get_embedder("sentence_transformers"), rb.RecordingLLM(get_llm("ollama"))
    rb.domain_routes.get_llm = lambda _n: llm
    client = TestClient(create_app(settings, app_db))
    logging.getLogger("eaop").setLevel(logging.ERROR)
    tenants, _servers, _urls = rb.tenants_setup(settings, owner, client)
    headers = rb.FreshHeaders(client, tenants, "support_engineer")
    passages = rb.load("passages.jsonl")
    rows = []
    for t in ("apex", "meridian"):
        rb.ingest_corpus(client, headers[t], t, passages, "", rows)
    cases = [c for c in rb.load("incidents.jsonl") if c["split"] == "dev" and c["expected_outcome"] == "incident"]
    res = []
    for c in cases:
        tenant = tenants[c["tenant"]]
        r = client.post("/api/v1/incidents/extract", headers=headers[c["tenant"]], json={"report_text": c["text"]})
        if r.status_code >= 300:
            continue
        inc = r.json()
        with app_db.session(tenant["id"]) as s:
            profile = get_profile(s, tenant["id"])
            kinds = profile.guidance_kinds if profile else ["equipment_manual", "inspection_report"]
            query = f"troubleshoot {inc['category'].replace('_', ' ')} {' '.join(inc['symptoms'])}"
            hits = search(s, tenant["id"], query, embedder, k=8, kinds=kinds)
            usable = [h for h in hits if not h.suspicious and has_evidence(h, embedder)]
            a0 = len(llm.answer_log)
            from app.ai.rag import answer_question
            result = answer_question(s, tenant["id"], query, embedder, llm, kinds=kinds, enforce_entities=False)
        raw = llm.answer_log[a0:]
        if not hits:
            stage = "no passages retrieved for the guidance kinds"
        elif not usable:
            stage = "retrieved passages all below the evidence gate"
        elif result.grounded:
            stage = "grounded"
        elif result.insufficient_evidence:
            stage = "model answered INSUFFICIENT"
        else:
            stage = "withheld: " + ("; ".join(result.problems)[:90] if result.problems else "unverified")
        res.append({"id": c["id"], "tenant": c["tenant"], "stage": stage, "query": query[:120], "top": [(h.filename, round(h.similarity, 3), round(h.overlap, 2)) for h in hits[:3]],
                    "n_usable": len(usable), "category": inc["category"], "review_status": inc["review_status"], "raw_answer": (raw[0]["text"][:160] if raw else None),
                    "expected_guidance_family": c.get("category"), "rule_priority_basis": rules.decide_priority({"category": inc["category"]}) if c["tenant"] == "apex" else None})
    (out / "guidance.jsonl").write_text("\n".join(json.dumps(x) for x in res) + "\n", encoding="utf-8")
    from collections import Counter
    print(Counter(x["stage"].split(":")[0] if x["stage"].startswith("withheld") else x["stage"] for x in res))
    print("written", out)


if __name__ == "__main__":
    main()
