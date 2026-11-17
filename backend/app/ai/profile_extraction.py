"""Profile-driven structured extraction for the language model (prompt + JSON schema built from config).

The built-in equipment-maintenance extraction in ollama_llm.py is left byte-for-byte unchanged (Phase 3
evidence depends on it); tenants with a profile use this generic path instead. The model only proposes
fields; numeric readings and the safety flag are re-derived by regex from the report text, and priority is
decided by deterministic profile rules.
"""
import json
import re

from app.profile import engine
from app.profile.schema import TenantProfile

PROMPT_VERSION = "profile-1"


def build_schema(profile: TenantProfile) -> dict:
    props: dict = {
        "asset_id": {"type": ["string", "null"]},
        "category": {"type": "string", "enum": [c.name for c in profile.categories] + ["other"]},
        "symptoms": {"type": "array", "items": {"type": "string"}},
    }
    for signal in profile.signals:
        props[signal.name] = {"type": ["number", "null"]}
    props["safety_flag"] = {"type": "boolean"}
    return {"type": "object", "properties": props, "required": list(props)}


def build_system_prompt(profile: TenantProfile) -> str:
    label = profile.asset_label
    cats = "; ".join(f"{c.name} ({c.description or 'keywords: ' + ', '.join(c.keywords[:6])})"
                     for c in profile.categories)
    signals = " ".join(f"{s.name} is the {s.name.replace('_', ' ')}{' in ' + s.unit if s.unit else ''} if stated, "
                       "else null." for s in profile.signals)
    safety = ", ".join(profile.safety_keywords[:8]) or "a safety hazard"
    return (
        f"Extract structured fields from a {label} fault report. Use only facts stated in the report. "
        f"asset_id must be copied exactly from the report (the {label} identifier) or null if none is given. "
        f"symptoms is a short list of observed symptoms. {signals} "
        f"safety_flag is true only if the report mentions: {safety}. "
        f"category is the MAIN complaint, one of: {cats}; other (anything else)."
    )


def validate_fields(raw: str, profile: TenantProfile, report_text: str):
    """Return (fields, error). `error` is a message when the model output is unusable."""
    try:
        data = json.loads(raw)
    except ValueError:
        return None, "extraction is not valid JSON"
    if not isinstance(data, dict):
        return None, "extraction is not a JSON object"
    names = [c.name for c in profile.categories] + ["other"]
    if data.get("category") not in names:
        return None, "category is not one of the tenant's categories"
    symptoms = data.get("symptoms")
    if not isinstance(symptoms, list) or not all(isinstance(s, str) for s in symptoms):
        return None, "symptoms must be a list of strings"
    asset = data.get("asset_id")
    if asset is not None and (not isinstance(asset, str) or asset.upper() not in report_text.upper()):
        return None, "model asset_id does not appear in the report (hallucination)"
    signals = {}
    for signal in profile.signals:
        value = data.get(signal.name)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            return None, f"{signal.name} must be a number or null"
        signals[signal.name] = float(value) if value is not None else None
    # Safety-relevant numeric inputs and flags: prefer exact regex/keyword evidence from the report text.
    parsed = engine.parse_report(profile, report_text)
    for name, value in parsed["signals"].items():
        if value is not None:
            signals[name] = value
    flag = bool(data.get("safety_flag")) or parsed["safety_flag"]
    fields = {"asset_id": asset.upper() if asset else None, "category": data["category"], "symptoms": symptoms,
              "signals": signals, "safety_flag": flag}
    if re.search(r"[\x00-\x08]", json.dumps(fields)):  # defensive: no control characters in stored fields
        return None, "extraction contains control characters"
    return fields, None
