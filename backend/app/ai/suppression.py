"""H2: structured suppression of self-declared low-authority notes (behind the default-off `low_authority_suppression` tuning flag).

A service/incident record that is structurally a note (`category: note`), explicitly declares itself unverified, and names an asset that the
tenant's own register resolves to exactly one equipment model is removed from the generation context ONLY IF an authoritative manual
passage for that same model, covering the same topic, is retained in that context and the note adds no information the manual lacks.
Every doubt preserves the note. Pure and deterministic; no model call, no dataset-specific identifiers.
"""
import re
from collections.abc import Callable
from dataclasses import dataclass

from app.ai.authority import is_low_authority
from app.retrieval.text import STOPWORDS, tokens

NOTE_SOURCE_KINDS = frozenset({"incident_history", "service_history", "maintenance_log"})
MANUAL_KINDS = frozenset({"equipment_manual", "fleet_manual"})
MIN_TOPIC_OVERLAP = 0.6
MIN_TOPIC_TOKENS = 2

_FIELD = re.compile(r"(?:^|;)\s*([a-z_]+):\s*([^;]*)", re.I)
_ASSET_FIELDS = ("equipment_id", "vehicle_id", "asset_id")
_IDENT = re.compile(r"\b(?:INC-\d{4}-\d{4}|PN-\d{3,6}|[A-Z]{1,4}-\d{2,4}[A-Z]?)\b")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_AUTHORITY_WORDS = frozenset("unverified unconfirmed verified unofficial hearsay note technician manual usually taken".split())
_REGISTER_STOP = frozenset("from".split())


@dataclass(frozen=True)
class Suppression:
    note: object
    manual: object
    model: str
    asset: str


def parse_fields(text: str) -> dict[str, str]:
    return {k.lower(): v.strip() for k, v in _FIELD.findall(text)}


def _fold(token: str) -> str:
    return token[:-1] if len(token) > 3 and token.endswith("s") else token


def _claim(description: str) -> str:
    """The statement after a leading "label (unverified ...):" prefix, which only describes the note's authority."""
    head, sep, rest = description.partition(":")
    return rest if sep and is_low_authority(head) else description


def _topic_tokens(description: str, exclude: set[str]) -> set[str]:
    out = set()
    for t in tokens(_claim(description)):
        if t in STOPWORDS or t in _AUTHORITY_WORDS or t in _REGISTER_STOP or len(t) < 2 or any(c.isdigit() for c in t) or t in exclude:
            continue
        out.add(_fold(t))
    return out


def _names_model(text: str, model: str) -> bool:
    return re.search(rf"(?<![A-Z0-9-]){re.escape(model.upper())}(?![A-Z0-9-])", text.upper()) is not None


def _note_asset(hit) -> tuple[str, str] | None:
    """(asset id, description) of a structured service/incident note that declares low authority, else None."""
    if getattr(hit, "kind", None) not in NOTE_SOURCE_KINDS:
        return None
    fields = parse_fields(hit.text)
    if fields.get("category", "").lower() != "note":
        return None
    description = fields.get("description", "")
    if not is_low_authority(description):
        return None
    for name in _ASSET_FIELDS:
        if fields.get(name):
            return fields[name].upper(), description
    return None


def _adds_nothing(description: str, manual_text: str, asset: str, model: str) -> bool:
    """True when the note's identifiers and measurements are not information the manual lacks."""
    ids = {i for i in _IDENT.findall(description.upper()) if i not in (asset, model.upper())}
    if any(i not in manual_text.upper() for i in ids):
        return False
    if _NUMBER.search(_IDENT.sub(" ", _claim(description).upper())) and not _NUMBER.search(_IDENT.sub(" ", manual_text.upper())):
        return False  # the note would be the only source of a value
    return True


def _covers_topic(description: str, manual_text: str, asset: str, model: str) -> bool:
    topic = _topic_tokens(description, set(tokens(asset)) | set(tokens(model)))
    if len(topic) < MIN_TOPIC_TOKENS:
        return False
    manual_tokens = {_fold(t) for t in tokens(manual_text)}
    return len(topic & manual_tokens) / len(topic) >= MIN_TOPIC_OVERLAP


def find_suppressions(context: list, resolve: Callable[[list[str]], dict[str, set[str]]]) -> list[Suppression]:
    """Notes in `context` that H2 would remove, with the manual passage that justifies each."""
    notes = [(h, _note_asset(h)) for h in context]
    notes = [(h, a) for h, a in notes if a]
    if not notes:
        return []
    models = resolve(sorted({a[0] for _, a in notes}))
    found = []
    for hit, (asset, description) in notes:
        resolved = models.get(asset, set())
        if len(resolved) != 1:
            continue  # unresolved or ambiguous identity
        model = next(iter(resolved))
        for manual in context:
            if getattr(manual, "kind", None) in MANUAL_KINDS and not is_low_authority(manual.text) \
                    and _names_model(manual.text, model) and _covers_topic(description, manual.text, asset, model) \
                    and _adds_nothing(description, manual.text, asset, model):
                found.append(Suppression(hit, manual, model, asset))
                break
    return found


def suppress_low_authority(context: list, resolve: Callable[[list[str]], dict[str, set[str]]]) -> list:
    gone = {id(s.note) for s in find_suppressions(context, resolve)}
    return [h for h in context if id(h) not in gone]
