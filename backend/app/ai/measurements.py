"""Numeric measurement traceability for incident extraction (Phase 8 priority 1).

A number the model proposes (vibration velocity, brake pressure, coolant temperature, ...) may only influence the deterministic priority rules when
the same value can be found in the report text. Every measurement is recorded for audit with its source and status; an unsupported value is
never silently replaced by a default: it is dropped from the rule inputs, the model's original value is preserved on the record, and the incident
is routed to human review. Genuine values stated in the report are untouched, so real P1 incidents are not suppressed.
"""
import re

_NUM = r"(?<![\w.])(\d+(?:[.,]\d+)?)(?![\w])"


def _find_value(report_text: str, value: float) -> re.Match | None:
    """The first occurrence of `value` as a number in the text (treating 8.0 and 8 as the same value)."""
    for m in re.finditer(_NUM, report_text):
        try:
            if abs(float(m.group(1).replace(",", ".")) - float(value)) < 1e-9:
                return m
        except ValueError:
            continue
    return None


def verify_measurements(report_text: str, proposed: dict[str, tuple[float | None, str]],
                        regex_values: dict[str, float | None]) -> tuple[dict[str, float | None], list[dict]]:
    """Return (values that may be used by the rules, audit records).

    proposed:     name -> (value proposed by the model or regex, unit)
    regex_values: name -> value parsed deterministically from the report (the authoritative source when present)
    """
    usable: dict[str, float | None] = {}
    records: list[dict] = []
    for name, (value, unit) in proposed.items():
        if value is None:
            usable[name] = None
            continue
        match = _find_value(report_text, value)
        from_regex = regex_values.get(name) is not None and abs(float(regex_values[name]) - float(value)) < 1e-9
        if match is not None:
            start = max(0, match.start() - 30)
            span = report_text[start:match.end() + len(unit) + 12].strip()
            usable[name] = float(value)
            records.append({"name": name, "value": float(value), "unit": unit, "status": "verified", "source": "report_text",
                            "evidence_span": span, "method": "deterministic_regex" if from_regex else "value_present_in_report",
                            "normalized_value": float(value), "converted": False})
        else:
            usable[name] = None
            records.append({"name": name, "value": None, "unit": unit, "status": "unsupported", "source": "model_output",
                            "model_proposed_value": float(value), "evidence_span": None, "method": "value_not_found_in_report",
                            "normalized_value": None, "converted": False})
    return usable, records


# V41-14.02: the always-on, evidence-based audit lives in app.ai.measurement_evidence (hardening V5); re-exported here for callers.
from app.ai.measurement_evidence import (  # noqa: E402,F401
    CONFLICT,
    HOLD_STATUSES,
    QUARANTINED,
    UNSUPPORTED,
    VERIFIED,
    audit_measurements,
    needs_review,
)
