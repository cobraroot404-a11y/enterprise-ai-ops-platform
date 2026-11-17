"""Re-embed a tenant's documents under a different embedding backend (atomic, repeatable).

Usage: python scripts/reindex_embeddings.py --tenant apex-industrial --backend sentence_transformers \
           [--report evaluation/reports/phase3/reindex-apex.json]

Steps: capture before-counts -> re-embed ALL chunks in one transaction -> verify counts/dimensions ->
activate the new profile -> rebuild the HNSW index -> run a retrieval self-check. Nothing is changed if any
verification fails. Never run against the `*-uitest` fixture unless you mean to.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select, text  # noqa: E402

from app.ai.embeddings import get_embedder  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.database.session import Database  # noqa: E402
from app.models import DocumentChunk, Tenant  # noqa: E402
from app.retrieval.reindex import reindex_tenant  # noqa: E402
from app.retrieval.search import search  # noqa: E402
from app.retrieval.text import sentences  # noqa: E402


def self_check(db: Database, tenant_id, embedder, sample: int = 25) -> dict:
    """Query with the first sentence of sampled chunks; the source chunk should be in the top 5."""
    with db.session(tenant_id) as s:
        chunks = s.execute(select(DocumentChunk.id, DocumentChunk.text).where(
            DocumentChunk.tenant_id == tenant_id, DocumentChunk.is_current).order_by(DocumentChunk.id)).all()
        step = max(1, len(chunks) // sample)
        picked = chunks[::step][:sample]
        found = 0
        for chunk_id, body in picked:
            first = (sentences(body) or [body])[0][:300]
            hits = search(s, tenant_id, first, embedder, k=5)
            found += any(h.chunk_id == str(chunk_id) for h in hits)
        return {"queries": len(picked), "source_chunk_in_top5": found,
                "rate": round(found / len(picked), 3) if picked else None}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--backend", required=True, choices=["deterministic", "sentence_transformers"])
    parser.add_argument("--report")
    args = parser.parse_args()
    settings = get_settings()
    embedder = get_embedder(args.backend)

    owner = Database(settings, role="owner", pool_size=1, max_overflow=0)
    with owner.session() as s:
        tenant = s.scalar(select(Tenant).where(Tenant.slug == args.tenant))
        if tenant is None:
            sys.exit(f"Unknown tenant '{args.tenant}'")
        tenant_id = tenant.id

    app_db = Database(settings, role="app", pool_size=1, max_overflow=0)
    started = time.perf_counter()
    with app_db.session(tenant_id) as s:
        report = reindex_tenant(s, tenant_id, embedder)
        s.commit()
    report["reindex_seconds"] = round(time.perf_counter() - started, 2)
    with owner.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("REINDEX INDEX document_chunks_embedding_idx"))
        conn.execute(text("ANALYZE document_chunks"))
    report["index_rebuilt"] = True
    report["retrieval_self_check"] = self_check(app_db, tenant_id, embedder)
    report["command"] = "python " + " ".join(sys.argv)
    text_out = json.dumps(report, indent=2, default=str)
    print(text_out)
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(text_out, encoding="utf-8")


if __name__ == "__main__":
    main()
