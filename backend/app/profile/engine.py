"""Deterministic report parsing and priority decisions driven by a TenantProfile (no model involved)."""
import re

from app.profile.schema import Condition, TenantProfile


def parse_report(profile: TenantProfile, report_text: str) -> dict:
    lowered = report_text.lower()
    asset = re.search(profile.asset_id_pattern, report_text, re.IGNORECASE)
    category = next((c.name for c in profile.categories if any(k.lower() in lowered for k in c.keywords)), "other")
    symptoms = [s.name for s in profile.symptoms if any(k.lower() in lowered for k in s.keywords)]
    signals: dict[str, float | None] = {}
    for signal in profile.signals:
        match = re.search(signal.regex, report_text, re.IGNORECASE)
        signals[signal.name] = float(match.group(1)) if match else None
        if match:
            unit = f" {signal.unit}" if signal.unit else ""
            symptoms.append(f"{signal.name.replace('_', ' ')} {signals[signal.name]:g}{unit}")
    return {
        "asset_id": asset.group(1).upper() if asset else None,
        "category": category,
        "symptoms": symptoms,
        "signals": signals,
        "safety_flag": any(k.lower() in lowered for k in profile.safety_keywords),
    }


def _holds(cond: Condition, fields: dict) -> bool:
    if cond.flag is not None:
        return bool(fields.get("safety_flag"))
    if cond.signal is not None:
        value = (fields.get("signals") or {}).get(cond.signal)
        if value is None:
            return False
        return value >= cond.gte if cond.gte is not None else value <= cond.lte
    return fields.get("category") in (cond.category_in or [])


def decide_priority(profile: TenantProfile, fields: dict) -> str:
    """First matching rule wins; rules are evaluated in the order the tenant defined them."""
    for rule in profile.priority_rules:
        if any(_holds(cond, fields) for cond in rule.any):
            return rule.priority
    return profile.default_priority
