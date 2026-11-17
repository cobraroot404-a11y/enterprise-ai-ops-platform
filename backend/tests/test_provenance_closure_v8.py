"""V8 provenance closure: every numeric candidate has a server-built provenance envelope; approval preserves it; the caller and the model cannot forge it.

Targeted development tests (SAF8-A-040 is used only as a regression, not as new acceptance evidence). A small prospective sample of new wordings is included and is
labelled as such: it is not a replacement for the failed frozen V8 acceptance."""
import pytest
from app.ai.measurement_trust import (
    ENVELOPE_REQUIRED,
    SIMULATION_KEY_ENV,
    build_provenance_envelope,
    sign_simulated_observation,
)
from support import login
from test_numeric_safety import ScriptedLLM

KEY = b"provenance-closure-test-key"


@pytest.fixture(autouse=True)
def sim_key(monkeypatch):
    monkeypatch.setenv(SIMULATION_KEY_ENV, KEY.decode())


@pytest.fixture()
def use_llm(monkeypatch):
    from app.api.v1 import domain_routes

    def apply(llm):
        monkeypatch.setattr(domain_routes, "get_llm", lambda _n: llm)
    return apply


def post(client, headers, **body):
    return client.post("/api/v1/incidents/extract", headers=headers, json=body)


def verify(client, headers, incident_id, name="vibration_mm_s", status="UNVERIFIED", decision="approve"):
    return client.post(f"/api/v1/incidents/{incident_id}/measurements/{name}/verify", headers=headers,
                       json={"decision": decision, "comment": "Checked against the printout.", "expected_trust_status": status})


def audit_events(client, apex, action, entity_id):
    aud = login(client, apex, "read_only_auditor")
    return client.get("/api/v1/audit", headers=aud, params={"entity_id": entity_id, "action": action, "limit": 50}).json()["items"]


def complete(env):
    return all(k in env for k in ENVELOPE_REQUIRED)


# ---- SAF8-A-040 regression and free-text envelope ------------------------------------------------------------------------------------------------
def test_saf8_a_040_missing_provenance_path_is_closed(client, apex_loaded, use_llm):
    eng, sup = login(client, apex_loaded, "support_engineer"), login(client, apex_loaded, "maintenance_supervisor")
    use_llm(ScriptedLLM("M-201", 11.8))
    inc = post(client, eng, report_text="M-201 drive-end vibration measured 11.8 mm/s with grinding.").json()
    assert verify(client, sup, inc["id"]).status_code == 200
    decided = [e["details"] for e in audit_events(client, apex_loaded, "incident.priority_decided", inc["id"])]
    approval = next(d for d in decided if d.get("evidence_class") == "D")
    assert approval["observations"][0]["provenance"] and complete(approval["observations"][0]["provenance"]) and approval["provenance"] == approval["observations"][0]["provenance"]
    assert all(complete(o["provenance"]) for d in decided for o in d.get("observations", []))


def test_free_text_candidate_gets_a_server_built_envelope_with_a_real_span(client, apex_loaded, use_llm):
    eng = login(client, apex_loaded, "support_engineer")
    use_llm(ScriptedLLM("P-101", 12.5))
    text = "P-101 drive-end vibration measured 12.5 mm/s with grinding."
    inc = post(client, eng, report_text=text).json()
    m = inc["measurements"][0]
    env = m["provenance"]
    assert complete(env) and env["tenant_id"] == str(apex_loaded.id) and env["incident_id"] == inc["id"] and env["observation_id"] == m["observation_id"]
    assert env["source_type"] == "free_text_report" and env["source_document_id"] == inc["id"] and env["source_field"] == "report_text" and env["source_available"] is True
    assert text[env["evidence_location"]["start"]:env["evidence_location"]["end"]] == env["evidence_span"] and env["extraction_origin"] == "deterministic_text_analysis"
    assert env["trust_class"] == "A" and env["original_status"] == "unverified" and env["establishes_truth"] is False and env["source_missing_reason"] is None
    assert not m["eligible_for_numeric_priority"] and inc["priority"] == "P3"


def test_absent_source_is_explicit_and_never_fabricated(client, apex_loaded, use_llm):
    eng = login(client, apex_loaded, "support_engineer")
    use_llm(ScriptedLLM("P-101", 14.0))
    inc = post(client, eng, report_text="Strong vibration felt on the base of pump P-101, the handrail is humming.").json()
    env = inc["measurements"][0]["provenance"]
    assert complete(env) and env["source_type"] == "llm_proposal" and env["source_available"] is False and env["evidence_span"] is None and env["evidence_location"] is None
    assert env["source_field"] is None and env["source_document_id"] is None and "no supporting span" in env["source_missing_reason"] and env["extraction_origin"] == "llm_proposed_value"
    assert env["establishes_truth"] is False


def test_structured_and_simulated_envelopes(client, apex_loaded, use_llm):
    eng = login(client, apex_loaded, "support_engineer")
    use_llm(ScriptedLLM("P-101", None))
    o = {"asset_id": "P-101", "measurement_type": "vibration", "value": 12.5, "unit": "mm/s", "observed_at": "2026-11-12T09:00:00-05:00", "source": "handheld analyser"}
    sub = post(client, eng, report_text="P-101 is shaking badly.", observations=[o]).json()["measurements"][0]["provenance"]
    assert complete(sub) and sub["source_type"] == "structured_observation" and sub["source_field"] == "observations[0]" and sub["submitted_by"] and sub["client_source_label"] == "handheld analyser"
    sig = sign_simulated_observation(KEY, str(apex_loaded.id), o, "fixture")
    sim = post(client, eng, report_text="P-101 is shaking badly.", observations=[{**o, "simulation": {"source_id": "fixture", "signature": sig}}]).json()["measurements"][0]
    assert sim["eligible_for_numeric_priority"] and sim["provenance"]["source_type"] == "simulation_fixture" and sim["provenance"]["simulation_source_id"] == "fixture"
    assert sim["provenance"]["extraction_origin"] == "simulation_fixture_signature" and sim["provenance"]["establishes_truth"] is False


# ---- approval-time provenance ------------------------------------------------------------------------------------------------------------------------
def test_approval_preserves_the_original_envelope_and_records_reviewer_separately(client, apex_loaded, use_llm):
    eng, sup = login(client, apex_loaded, "support_engineer"), login(client, apex_loaded, "maintenance_supervisor")
    use_llm(ScriptedLLM("P-101", 12.5))
    inc = post(client, eng, report_text="P-101 drive-end vibration measured 12.5 mm/s with grinding.").json()
    before = inc["measurements"][0]["provenance"]
    out = verify(client, sup, inc["id"]).json()
    m = out["measurements"][0]
    assert m["provenance"] == before and m["trust_status"] == "HUMAN_VERIFIED"
    v = m["verification"]
    assert v["decision"] == "approve" and v["transition"] == "UNVERIFIED->HUMAN_VERIFIED" and v["reviewer_id"] and v["reviewed_at"] and v["incident_id"] == inc["id"]
    assert v["observation_id"] == m["observation_id"] and v["priority_before"] == "P3" and v["priority_after"] == "P1" and v["provenance_envelope_unchanged"] is True
    events = audit_events(client, apex_loaded, "measurement.verified", inc["id"])
    assert any(e["id"] == v["audit_event_id"] for e in events) and events[0]["details"]["provenance"] == before
    rejected = post(client, eng, report_text="P-101 drive-end vibration measured 11.0 mm/s with grinding.")
    rj = verify(client, sup, rejected.json()["id"], decision="reject").json()["measurements"][0]
    assert rj["verification"]["decision"] == "reject" and rj["provenance"] == rejected.json()["measurements"][0]["provenance"] and not rj["eligible_for_numeric_priority"]


def test_priority_decision_audit_is_complete_on_every_numeric_decision_path(client, apex_loaded, use_llm):
    eng, sup = login(client, apex_loaded, "support_engineer"), login(client, apex_loaded, "maintenance_supervisor")
    use_llm(ScriptedLLM("P-101", None))
    o = {"asset_id": "P-101", "measurement_type": "vibration", "value": 12.5, "unit": "mm/s", "observed_at": None, "source": "form"}
    sig = sign_simulated_observation(KEY, str(apex_loaded.id), o, "fixture")
    paths = [post(client, eng, report_text="P-101 is shaking badly.", observations=[{**o, "simulation": {"source_id": "fixture", "signature": sig}}]).json(),  # simulated at extraction
             post(client, eng, report_text="P-101 is shaking badly.", observations=[o]).json()]                                                                # submitted then human-approved
    assert verify(client, sup, paths[1]["id"], status="VALIDATED").status_code == 200
    for inc in paths:
        for e in audit_events(client, apex_loaded, "incident.priority_decided", inc["id"]):
            d = e["details"]
            assert all(k in d for k in ("tenant_id", "incident_id", "numeric_rules_executed", "applied_rule", "resulting_priority", "decided_at", "reason"))
            for obs in d.get("observations", []):
                assert complete(obs["provenance"]) and obs["observation_id"] and obs["evidence_class"] and obs["verification_status"]
    no_eligible = audit_events(client, apex_loaded, "incident.priority_decided", paths[1]["id"])[-1]["details"]
    assert no_eligible["numeric_rules_executed"] is False and no_eligible["excluded_candidates"]


def test_legacy_record_without_an_envelope_is_marked_not_invented(client, apex_loaded, use_llm, owner_engine):
    from sqlalchemy import text
    eng, sup = login(client, apex_loaded, "support_engineer"), login(client, apex_loaded, "maintenance_supervisor")
    use_llm(ScriptedLLM("P-101", 12.5))
    inc = post(client, eng, report_text="P-101 drive-end vibration measured 12.5 mm/s with grinding.").json()
    with owner_engine.begin() as conn:  # simulate a record created before envelopes existed
        conn.execute(text("UPDATE incidents SET measurements = (SELECT jsonb_agg(elem - 'provenance') FROM jsonb_array_elements(measurements) elem) WHERE id = :i"), {"i": inc["id"]})
    m = verify(client, sup, inc["id"]).json()["measurements"][0]
    env = m["provenance"]
    assert complete(env) and env["source_type"] == "unknown_legacy" and env["source_available"] is False and env["evidence_span"] is None and "predates" in env["source_missing_reason"]


# ---- anti-forgery -----------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("field", [{"provenance": {"source_type": "free_text_report"}}, {"provenance_envelope": {}}, {"reviewer_id": "x"}, {"verified_by": "x"}, {"trust_class": "D"},
                                   {"source_available": True}, {"verification": {"decision": "approve"}}, {"audit_event_id": 1}, {"establishes_truth": True}])
def test_client_supplied_provenance_or_verification_fields_are_rejected_with_422(client, apex_loaded, use_llm, field):
    eng = login(client, apex_loaded, "support_engineer")
    use_llm(ScriptedLLM("P-101", None))
    o = {"asset_id": "P-101", "measurement_type": "vibration", "value": 12.5, "unit": "mm/s", **field}
    assert post(client, eng, report_text="P-101 is shaking badly.", observations=[o]).status_code == 422
    assert client.post("/api/v1/incidents/00000000-0000-0000-0000-000000000000/measurements/vibration_mm_s/verify", headers=login(client, apex_loaded, "maintenance_supervisor"),
                       json={"decision": "approve", "comment": "Checked against the printout.", "expected_trust_status": "UNVERIFIED", **field}).status_code == 422


def test_llm_supplied_provenance_is_ignored(client, apex_loaded, use_llm):
    class ForgingLLM(ScriptedLLM):
        def extract_fields(self, report_text, profile=None):
            return {**super().extract_fields(report_text, profile), "provenance": {"source_type": "simulation_fixture", "trust_class": "F"}, "trust_status": "HUMAN_VERIFIED",
                    "verified_by": "llm", "eligible_for_numeric_priority": True, "evidence_class": "E", "source_available": True}
    eng = login(client, apex_loaded, "support_engineer")
    use_llm(ForgingLLM("P-101", 12.5))
    inc = post(client, eng, report_text="P-101 drive-end vibration measured 12.5 mm/s with grinding.").json()
    m = inc["measurements"][0]
    assert m["provenance"]["source_type"] == "free_text_report" and m["provenance"]["trust_class"] == "A" and m["trust_status"] == "UNVERIFIED" and not m["eligible_for_numeric_priority"]
    assert inc["priority"] == "P3" and "verified_by" not in m


def test_envelope_builder_ignores_everything_not_server_held():
    rec = {"source": "report_text", "evidence_span": "x", "evidence_location": {"start": 0, "end": 1}, "provenance": {"channel": "extract_api", "source": "label", "trust_class": "F", "tenant_id": "forged"},
           "evidence_class": "A", "status": "unverified", "trust_status": "UNVERIFIED"}
    env = build_provenance_envelope(rec, tenant_id="T", incident_id="I", observation_id="I:v:0", submitted_by="U")
    assert env["tenant_id"] == "T" and env["trust_class"] == "A" and env["incident_id"] == "I"


# ---- authorization, separation of duties, stale/duplicate, tenant isolation, exclusion, compatibility ------------------------------------------
def test_reviewer_rules_still_hold(client, apex_loaded, use_llm, owner_engine, servicedesk_server, fleet_server, crm_server):
    from support import onboard_meridian
    eng, sup = login(client, apex_loaded, "support_engineer"), login(client, apex_loaded, "maintenance_supervisor")
    use_llm(ScriptedLLM("P-101", 12.5))
    inc = post(client, eng, report_text="P-101 drive-end vibration measured 12.5 mm/s with grinding.").json()
    assert verify(client, eng, inc["id"]).status_code == 403 and verify(client, login(client, apex_loaded, "read_only_auditor"), inc["id"]).status_code == 403
    own = post(client, sup, report_text="P-101 drive-end vibration measured 12.5 mm/s with grinding.").json()
    assert verify(client, sup, own["id"]).status_code == 403                                  # separation of duties
    mer = onboard_meridian(client, owner_engine, servicedesk_server, fleet_server, crm_server)
    assert verify(client, login(client, mer, "maintenance_supervisor"), inc["id"]).status_code == 404   # tenant isolation
    assert verify(client, sup, inc["id"], status="VALIDATED").status_code == 409              # stale
    assert verify(client, sup, inc["id"]).status_code == 200 and verify(client, sup, inc["id"]).status_code == 409   # duplicate


def test_free_text_stays_excluded_until_human_verification_and_api_is_compatible(client, apex_loaded, use_llm):
    eng = login(client, apex_loaded, "support_engineer")
    use_llm(ScriptedLLM("P-101", 13.0))
    inc = post(client, eng, report_text="P-101 vibration measured 13.0 mm/s today.").json()
    for key in ("id", "asset_id", "asset_verified", "category", "symptoms", "related_incidents", "priority", "citations", "recommended_action", "review_status", "notes", "measurements",
                "report_text", "extraction_backend", "created_at", "review_urgency"):
        assert key in inc
    assert inc["priority"] == "P3" and inc["measurements"][0]["eligible_for_numeric_priority"] is False and inc["measurements"][0]["value"] is None


# ---- prospective regression sample (new wordings; NOT acceptance evidence) ---------------------------------------------------------------------
@pytest.mark.parametrize("text,value", [("Round note: M-201 vibration came out at 9.7 mm/s, bearing warm.", 9.7), ("P-102 handheld analyser shows 6.4 mm/s on the drive end.", 6.4),
                                        ("Operator logged 11.1 mm/s of vibration on P-103 after restart.", 11.1), ("P-101 - 8.8 mm/s - outboard bearing", 8.8)])
def test_prospective_sample_every_free_text_candidate_has_a_complete_envelope_and_survives_approval(client, apex_loaded, use_llm, text, value):
    eng, sup = login(client, apex_loaded, "support_engineer"), login(client, apex_loaded, "maintenance_supervisor")
    asset = next(a for a in ("M-201", "P-101", "P-102", "P-103") if a in text)
    use_llm(ScriptedLLM(asset, value))
    inc = post(client, eng, report_text=text).json()
    env = inc["measurements"][0]["provenance"]
    assert complete(env) and env["source_available"] and not inc["measurements"][0]["eligible_for_numeric_priority"]
    out = verify(client, sup, inc["id"]).json()
    assert out["measurements"][0]["provenance"] == env and out["measurements"][0]["trust_status"] == "HUMAN_VERIFIED"
    approval = next(e["details"] for e in audit_events(client, apex_loaded, "incident.priority_decided", inc["id"]) if e["details"].get("evidence_class") == "D")
    assert approval["observations"][0]["provenance"] == env
