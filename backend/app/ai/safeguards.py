"""Deterministic safeguards applied to model output before it is shown or acted on.

These checks are generic. They verify identifiers, numbers and explicit absence claims against evidence
and check that citations point to current, tenant-owned chunks.
"""
import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai.absence_claims import unsupported_absence

# Equipment IDs (P-101, CV-401), part numbers (PN-4417) and incident record IDs (INC-2025-1001).
IDENTIFIER = re.compile(r"\b(?:INC-\d{4}-\d{4}|PN-\d{3,6}|[A-Z]{1,4}-\d{2,4}[A-Z]?)\b")  # most specific first
_MARKER = re.compile(r"\[\d+\]")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _norm_number(raw: str) -> str:
    return raw.replace(",", "").rstrip(".")


def _numbers(text_: str, reference_spans: tuple[tuple[int, int], ...] = ()) -> set[str]:
    from app.ai.tuning import get_tuning
    # C1: with citation_marker_formats a range or list marker such as [1-3] is a citation, not the numbers 1 and 3
    marker = _RANGE_MARKER if get_tuning().citation_marker_formats else _MARKER
    text_ = marker.sub(lambda match: " " * len(match.group()), text_)
    return {
        _norm_number(match.group())
        for match in _NUMBER.finditer(text_)
        if not any(start <= match.start() and match.end() <= end for start, end in reference_spans)
    }


def unsupported_identifiers(answer: str, evidence_texts: list[str], question: str = "") -> list[str]:
    """Identifiers mentioned in the answer that appear in neither the evidence nor the question."""
    allowed = {m.upper() for t in [*evidence_texts, question] for m in IDENTIFIER.findall(t.upper())}
    return sorted({m for m in IDENTIFIER.findall(answer.upper()) if m not in allowed})


_RANGE_MARKER = re.compile(r"\[\s*\d+(?:\s*[-–,]\s*\d+)*\s*\]")  # [1], [1-3], [1, 2], [1,2,3]


def citation_marker_indexes(answer: str) -> set[int]:
    """Citation indexes referenced by markers, expanding ranges ([1-3] -> 1, 2, 3) and lists ([1, 2] -> 1, 2)."""
    indexes: set[int] = set()
    for marker in _RANGE_MARKER.findall(answer):
        body = marker.strip("[] ")
        for part in re.split(r"\s*,\s*", body):
            if re.search(r"[-–]", part):
                lo, hi = (int(x) for x in re.split(r"\s*[-–]\s*", part)[:2])
                indexes.update(range(lo, hi + 1) if 0 < hi - lo < 20 else {lo, hi})
            elif part.strip().isdigit():
                indexes.add(int(part))
    return indexes


def unsupported_numbers(answer: str, evidence_texts: list[str], *,
                        reference_spans: tuple[tuple[int, int], ...] = ()) -> list[str]:
    """Numbers stated in the answer that do not appear in the cited evidence.

    Numbers from the QUESTION are deliberately not allowed: a model could otherwise present a figure the user
    typed (e.g. their own reading) as a specification limit from the manual."""
    allowed: set[str] = set()
    for t in evidence_texts:
        allowed |= _numbers(t)
    return sorted(_numbers(answer, reference_spans) - allowed)


def check_answer_support(answer: str, evidence_texts: list[str], question: str, *,
                         reference_spans: tuple[tuple[int, int], ...] = ()) -> list[str]:
    problems = []
    ids = unsupported_identifiers(answer, evidence_texts, question)
    if ids:
        problems.append(f"identifier(s) not found in the evidence: {', '.join(ids)}")
    nums = unsupported_numbers(answer, evidence_texts, reference_spans=reference_spans)
    if nums:
        problems.append(f"number(s) not found in the cited evidence: {', '.join(nums)}")
    if unsupported_absence(_RANGE_MARKER.sub(" ", answer), evidence_texts, question):
        problems.append("absence claim lacks explicit cited evidence for the requested property and subject")
    return problems


def verify_citation_sources(session: Session, tenant_id, citations: list[dict]) -> list[str]:
    """Every cited chunk must exist, be current, and belong to this tenant (with a tenant-owned document)."""
    if not citations:
        return []
    ids = sorted({c["chunk_id"] for c in citations})
    found = {str(r[0]) for r in session.execute(
        text("SELECT c.id FROM document_chunks c JOIN documents d ON d.id = c.document_id "
             "WHERE c.tenant_id = :t AND d.tenant_id = :t AND d.lifecycle_status = 'active' "
             "AND c.is_current AND c.id = ANY(CAST(:ids AS uuid[]))"),
        {"t": str(tenant_id), "ids": ids})}
    return [f"citation source {cid} is not a current chunk owned by this tenant" for cid in ids if cid not in found]
