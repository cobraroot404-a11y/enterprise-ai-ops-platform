"""Numeric evidence trust policy (V41-14.02, architectural remediation V8).

Who may put a number into automated numeric priority is decided HERE, server-side, not by regexes, prompts, schemas or the UI.

Evidence classes
  A  free-text candidate or any LLM-proposed value (including LLM-structured output)  -> UNVERIFIED, never eligible
  C  typed observation from an authenticated, authorised submitter                     -> VALIDATED (checks passed), not eligible until a human verifies it
  D  observation approved through the human-verification workflow                      -> HUMAN_VERIFIED, eligible
  E  independently authenticated sensor/telemetry observation                          -> NOT IMPLEMENTED (no telemetry authentication exists); never claimed
  F  simulated observation from the project's approved simulation fixture              -> SIMULATED_VALIDATED, eligible only for clearly labelled demonstration data

Class F requires an HMAC signature, made with a server-held key (env EAOP_SIMULATION_FIXTURE_KEY) over the tenant and the observation; with no key configured every
simulator claim is rejected, and a caller cannot self-declare simulator provenance. Authentication proves who submitted, not that the measurement is true."""
import hashlib
import hmac
import json
import os

UNVERIFIED, SUBMITTED, VALIDATED = "UNVERIFIED", "SUBMITTED", "VALIDATED"
HUMAN_VERIFIED, SOURCE_AUTHENTICATED, SIMULATED_VALIDATED, REJECTED = "HUMAN_VERIFIED", "SOURCE_AUTHENTICATED", "SIMULATED_VALIDATED", "REJECTED"
ELIGIBLE_STATUSES = frozenset({HUMAN_VERIFIED, SOURCE_AUTHENTICATED, SIMULATED_VALIDATED})
SIMULATION_KEY_ENV = "EAOP_SIMULATION_FIXTURE_KEY"
PENDING_STATUSES = ("unverified", "submitted")  # candidates a human may still verify


def simulation_key() -> bytes | None:
    key = os.environ.get(SIMULATION_KEY_ENV)
    return key.encode() if key else None


def _payload(tenant_id: str, obs: dict, source_id: str) -> bytes:
    body = {"tenant": str(tenant_id), "asset": str(obs.get("asset_id", "")).upper(), "type": obs.get("measurement_type"), "value": float(obs.get("value", 0.0)),
            "unit": str(obs.get("unit", "")), "observed_at": obs.get("observed_at"), "source_id": source_id}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


def sign_simulated_observation(key: bytes, tenant_id: str, obs: dict, source_id: str) -> str:
    """Used by the simulation fixture (and tests) that holds the server key."""
    return hmac.new(key, _payload(tenant_id, obs, source_id), hashlib.sha256).hexdigest()


def verify_simulated_observation(tenant_id: str | None, obs: dict) -> tuple[bool, str]:
    claim = obs.get("simulation") or {}
    key = simulation_key()
    if key is None:
        return False, "simulated provenance is not accepted: no simulation fixture key is configured on this server"
    if not tenant_id or not claim.get("source_id") or not claim.get("signature"):
        return False, "simulated provenance is incomplete"
    expected = sign_simulated_observation(key, tenant_id, obs, str(claim["source_id"]))
    if not hmac.compare_digest(expected, str(claim["signature"])):
        return False, "simulated provenance signature is invalid for this tenant and observation"
    return True, "simulation fixture signature verified"


ENVELOPE_REQUIRED = ("envelope_version", "tenant_id", "incident_id", "observation_id", "source_type", "source_document_id", "source_field", "source_available", "source_missing_reason",
                     "extraction_origin", "trust_class", "original_status", "establishes_truth")


def build_provenance_envelope(rec: dict, *, tenant_id, incident_id, observation_id: str, submitted_by, legacy: bool = False) -> dict:
    """Server-built provenance envelope for ONE numeric candidate. It documents where the candidate came from; it never establishes that the measurement is true.

    Built only from server-held facts (tenant, incident, who submitted, the verifier's own span/offsets). Nothing is taken from the request or the model, and a source reference
    that cannot be established (a value the model proposed with no supporting text, a record created before envelopes existed) is recorded as unavailable with the reason,
    never invented. Structured records keep the submitter-supplied label under `client_source_label` (descriptive, untrusted)."""
    src = rec.get("source")
    prior = rec.get("provenance") or {}
    loc = rec.get("evidence_location")
    span = rec.get("evidence_span")
    if legacy:
        source_type, origin, available, missing = "unknown_legacy", "unknown_legacy", False, "the record predates provenance envelopes, so its original source reference was not captured"
        span, loc = None, None
    elif src == "structured_record":
        sim = bool(rec.get("simulated"))
        source_type = "simulation_fixture" if sim else "structured_observation"
        origin = "simulation_fixture_signature" if sim else "authenticated_submission"
        available, missing = bool(loc and loc.get("field")), None if (loc and loc.get("field")) else "no structured field reference"
    elif src == "report_text" and loc and loc.get("start") is not None:
        source_type, origin, available, missing = "free_text_report", "deterministic_text_analysis", True, None
    elif src == "report_text":
        source_type, origin, available, missing = "free_text_report", "deterministic_text_analysis", False, "the analysis matched the report but kept no span for this record"
    else:  # model_output: a value the model proposed that the report does not support
        source_type, origin, available, missing = "llm_proposal", "llm_proposed_value", False, "the value was proposed by the model and has no supporting span in the report"
        span, loc = None, None
    env = {"envelope_version": 1, "tenant_id": str(tenant_id), "incident_id": str(incident_id), "observation_id": observation_id, "source_type": source_type,
           "source_document_id": str(incident_id) if source_type in ("free_text_report", "simulation_fixture", "structured_observation") and not legacy else None,
           "source_field": ("report_text" if source_type == "free_text_report" else (loc or {}).get("field") if source_type in ("structured_observation", "simulation_fixture") else None),
           "evidence_span": span if available else None, "evidence_location": loc if available else None, "source_available": available, "source_missing_reason": missing,
           "extraction_origin": origin, "trust_class": rec.get("evidence_class"), "original_status": rec.get("status"), "original_trust_status": rec.get("trust_status"),
           "submitted_by": str(submitted_by) if submitted_by else None, "channel": prior.get("channel") or "extract_api", "client_source_label": prior.get("source"),
           "simulation_source_id": rec.get("simulation_source_id"), "establishes_truth": False}
    return env


def apply_trust_policy(records: list[dict]) -> dict[str, float | None]:
    """Assign evidence class / trust status to each audit record and return the ONLY values that may enter automated numeric priority (name -> canonical value)."""
    eligible: dict[str, float | None] = {}
    for rec in records:
        supported = rec["status"] == "verified"  # the text/structure checks found a supported candidate
        cand = rec.get("value") if supported else None
        rec["candidate_value"] = cand
        rec["eligible_for_numeric_priority"] = False
        rec["simulated"] = bool(rec.get("simulated", False))
        if rec["source"] == "structured_record" and supported and rec["simulated"]:
            rec.update({"evidence_class": "F", "trust_status": SIMULATED_VALIDATED, "status": "verified", "verification_status": "verified", "eligible_for_numeric_priority": True,
                        "reason": "simulated observation from the approved simulation fixture (labelled SIMULATED; not field telemetry): " + rec["reason"]})
            rec["verification_reason"] = rec["reason"]
            eligible[rec["name"]] = rec["value"]
        elif rec["source"] == "structured_record" and supported:
            rec.update({"evidence_class": "C", "trust_status": VALIDATED, "status": "submitted", "verification_status": "submitted", "value": None, "review_required": True,
                        "candidate_values": [cand], "reason": "authenticated submission passed validation; it is not eligible for automated priority until a human verifies it"})
            rec["verification_reason"] = rec["reason"]
        elif supported:
            rec.update({"evidence_class": "A", "trust_status": UNVERIFIED, "status": "unverified", "verification_status": "unverified", "value": None, "review_required": True,
                        "candidate_values": [cand], "reason": "free-text candidate supported by the report text; free text is not an evidence source for automated numeric priority, so it awaits human verification"})
            rec["verification_reason"] = rec["reason"]
        else:
            rec.setdefault("evidence_class", "C" if rec["source"] == "structured_record" else "A")
            rec["trust_status"] = REJECTED if rec["source"] == "structured_record" and rec["status"] == "quarantined" else UNVERIFIED
    return eligible
