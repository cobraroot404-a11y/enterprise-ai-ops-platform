"""Deterministic report parsing and business rules.

Priority is ALWAYS decided here, never by a model. The thresholds are a fictional Apex maintenance
policy used for this demonstration (not a real standard).
"""
import re

ASSET_ID = re.compile(r"\b([A-Z]{1,4}-\d{2,4}[A-Z]?)\b")
VIBRATION = re.compile(r"(\d+(?:\.\d+)?)\s*mm\s*/\s*s", re.IGNORECASE)

CATEGORIES = [
    ("mechanical_vibration", ("vibrat",)),
    ("leak", ("leak", "dripping", "seep")),
    ("overheating", ("overheat", "too hot", "high temperature", "temperature rise", "running hot")),
    ("electrical_fault", ("tripp", "short circuit", "electrical", "burning smell")),
    ("noise", ("noise", "grinding", "knocking", "squeal", "rattl")),
    ("performance_degradation", ("low flow", "pressure drop", "reduced output", "slow")),
]
SYMPTOM_KEYWORDS = [
    ("abnormal vibration", ("vibrat",)),
    ("unusual noise", ("noise", "grinding", "knocking", "squeal", "rattl")),
    ("overheating", ("overheat", "too hot", "running hot", "high temperature")),
    ("fluid leak", ("leak", "dripping", "seep")),
    ("smoke or burning smell", ("smoke", "burning smell")),
    ("reduced flow or pressure", ("low flow", "pressure drop", "reduced output")),
]


def parse_report(report_text: str) -> dict:
    lowered = report_text.lower()
    asset = ASSET_ID.search(report_text)
    category = next((name for name, keys in CATEGORIES if any(k in lowered for k in keys)), "other")
    symptoms = [name for name, keys in SYMPTOM_KEYWORDS if any(k in lowered for k in keys)]
    velocity = None
    match = VIBRATION.search(report_text)
    if match:
        velocity = float(match.group(1))
        symptoms.append(f"vibration velocity {velocity:g} mm/s")
    return {
        "asset_id": asset.group(1) if asset else None,
        "category": category,
        "symptoms": symptoms,
        "vibration_mm_s": velocity,
        "smoke_or_fire": any(k in lowered for k in ("smoke", "fire", "burning smell")),
    }


def decide_priority(fields: dict) -> str:
    velocity = fields.get("vibration_mm_s")
    category = fields.get("category")
    if fields.get("smoke_or_fire") or (velocity is not None and velocity >= 11.2):
        return "P1"
    if (velocity is not None and velocity >= 7.1) or category in ("leak", "overheating", "electrical_fault"):
        return "P2"
    if (velocity is not None and velocity >= 4.5) or category in ("noise", "mechanical_vibration"):
        return "P3"
    return "P4"
