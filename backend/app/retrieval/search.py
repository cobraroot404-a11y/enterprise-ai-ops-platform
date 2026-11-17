"""Hybrid retrieval: pgvector cosine + PostgreSQL full-text, fused with reciprocal rank fusion.

Always tenant-filtered in SQL (defense in depth on top of row-level security).
"""
import re
from dataclasses import asdict, dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai.embeddings import Embedder
from app.ai.safety import looks_like_injection
from app.ai.tuning import Tuning, get_tuning
from app.core.errors import DependencyUnavailable
from app.observability.metrics import METRICS
from app.retrieval.entities import entity_patterns, query_identifiers, required_entities, text_names_entity
from app.retrieval.profiles import require_compatible
from app.retrieval.text import content_tokens, overlap_ratio


@dataclass
class Hit:
    chunk_id: str
    document_id: str
    filename: str
    kind: str
    version: int
    text: str
    page_number: int | None
    record_id: str | None
    suspicious: bool
    score: float
    similarity: float
    overlap: float

    def to_dict(self) -> dict:
        return asdict(self)


_SQL = """
WITH base AS (
  SELECT c.id, c.document_id, c.version, c.text, c.page_number, c.record_id, c.suspicious, c.tsv,
         c.embedding, d.filename, d.kind
  FROM document_chunks c JOIN documents d ON d.id = c.document_id
  WHERE c.tenant_id = :tenant AND d.tenant_id = :tenant AND d.lifecycle_status = 'active' AND c.is_current AND c.embedding_profile_id = :profile {kind_clause}
),
vec AS (
  SELECT id, row_number() OVER (ORDER BY embedding <=> CAST(:qv AS vector)) AS r
  FROM base ORDER BY embedding <=> CAST(:qv AS vector) LIMIT :pool
),
fts AS (
  SELECT id, row_number() OVER (ORDER BY ts_rank_cd(tsv, to_tsquery('english', :tsq)) DESC) AS r
  FROM base WHERE :tsq <> '' AND tsv @@ to_tsquery('english', :tsq) LIMIT :pool
){ent_cte}
SELECT b.id, b.document_id, b.filename, b.kind, b.version, b.text, b.page_number, b.record_id, b.suspicious,
       {score_expr} AS score,
       1 - (b.embedding <=> CAST(:qv AS vector)) AS similarity
FROM base b
LEFT JOIN vec ON vec.id = b.id
LEFT JOIN fts ON fts.id = b.id{ent_join}
WHERE ({mode_clause}){ent_where}
ORDER BY score DESC{order_extra}
LIMIT :k
"""


def _tsquery(query: str) -> str:
    terms = [t for t in dict.fromkeys(content_tokens(query)) if re.fullmatch(r"[a-z0-9]+", t)]
    return " | ".join(terms)


_MODES = {
    "hybrid": "vec.id IS NOT NULL OR fts.id IS NOT NULL",
    "vector": "vec.id IS NOT NULL",  # ablation: embedding similarity only
    "fts": "fts.id IS NOT NULL",  # ablation: PostgreSQL full-text only
}


def search(session: Session, tenant_id, query: str, embedder: Embedder, *, k: int = 5,
           kinds: list[str] | None = None, pool: int = 30, mode: str = "hybrid") -> list[Hit]:
    tun = get_tuning()
    with METRICS.timer("retrieval_seconds", tenant=str(tenant_id), mode=mode):
        depth = max(k, tun.rerank_depth) if (tun.rerank and mode == "hybrid") else k
        if tun.subquery_split and mode == "hybrid":
            hits = _split_search(session, tenant_id, query, embedder, depth, kinds, pool)
        else:
            hits = _search(session, tenant_id, query, embedder, k=depth, kinds=kinds, pool=pool, mode=mode)
        if tun.rerank and mode == "hybrid":
            hits = _rerank(session, tenant_id, query, hits, tun)
        return hits[:k]


_SPLIT = re.compile(r",?\s+and\s+(?=(?:what|which|when|how|who|where)\b)|;\s+", re.IGNORECASE)


def split_question(question: str) -> list[str]:
    """Rule-based split of a multi-part question; identifiers named anywhere are carried into every part."""
    parts = [p.strip(" ?,.") for p in _SPLIT.split(question) if p and p.strip(" ?,.")]
    if len(parts) < 2:
        return [question]
    ids = query_identifiers(question)
    return [p if all(i in p.upper() for i in ids) else f"{p} {' '.join(i for i in ids if i not in p.upper())}" for p in parts]


def _split_search(session, tenant_id, query, embedder, k, kinds, pool) -> list[Hit]:
    parts = split_question(query)
    lists = [_search(session, tenant_id, query, embedder, k=max(k, 10), kinds=kinds, pool=pool)]
    if len(parts) > 1:
        lists += [_search(session, tenant_id, p, embedder, k=max(k, 10), kinds=kinds, pool=pool) for p in parts]
    if len(lists) == 1:
        return lists[0][:k]
    fused: dict[str, float] = {}
    by_id: dict[str, Hit] = {}
    for hits in lists:
        for rank, h in enumerate(hits, 1):
            fused[h.chunk_id] = fused.get(h.chunk_id, 0.0) + 1.0 / (60 + rank)
            by_id.setdefault(h.chunk_id, h)
    ordered = sorted(fused, key=lambda cid: -fused[cid])[:k]
    return [by_id[c] for c in ordered]


def _rerank(session, tenant_id, query: str, hits: list[Hit], tun: Tuning) -> list[Hit]:
    """Linear feature reranker: embedding similarity, lexical overlap, identifier match, title match, original-rank prior. No new model."""
    w_sim, w_ov, w_id, w_title, w_rank = tun.rerank_weights
    alts = required_entities(session, tenant_id, query)

    def features(rank: int, h: Hit) -> float:
        ident = 1.0 if alts and all(text_names_entity(h.text, a) for a in alts) else 0.5 if alts and any(text_names_entity(h.text, a) for a in alts) else 0.0
        title = overlap_ratio(query, h.text[:90])
        return w_sim * h.similarity + w_ov * h.overlap + w_id * ident + w_title * title + w_rank / (1 + rank)

    scored = sorted(((features(i, h), i, h) for i, h in enumerate(hits)), key=lambda t: (-t[0], t[1]))
    return [h for _s, _i, h in scored]


def _search(session: Session, tenant_id, query: str, embedder: Embedder, *, k: int = 5,
            kinds: list[str] | None = None, pool: int = 30, mode: str = "hybrid") -> list[Hit]:
    profile = require_compatible(session, tenant_id, embedder)  # refuses a model/revision mismatch
    if profile is None:
        return []
    try:
        with METRICS.timer("embedding_seconds", tenant=str(tenant_id), backend=embedder.name):
            vector = embedder.embed([query])[0]
    except Exception as exc:  # noqa: BLE001 - any embedding failure is a dependency outage, not a server bug
        METRICS.incr("embedding_failures_total", tenant=str(tenant_id), backend=embedder.name)
        raise DependencyUnavailable("The embedding model is unavailable; retry shortly",
                                    code="embedding_unavailable") from exc
    params = {
        "profile": str(profile.id), "tenant": str(tenant_id), "qv": "[" + ",".join(f"{x:.6f}" for x in vector) + "]",
        "tsq": _tsquery(query), "pool": pool, "k": k,
    }
    kind_clause = ""
    if kinds:
        kind_clause = "AND d.kind = ANY(:kinds)"
        params["kinds"] = kinds
    if mode not in _MODES:
        raise ValueError(f"unknown search mode '{mode}'")
    tun = get_tuning()
    score_expr = "coalesce(1.0 / (60 + vec.r), 0) + coalesce(1.0 / (60 + fts.r), 0)"  # the validated baseline expression
    ent_cte = ent_join = ent_where = ""
    order_extra = (", b.filename, b.page_number NULLS LAST, b.record_id NULLS LAST, b.version DESC, b.id" if tun.stable_ranking else "")
    if (tun.rrf_k, tun.w_vec, tun.w_text) != (60, 1.0, 1.0):
        params.update(rrfk=tun.rrf_k, wv=tun.w_vec, wt=tun.w_text)
        score_expr = "coalesce(:wv / (:rrfk + vec.r), 0) + coalesce(:wt / (:rrfk + fts.r), 0)"
    if tun.entity_boost > 0 and mode == "hybrid":
        pats = entity_patterns(session, tenant_id, query)
        if pats:
            params.update(pats=pats, eboost=tun.entity_boost)
            ent_cte = (", ent AS (SELECT id FROM base WHERE text ILIKE ANY(CAST(:pats AS text[])) "
                       "ORDER BY embedding <=> CAST(:qv AS vector) LIMIT :pool)")
            ent_join = " LEFT JOIN ent ON ent.id = b.id"
            ent_where = " OR ent.id IS NOT NULL"
            score_expr += " + CASE WHEN ent.id IS NOT NULL THEN :eboost ELSE 0 END"
    rows = session.execute(text(_SQL.format(kind_clause=kind_clause, mode_clause=_MODES[mode], score_expr=score_expr,
                                            ent_cte=ent_cte, ent_join=ent_join, ent_where=ent_where, order_extra=order_extra)),
                           params).mappings().all()
    return [
        Hit(chunk_id=str(r["id"]), document_id=str(r["document_id"]), filename=r["filename"], kind=r["kind"],
            version=r["version"], text=r["text"], page_number=r["page_number"], record_id=r["record_id"],
            suspicious=bool(r["suspicious"]) or looks_like_injection(r["text"]), score=float(r["score"]),
            similarity=float(r["similarity"]), overlap=overlap_ratio(query, r["text"]))
        for r in rows
    ]
