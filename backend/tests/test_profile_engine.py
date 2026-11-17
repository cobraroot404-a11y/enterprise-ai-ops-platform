"""Tenant profile: validation, deterministic parsing/priority, and equivalence with the built-in rules."""
import json
from pathlib import Path

import pytest
from app.ai import rules
from app.ai.profile_extraction import build_schema, build_system_prompt, validate_fields
from app.profile import engine
from app.profile.schema import TenantProfile
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
MERIDIAN = json.loads((ROOT / "onboarding" / "meridian.json").read_text(encoding="utf-8"))["profile"]


@pytest.fixture()
def meridian():
    return TenantProfile.model_validate(MERIDIAN)


def _fields(profile, text):
    f = engine.parse_report(profile, text)
    return f, engine.decide_priority(profile, f)


# ---- Meridian behaviour -----------------------------------------------------------------------------------------
def test_low_brake_pressure_is_p2_and_extracts_the_reading(meridian):
    f, p = _fields(meridian, "Vehicle VH-2101 shows low brake pressure of 52 psi with a hissing noise at the rear axle.")
    assert (f["asset_id"], f["category"], f["signals"]["brake_pressure_psi"], p) == ("VH-2101", "brake_system", 52.0, "P2")
    assert "low brake pressure" in f["symptoms"] and any("brake pressure psi 52" in s for s in f["symptoms"])


@pytest.mark.parametrize("text,priority", [
    ("VH-2104 coolant temperature reached 118 C on the hill climb.", "P1"),
    ("VH-2104 coolant temperature 108 C and rising.", "P2"),
    ("VH-2101 brake line pressure is 38 psi.", "P1"),             # <= 40: must not be driven
    ("VH-2101 brake line pressure is 57 psi, trending down.", "P3"),  # brake_system category only
    ("VH-2102 reports brake failure on a downhill section.", "P1"),   # safety keyword
    ("VH-2103 has a tyre that looks flat.", "P3"),
    ("VH-2103 cargo temperature rose to -12 C.", "P2"),
    ("VH-2102 interior light is dim.", "P4"),
])
def test_meridian_priority_policy(meridian, text, priority):
    assert _fields(meridian, text)[1] == priority


def test_no_vehicle_id_means_no_asset(meridian):
    assert engine.parse_report(meridian, "A strange noise somewhere in the depot.")["asset_id"] is None
    assert engine.parse_report(meridian, "Pump P-101 is vibrating.")["asset_id"] is None  # not Meridian's ID format


def test_extraction_schema_and_prompt_come_from_the_profile(meridian):
    schema = build_schema(meridian)
    assert set(schema["properties"]) == {"asset_id", "category", "symptoms", "brake_pressure_psi", "coolant_temp_c",
                                         "safety_flag"}
    assert "brake_system" in schema["properties"]["category"]["enum"] and "other" in schema["properties"]["category"]["enum"]
    prompt = build_system_prompt(meridian)
    assert "vehicle" in prompt and "brake_pressure_psi" in prompt and "P-101" not in prompt


def test_model_output_validation_rejects_hallucinations_and_reasserts_regex_values(meridian):
    report = "Vehicle VH-2101 shows low brake pressure of 52 psi."
    ok = json.dumps({"asset_id": "VH-2101", "category": "brake_system", "symptoms": ["low brake pressure"],
                     "brake_pressure_psi": 61, "coolant_temp_c": None, "safety_flag": False})
    fields, err = validate_fields(ok, meridian, report)
    assert err is None and fields["signals"]["brake_pressure_psi"] == 52.0  # exact value from the text wins
    for bad in ('{"asset_id": "VH-9999", "category": "brake_system", "symptoms": [], "brake_pressure_psi": null, '
                '"coolant_temp_c": null, "safety_flag": false}',          # asset not in the report
                '{"asset_id": "VH-2101", "category": "warp_drive", "symptoms": [], "brake_pressure_psi": null, '
                '"coolant_temp_c": null, "safety_flag": false}',          # category outside the profile
                "not json", "[]"):
        assert validate_fields(bad, meridian, report)[1]


# ---- validation of tenant-supplied configuration ----------------------------------------------------------------------
def _with(**changes):
    return {**MERIDIAN, **changes}


@pytest.mark.parametrize("changes", [
    {"asset_id_pattern": "VH-(\\d+"},                                    # does not compile
    {"asset_id_pattern": "VH-\\d{4}"},                                   # no capture group
    {"asset_id_pattern": "(VH)-(\\d{4})"},                               # two groups
    {"asset_id_pattern": "(a+)+$"},                                      # catastrophic backtracking shape
    {"asset_id_pattern": "(" + "a" * 250 + ")"},                         # too long
    {"categories": [{"name": "other", "keywords": ["x"]}]},              # 'other' is implicit
    {"categories": [{"name": "A-Bad Name", "keywords": ["x"]}]},
    {"priority_rules": [{"priority": "P1", "any": [{"signal": "no_such_signal", "gte": 1}]}]},
    {"priority_rules": [{"priority": "P1", "any": [{"category_in": ["not_a_category"]}]}]},
    {"priority_rules": [{"priority": "P1", "any": [{"flag": "safety", "category_in": ["leak"]}]}]},
    {"priority_rules": [{"priority": "P1", "any": [{"signal": "brake_pressure_psi", "gte": 1, "lte": 2}]}]},
    {"priority_rules": [{"priority": "P9", "any": [{"flag": "safety"}]}]},
    {"enrichments": [{"label": "x1", "connector_kind": "fleet", "path": "/vehicles/../admin", "template": "abc"}]},
    {"enrichments": [{"label": "x1", "connector_kind": "fleet", "path": "http://evil.example/{asset_id}",
                      "template": "abc"}]},
    {"register_kind": "Bad Kind"},
])
def test_invalid_profiles_are_rejected(changes):
    with pytest.raises(ValidationError):
        TenantProfile.model_validate(_with(**changes))


# ---- the generic engine reproduces the built-in (Apex-default) rules ------------------------------------------------------
def _legacy_equivalent() -> TenantProfile:
    return TenantProfile.model_validate({
        "asset_id_pattern": r"\b([A-Z]{1,4}-\d{2,4}[A-Z]?)\b", "register_kind": "equipment_register",
        "guidance_kinds": ["equipment_manual", "inspection_report"], "history_kind": "incident_history",
        "categories": [{"name": n, "keywords": list(k)} for n, k in rules.CATEGORIES],
        "symptoms": [{"name": n, "keywords": list(k)} for n, k in rules.SYMPTOM_KEYWORDS],
        "signals": [{"name": "vibration_mm_s", "regex": r"(\d+(?:\.\d+)?)\s*mm\s*/\s*s", "unit": "mm/s"}],
        "safety_keywords": ["smoke", "fire", "burning smell"],
        "priority_rules": [
            {"priority": "P1", "any": [{"flag": "safety"}, {"signal": "vibration_mm_s", "gte": 11.2}]},
            {"priority": "P2", "any": [{"signal": "vibration_mm_s", "gte": 7.1},
                                       {"category_in": ["leak", "overheating", "electrical_fault"]}]},
            {"priority": "P3", "any": [{"signal": "vibration_mm_s", "gte": 4.5},
                                       {"category_in": ["noise", "mechanical_vibration"]}]},
        ],
    })


def test_generic_engine_matches_builtin_rules_on_the_evaluation_reports():
    profile = _legacy_equivalent()
    reports = [json.loads(x)["text"] for x in (ROOT / "evaluation" / "datasets" / "apex-eval-v1" / "reports.jsonl")
               .read_text(encoding="utf-8").splitlines() if x.strip()]
    reports += ["Pump P-101 shows abnormal vibration at 8.4 mm/s with grinding noise.",
                "Motor M-201 smoking and burning smell.", "P-103 leaking at the seal.", "Something is slow today.",
                "Pump P-102 vibration 4.5 mm/s.", "Pump P-102 vibration 11.2 mm / s with smoke."]
    assert len(reports) >= 20
    for text in reports:
        legacy = rules.parse_report(text)
        generic = engine.parse_report(profile, text)
        assert generic["asset_id"] == legacy["asset_id"], text
        assert generic["category"] == legacy["category"], text
        assert generic["signals"]["vibration_mm_s"] == legacy["vibration_mm_s"], text
        assert generic["safety_flag"] == legacy["smoke_or_fire"], text
        assert engine.decide_priority(profile, generic) == rules.decide_priority(legacy), text
