"""Identifier handling for questions: equipment/asset/model identifiers and their resolution through the tenant's own records.

Everything here is tenant-scoped (explicit tenant predicate on top of row-level security) and deterministic (no model call). An asset identifier
is resolved to equipment model identifiers by reading the `model: <id>` field of the register row whose record id equals the asset.
"""
import re

from sqlalchemy import text
from sqlalchemy.orm import Session

IDENT = re.compile(r"\b(?:INC-\d{4}-\d{4}|PN-\d{3,6}|[A-Z]{1,4}-\d{2,4}[A-Z]?)\b")
MODEL_FIELD = re.compile(r"model:\s*([A-Z]{1,4}-\d{2,4}[A-Z]?)", re.IGNORECASE)


def query_identifiers(question: str) -> list[str]:
    return list(dict.fromkeys(IDENT.findall(question.upper())))


def resolve_models(session: Session, tenant_id, ids: list[str]) -> dict[str, set[str]]:
    """asset id -> equipment model ids named in that asset's current register/record row (only ids with such a row appear)."""
    if not ids:
        return {}
    rows = session.execute(text(
        "SELECT upper(c.record_id), c.text FROM document_chunks c JOIN documents d ON d.id = c.document_id "
        "WHERE c.tenant_id = :t AND d.tenant_id = :t AND d.lifecycle_status = 'active' AND c.is_current AND upper(c.record_id) = ANY(CAST(:ids AS text[]))"),
        {"t": str(tenant_id), "ids": ids}).all()
    out: dict[str, set[str]] = {}
    for rid, body in rows:
        models = {m.upper() for m in MODEL_FIELD.findall(body)}
        if models:
            out.setdefault(rid, set()).update(models)
    return out


def required_entities(session: Session, tenant_id, question: str) -> list[set[str]]:
    """One alternatives-set per identifier in the question: the identifier itself plus, for an asset, the model(s) its record names."""
    ids = query_identifiers(question)
    models = resolve_models(session, tenant_id, ids)
    return [{i} | models.get(i, set()) for i in ids]


def entity_patterns(session: Session, tenant_id, question: str) -> list[str]:
    pats: set[str] = set()
    for alts in required_entities(session, tenant_id, question):
        pats |= alts
    return [f"%{p}%" for p in sorted(pats)]


def text_names_entity(passage_text: str, alternatives: set[str]) -> bool:
    upper = passage_text.upper()
    return any(a in upper for a in alternatives)


NAME_FIELD = re.compile(r"(?:^|;\s*)name:\s*([^;]+)", re.IGNORECASE)


def asset_name(session: Session, tenant_id, asset_id: str) -> str | None:
    """The asset's own descriptive name from its current record (e.g. "Centrifugal Pump P-101"), without the identifier itself."""
    row = session.execute(text(
        "SELECT c.text FROM document_chunks c JOIN documents d ON d.id = c.document_id "
        "WHERE c.tenant_id = :t AND d.tenant_id = :t AND d.lifecycle_status = 'active' AND c.is_current AND upper(c.record_id) = :a "
        "AND c.text ILIKE '%name:%' LIMIT 1"), {"t": str(tenant_id), "a": asset_id.upper()}).first()
    if not row:
        return None
    m = NAME_FIELD.search(row[0])
    if not m:
        return None
    name = re.sub(re.escape(asset_id), "", m.group(1), flags=re.IGNORECASE).strip(" -")
    return name or None
