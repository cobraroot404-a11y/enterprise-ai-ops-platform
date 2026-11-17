"""Verify a note-backed model specification against current, tenant-owned manuals."""

import re
from dataclasses import dataclass
from math import isclose, isfinite

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai.asset_references import resolve_question_asset
from app.ai.authority import is_low_authority
from app.ai.llm import CitedQuote
from app.ai.measurement_evidence import TYPES, parse_number
from app.ai.safety import looks_like_injection
from app.ai.suppression import MANUAL_KINDS, NOTE_SOURCE_KINDS, parse_fields
from app.retrieval.search import Hit
from app.retrieval.text import normalize_ws, sentences

_LEGACY_PREFIX = "technician note (unverified, not from the manual)"
_UNIT_ALIASES = {
    "millimeter": "mm", "millimeters": "mm", "millimetre": "mm", "millimetres": "mm",
    "inches": "in", "inch": "in",
    "operating hour": "operating hours", "hour": "hours", "month": "months",
    "day": "days", "week": "weeks", "year": "years", "litre": "l", "litres": "l",
    "liter": "l", "liters": "l",
}
_TIME_UNITS = {"operating hours", "hours", "days", "weeks", "months", "years"}
_SPEC_UNITS = _TIME_UNITS | {"mm", "in", "l", "ml", "kg", "g", "psi", "bar", "kpa", "kw", "w", "rpm", "nm", "v", "a"}
_QUALIFIERS = {
    "": "exact", "every": "exact",
    "below": "<", "less than": "<", "above": ">", "greater than": ">",
    "maximum": "<=", "max": "<=", "at most": "<=", "no more than": "<=",
    "minimum": ">=", "min": ">=", "at least": ">=", "no less than": ">=",
}
_VALUE = re.compile(
    rf"(?:(?P<qualifier>{'|'.join(filter(None, _QUALIFIERS))}) )?"
    r"(?P<number>[0-9]{1,9}(?:[.,][0-9]{1,9})*)(?: (?P<unit>[a-z]+(?: [a-z]+)?))?"
)
_PROPERTY = (
    r"bearing re-grease interval|air dryer cartridge interval|shaft alignment tolerance|"
    r"[a-z-]+(?: [a-z-]+){0,4} (?:maintenance interval|tolerance|manufacturer limit)|"
    r"(?:rated|standard) [a-z-]+(?: [a-z-]+){0,4}"
)
_QUESTION = re.compile(
    rf"what (?:is the )?(?P<property>{_PROPERTY}) (?:applies to|for) (?P<asset>[a-z]+-[0-9]+[a-z]?)\??"
)
_LEGACY_UNITS = {
    "bearing re-grease interval": ("operating hours", "exact"),
    "air dryer cartridge interval": ("months", "exact"),
    "shaft alignment tolerance": ("mm", "<"),
}
_OVERRIDE = (
    r"overrid(e|es|den)|deviation|exception|supersed(e|es|ed|ing)|service bulletin|"
    r"engineering change|waiver|derogation"
)
_MAX_RELATED_CHUNKS = 100


@dataclass(frozen=True)
class Specification:
    value: float
    unit: str
    qualifier: str

    def matches(self, other: "Specification") -> bool:
        return (self.unit, self.qualifier) == (other.unit, other.qualifier) and isclose(
            self.value, other.value, rel_tol=1e-8,
        )

    def comparable(self, other: "Specification") -> bool:
        # Upper limits, lower limits and exact values describe different scopes.
        return self.unit == other.unit and self.qualifier.removesuffix("=") == other.qualifier.removesuffix("=")


def _specification(
    raw: str, property_name: str, defaults: tuple[str, str] | None = None,
) -> Specification | None:
    match = _VALUE.fullmatch(raw)
    if not match:
        return None
    number = parse_number(match["number"])
    value = number["value"]
    if number["ambiguous"] or value is None or not isfinite(value) or value <= 0:
        return None
    raw_unit = match["unit"]
    qualifier = _QUALIFIERS[match["qualifier"] or ""]
    if defaults:
        qualifier = _QUALIFIERS[match["qualifier"]] if match["qualifier"] else defaults[1]
        raw_unit = raw_unit or defaults[0]
    unit = _UNIT_ALIASES.get(raw_unit, raw_unit)
    if unit not in _SPEC_UNITS:
        return None
    if property_name.endswith(" interval") and (unit not in _TIME_UNITS or qualifier != "exact"):
        return None
    if property_name in {"rated brake pressure", "rated service brake line pressure"}:
        for _, convert, pattern, _ in TYPES["brake_pressure"]["units"]:
            if re.fullmatch(pattern, unit, re.I):
                return Specification(convert(value), "psi", qualifier)
        return None
    return Specification(value, unit, qualifier)


def _related_evidence(session: Session, tenant_id, asset: str, model: str):
    """Read current text only. Candidate overflow leaves the original verifier decision in place."""
    return list(session.execute(text(
        "SELECT d.kind, c.text FROM document_chunks c JOIN documents d ON d.id = c.document_id "
        "WHERE c.tenant_id = :tenant AND d.tenant_id = :tenant AND d.lifecycle_status = 'active' "
        "AND c.is_current AND c.version = d.current_version AND NOT c.suspicious "
        "AND ((d.kind = ANY(CAST(:manual_kinds AS text[])) AND c.text ILIKE :model) "
        "OR (c.text ~* :override AND (c.text ILIKE :asset OR c.text ILIKE :model))) LIMIT :limit"
    ), {
        "tenant": str(tenant_id), "manual_kinds": sorted(MANUAL_KINDS),
        "asset": f"%{asset}%", "model": f"%{model}%",
        "override": rf"\y({_OVERRIDE})\y", "limit": _MAX_RELATED_CHUNKS + 1,
    }))


def _manual_specification(
    session: Session, tenant_id, asset: str, model: str, property_name: str,
) -> Specification | None:
    rows = _related_evidence(session, tenant_id, asset, model)
    if len(rows) > _MAX_RELATED_CHUNKS:
        return None
    model_pattern = re.escape(model.lower())
    asset_pattern = re.escape(asset)
    heading_pattern = rf"{model_pattern}(?: [a-z0-9 -]+)? - {re.escape(property_name)}"
    forms = {
        "bearing re-grease interval":
            rf"re-grease the drive-end and non-drive-end bearings of the {model_pattern} (?P<value>every .+)",
        "air dryer cartridge interval":
            rf"the air dryer cartridge on the {model_pattern} is changed at (?P<value>.+)",
        "shaft alignment tolerance":
            rf"parallel and angular misalignment on the {model_pattern} must both stay (?P<value>.+)",
    }
    generic = rf"(?:the )?{re.escape(property_name)} (?:for|on) the {model_pattern} is (?P<value>.+)"
    form = forms.get(property_name, generic)
    values: list[Specification] = []
    for kind, body in rows:
        if looks_like_injection(body):
            continue
        # The repository has no trusted specification-override field. Related override text adds
        # uncertainty, regardless of who claims approval. It never serves as authoritative evidence.
        if re.search(rf"\b(?:{asset_pattern}|{model_pattern})(?![\w-])", body, re.I) and re.search(
            rf"\b(?:{_OVERRIDE})\b", body, re.I,
        ):
            return None
        heading, _, details = body.partition("\n")
        if kind not in MANUAL_KINDS or is_low_authority(body) or not re.fullmatch(
            heading_pattern, normalize_ws(heading),
        ):
            continue
        matches = [
            match for sentence in sentences(normalize_ws(details))
            if (match := re.fullmatch(form, sentence.removesuffix(".")))
        ]
        if not matches:
            return None
        for match in matches:
            value = _specification(match["value"], property_name)
            if value is None:
                return None
            values.append(value)
    if values and all(value.matches(values[0]) for value in values):
        return values[0]
    return None


def has_authoritative_conflict(
    session: Session, tenant_id, question: str, original_question: str, answer: str,
    cited: list[CitedQuote], hits: list[Hit],
) -> bool:
    """Withhold only a single, clearly comparable specification supplied by an unverified note."""
    intent = _QUESTION.fullmatch(normalize_ws(question))
    if not intent or len({citation.index for citation in cited}) != 1:
        return False
    asset, property_name = intent["asset"], intent["property"]
    hit = hits[cited[0].index - 1]
    if hit.kind not in NOTE_SOURCE_KINDS:
        return False
    fields = parse_fields(hit.text)
    assets = {fields[key].lower() for key in ("equipment_id", "vehicle_id", "asset_id") if fields.get(key)}
    label, _, statement = normalize_ws(fields.get("description", "")).partition(":")
    statement = statement.strip().removesuffix(".")
    if assets != {asset} or fields.get("category", "").lower() != "note" or not is_low_authority(label):
        return False
    # A verified quote must actually contain the claim, not just another occurrence of its number.
    if not any(statement and statement in normalize_ws(c.quote) for c in cited):
        return False
    claim_prefix = rf"(?:the )?{re.escape(property_name)} for {re.escape(asset)} is "
    note = re.fullmatch(rf"{claim_prefix}(?P<legacy>usually taken as )?(?P<value>.+)", statement)
    answer_text = normalize_ws(re.sub(r"\[\d+\]", "", answer)).removesuffix(".").rstrip()
    answer_value = re.sub(rf"^{claim_prefix}(?:usually taken as )?", "", answer_text)
    if not note:
        return False
    identity = resolve_question_asset(session, tenant_id, original_question)
    if not identity or identity[0].lower() != asset:
        return False
    manual = _manual_specification(session, tenant_id, asset, identity[1], property_name)
    if manual is None:
        return False
    defaults = None
    # Only the known legacy note form borrows the documented property units and qualifier, and
    # only when the current manual uses that exact convention. The generated answer cannot set it.
    convention = _LEGACY_UNITS.get(property_name)
    if (
        label == _LEGACY_PREFIX and note["legacy"] and convention == (manual.unit, manual.qualifier)
        and fields.get("root_cause", "").lower() == "n/a" and fields.get("resolution", "").lower() == "none"
    ):
        defaults = convention
    note_value = _specification(note["value"], property_name, defaults)
    stated = _specification(answer_value, property_name, defaults)
    return bool(
        note_value and stated and note_value.matches(stated)
        and note_value.comparable(manual) and not note_value.matches(manual)
    )
