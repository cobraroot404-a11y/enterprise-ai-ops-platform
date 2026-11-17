"""No-LLM, development-only diagnostic: replay the deterministic retrieval -> filter -> authority/H2 -> context_k path for chosen dev queries.
Split is forced to "dev"; held-out/challenge ids are rejected. It never constructs an LLM client.

    python evaluation/phase8/diag_context.py E2-A-0058 E2-M-0047 ...   (uses the disposable eaop_eval2 database; never calls Ollama)
"""
import dataclasses
import functools
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "evaluation" / "phase8"))
import run_baseline as rb  # noqa: E402

TUNING = {"entity_boost": 0.02, "entity_gate": True, "query_override_gate": True, "claim_completion": True,
          "numeric_verification": True, "guidance_query": "asset_context"}
os.environ["EAOP_TUNING"] = json.dumps(TUNING)
from app.ai.authority import _subject_tokens, apply_authority_order, is_low_authority, shares_subject  # noqa: E402
from app.ai.rag import has_evidence, select_context  # noqa: E402
from app.ai.tuning import get_tuning  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.database.session import Database  # noqa: E402
from app.main import create_app  # noqa: E402
from app.ai.suppression import find_suppressions, suppress_low_authority  # noqa: E402
from app.retrieval.entities import resolve_models  # noqa: E402
from app.retrieval.search import search  # noqa: E402
from app.retrieval.text import tokens  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402


def label(h):
    return f"{h.filename}#{h.page_number if h.page_number is not None else h.record_id}"


def main(ids):
    p3 = rb.p3
    assert rb.EVAL_DB != "eaop", "never the shared database"
    p3.BENCH_DB = rb.EVAL_DB
    settings = dataclasses.replace(get_settings(rb.EVAL_DB), jwt_secret="diag-" + uuid.uuid4().hex,
                                   llm_backend="ollama", embedding_backend="sentence_transformers")
    p3.setup(settings)
    owner = create_engine(settings.url("owner"))
    app_db = Database(settings, role="app")
    from app.ai.embeddings import get_embedder
    embedder = get_embedder("sentence_transformers")
    client = TestClient(create_app(settings, app_db))
    tenants, _servers, _urls = rb.tenants_setup(settings, owner, client)
    passages = rb.load("passages.jsonl")
    headers = rb.FreshHeaders(client, tenants, "support_engineer")
    for t in ("apex", "meridian"):
        rb.ingest_corpus(client, headers[t], t, passages, "", [])
    queries = {q["id"]: q for q in rb.load("queries.jsonl") if q["split"] == "dev"}  # dev split only
    unknown = [i for i in ids if i not in queries]
    if unknown:
        raise SystemExit(f"not dev-split query ids: {unknown}")
    out = {}
    for qid in ids:
        q = queries[qid]
        tenant = tenants[q["tenant"]]
        with app_db.session(tenant["id"]) as s:
            hits = search(s, tenant["id"], q["query"], embedder, k=8)
        rec = {"query": q["query"], "gold": {k: v for k, v in q.items() if k not in ("query",)}, "raw": [], "paths": {}}
        for h in hits:
            rec["raw"].append({"label": label(h), "kind": h.kind, "doc": h.document_id[:8], "score": round(h.score, 4),
                               "sim": round(h.similarity, 4), "overlap": round(h.overlap, 3), "suspicious": h.suspicious,
                               "has_evidence": has_evidence(h, embedder), "low_authority": is_low_authority(h.text),
                               "text": h.text[:230]})
        removed = [(label(h), "suspicious" if h.suspicious else "below evidence threshold")
                   for h in hits if h.suspicious or not has_evidence(h, embedder)]
        cands = [h for h in hits if not h.suspicious and has_evidence(h, embedder)]
        for name, flag in (("baseline", False), ("H1", True), ("H2", False)):
            c = apply_authority_order(cands) if flag else list(cands)
            final = select_context(c, get_tuning().context_k, get_tuning().context_diverse)
            if name == "H2":
                with app_db.session(tenant["id"]) as s2:
                    resolve = functools.partial(resolve_models, s2, tenant["id"])
                    rec["h2_suppressions"] = [{"note": label(x.note), "manual": label(x.manual), "model": x.model, "asset": x.asset}
                                              for x in find_suppressions(final, resolve)]
                    final = suppress_low_authority(final, resolve)
            rec["paths"][name] = {"removed_filters": removed, "pre_context_k": [label(h) for h in c],
                                  "final_context": [label(h) for h in final],
                                  "dropped_by_context_k": [label(h) for h in c if h not in final]}
        low = [h for h in cands if is_low_authority(h.text)]
        rec["match"] = [{"note": label(h), "subject_tokens": sorted(_subject_tokens(h.text)),
                         "per_other": [{"other": label(o), "shares": shares_subject(h.text, o.text),
                                        "missing": sorted(_subject_tokens(h.text) - set(tokens(o.text)))}
                                       for o in cands if o not in low]} for h in low]
        out[qid] = rec
    print(json.dumps(out, indent=1))
    app_db.dispose()


if __name__ == "__main__":
    main(sys.argv[1:])
