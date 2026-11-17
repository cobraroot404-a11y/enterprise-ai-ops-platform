"""H3: trusted question-supplied asset references in QA answers."""

import re
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai.authority import is_low_authority
from app.ai.llm import CitedQuote
from app.ai.suppression import MANUAL_KINDS
from app.profile.service import get_profile
from app.retrieval.search import Hit
from app.retrieval.text import normalize_ws, sentences

_ASSET = re.compile(r"(?<![\w./–—-])[A-Za-z]{1,4}-[0-9]{2,4}[A-Za-z]?(?![\w/–—-]|\.\w|,[0-9])")
_MODEL_FIELD = re.compile(r"(?:^|;)\s*model:\s*([^;]*)", re.I)
_INTERVAL = re.compile(
    r"the (?P<topic>[a-z-]+(?: [a-z-]+)*) interval for (?P<asset>[a-z]+-[0-9]+[a-z]?) is "
    r"(?P<interval>every [0-9]+(?:[.,][0-9]+)* (?:operating )?(?:hours|days|weeks|months|years))"
    r"\.? *(?:\[[0-9]+\] *)*\.?"
)
_MAINTENANCE_ACTIONS = {
    "check", "clean", "grease", "inspect", "lubricate", "re-grease", "replace", "service", "test",
}


def _asset_tokens(value: str):
    return (match for match in _ASSET.finditer(value) if not match[0].upper().startswith(("INC-", "PN-")))


def resolve_references(session: Session, tenant_id, question: str, answer: str) -> dict[str, str]:
    """Resolve exact copied tokens to one active, current, trusted register row and one model."""
    asked = {match[0] for match in _asset_tokens(question)}
    copied = asked & {match[0] for match in _asset_tokens(answer)}
    return _resolve_assets(session, tenant_id, copied)


def resolve_question_asset(session: Session, tenant_id, question: str) -> tuple[str, str] | None:
    """Resolve a single question-supplied asset without requiring the answer to copy it."""
    asked = {match[0] for match in _asset_tokens(question)}
    if len(asked) != 1:
        return None
    return next(iter(_resolve_assets(session, tenant_id, asked).items()), None)


def _resolve_assets(session: Session, tenant_id, assets: set[str]) -> dict[str, str]:
    if not assets:
        return {}
    profile = get_profile(session, tenant_id)
    rows = session.execute(text(
        "SELECT upper(c.record_id), c.text, c.suspicious FROM document_chunks c "
        "JOIN documents d ON d.id = c.document_id "
        "WHERE c.tenant_id = :tenant AND d.tenant_id = :tenant AND d.lifecycle_status = 'active' "
        "AND c.is_current AND d.kind = :kind AND upper(c.record_id) = ANY(CAST(:ids AS text[]))"
    ), {
        "tenant": str(tenant_id),
        "kind": profile.register_kind if profile else "equipment_register",
        "ids": sorted({asset.upper() for asset in assets}),
    })
    by_id = defaultdict(list)
    for record_id, body, suspicious in rows:
        by_id[record_id].append((body, suspicious))
    resolved = {}
    for asset in assets:
        records = by_id[asset.upper()]
        if len(records) != 1:
            continue
        body, suspicious = records[0]
        models = [value.strip() for value in _MODEL_FIELD.findall(body)]
        if not suspicious and len(models) == 1 and _ASSET.fullmatch(models[0]) and models[0].upper() != asset.upper():
            resolved[asset] = models[0]
    return resolved


def reference_spans(answer: str, resolved: dict[str, str]) -> tuple[tuple[int, int], ...]:
    return tuple(match.span() for match in _asset_tokens(answer) if match[0] in resolved)


def supports_referenced_interval(
    answer: str, resolved: dict[str, str], cited: list[CitedQuote], hits: list[Hit],
) -> bool:
    """Fail closed on new acceptances outside the supported recurring maintenance statement form."""
    claim = _INTERVAL.fullmatch(normalize_ws(answer))
    if not claim:
        return False
    models = {model.lower() for asset, model in resolved.items() if asset.lower() == claim["asset"]}
    if len(models) != 1:
        return False
    model = models.pop()
    topic, interval = claim["topic"], claim["interval"]
    supported = {f"the {topic} interval for {model} is {interval}"}
    subject, _, action = topic.rpartition(" ")
    if subject and action in _MAINTENANCE_ACTIONS:
        supported.add(f"{action} the {subject} of the {model} {interval}")
        supported.add(f"{action} the {subject}s of the {model} {interval}")
        if subject == "bearing":
            supported.add(f"{action} the drive-end and non-drive-end bearings of the {model} {interval}")
    for citation in cited:
        hit = hits[citation.index - 1]
        if hit.kind in MANUAL_KINDS and not is_low_authority(hit.text):
            # Match complete passage sentences, so a quote that drops a qualifier cannot support the claim.
            body = hit.text
            heading, _, rest = body.partition("\n")
            if normalize_ws(heading).startswith(f"{model} ") and normalize_ws(heading).endswith(f" - {topic} interval"):
                body = rest
            quoted = {sentence.removesuffix(".") for sentence in sentences(normalize_ws(citation.quote))}
            passage = {sentence.removesuffix(".") for sentence in sentences(normalize_ws(body))}
            if supported & quoted & passage:
                return True
    return False
