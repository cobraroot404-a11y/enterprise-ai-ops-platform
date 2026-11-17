"""Incident intelligence: report -> validated structured incident with citations."""
import re
from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.ai import rules
from app.ai.assets import asset_candidates
from app.ai.embeddings import Embedder
from app.ai.llm import LLMClient, LLMOutputInvalid
from app.ai.measurement_trust import (
    ELIGIBLE_STATUSES,
    ENVELOPE_REQUIRED,
    HUMAN_VERIFIED,
    PENDING_STATUSES,
    REJECTED,
    apply_trust_policy,
    build_provenance_envelope,
)
from app.ai.measurements import HOLD_STATUSES, audit_measurements, needs_review
from app.ai.rag import answer_question
from app.ai.tuning import get_tuning
from app.audit import service as audit
from app.connectors.clients import InventoryClient
from app.connectors.egress import tenant_slug
from app.connectors.enrichment import run_enrichments
from app.connectors.http import ConnectorError
from app.core.errors import Invalid, NotFound
from app.models import Connector, Incident
from app.observability.metrics import METRICS
from app.profile import engine
from app.profile.service import get_profile
from app.retrieval.entities import asset_name, resolve_models
from app.retrieval.search import search
from app.schemas.incident import DEFAULT_CATEGORIES, IncidentDraft, RelatedIncident

NO_EVIDENCE_ACTION = ("No supporting documentation was found for this symptom pattern. "
                      "Escalate to a maintenance supervisor for manual diagnosis.")
PART_NUMBER = re.compile(r"\bPN-\d{3,6}\b")


DEFAULT_REGISTER_KIND = "equipment_register"
DEFAULT_GUIDANCE_KINDS = ["equipment_manual", "inspection_report"]
DEFAULT_HISTORY_KIND = "incident_history"


def asset_in_register(session: Session, tenant_id, asset_id: str, register_kind: str = DEFAULT_REGISTER_KIND) -> bool:
    row = session.execute(text(
        "SELECT 1 FROM document_chunks c JOIN documents d ON d.id = c.document_id "
        "WHERE c.tenant_id = :t AND d.tenant_id = :t AND d.lifecycle_status = 'active' AND c.is_current AND d.kind = :k "
        "AND upper(c.record_id) = :a LIMIT 1"),
        {"t": str(tenant_id), "k": register_kind, "a": asset_id.upper()}).first()
    return row is not None


def register_kind_for(session: Session, tenant_id) -> str:
    profile = get_profile(session, tenant_id)
    return profile.register_kind if profile else DEFAULT_REGISTER_KIND


def _related(session: Session, tenant_id, asset_id: str, query: str, embedder: Embedder,
             history_kind: str | None = DEFAULT_HISTORY_KIND) -> list[RelatedIncident]:
    if not history_kind:
        return []
    hits = search(session, tenant_id, f"{asset_id} {query}", embedder, k=6, kinds=[history_kind])
    related = []
    for hit in hits:
        if hit.suspicious or not (hit.overlap >= 0.2 or asset_id in hit.text):
            continue
        related.append(RelatedIncident(record_id=hit.record_id, summary=hit.text[:300], filename=hit.filename,
                                       chunk_id=hit.chunk_id, same_asset=asset_id in hit.text))
    related.sort(key=lambda r: not r.same_asset)
    return related[:3]


def _cited_passage_texts(session: Session, tenant_id, citations: list[dict]) -> list[str]:
    """Full text of the passages the recommendation is grounded in (parts are read from evidence only)."""
    ids = [c["chunk_id"] for c in citations]
    if not ids:
        return []
    rows = session.execute(
        text("SELECT c.text FROM document_chunks c JOIN documents d ON d.id = c.document_id "
             "WHERE c.tenant_id = :t AND d.tenant_id = :t AND d.lifecycle_status = 'active' AND c.id = ANY(CAST(:ids AS uuid[]))"),
        {"t": str(tenant_id), "ids": ids}).all()
    return [r[0] for r in rows]


def _inventory_notes(session: Session, tenant_id, texts: list[str], quiet_if_unconfigured: bool = False) -> list[str]:
    parts = sorted({p for t in texts for p in PART_NUMBER.findall(t)})
    if not parts:
        return []
    row = session.scalar(select(Connector).where(Connector.tenant_id == tenant_id,
                                                 Connector.kind == "inventory"))
    if row is None:
        return [] if quiet_if_unconfigured else ["No inventory connector configured; part availability not checked."]
    client, notes = InventoryClient.from_row(row, tenant_slug=tenant_slug(session, tenant_id)), []
    for part in parts:
        try:
            info = client.get_part(part)
            notes.append(f"{part}: {info['quantity_on_hand']} on hand ({info.get('description', 'part')})")
        except ConnectorError as exc:
            notes.append(f"{part}: inventory lookup failed ({exc.kind})")
    return notes


def _verify_numbers(report_text: str, fields: dict, profile, *, numeric_locale=None, structured=None, provenance=None) -> tuple[dict, list[dict], bool]:
    """V41-14.02: model-proposed numbers are proposals. Only readings the report states for this asset, with their unit, reach the rules
    (see app.ai.measurements.audit_measurements). This check is always on: there is no switch that disables it."""
    asset_id = fields.get("asset_id") or ""

    def is_critical(name: str, value: float) -> bool:
        if profile:
            return engine.decide_priority(profile, {**fields, "signals": {**(fields.get("signals") or {}), name: value}}) in ("P1", "P2")
        return rules.decide_priority({**fields, name: value}) in ("P1", "P2")
    kw = {"numeric_locale": numeric_locale, "structured": structured, "provenance": provenance, "is_critical": is_critical}
    if profile:
        specs = [(sig.name, sig.regex, sig.unit or "") for sig in profile.signals]
        proposed = {name: (fields.get("signals") or {}).get(name) for name, _, _ in specs}
        _usable, records = audit_measurements(report_text, asset_id, specs, proposed, **kw)
        eligible = apply_trust_policy(records)  # ONLY trust-eligible values reach the numeric rules
        usable = {name: eligible.get(name) for name, _, _ in specs}
        fields = {**fields, "signals": usable}
    else:
        specs = [("vibration_mm_s", rules.VIBRATION.pattern, "mm/s")]
        _usable, records = audit_measurements(report_text, asset_id, specs, {"vibration_mm_s": fields.get("vibration_mm_s")}, **kw)
        usable = {"vibration_mm_s": apply_trust_policy(records).get("vibration_mm_s")}
        fields = {**fields, "vibration_mm_s": usable["vibration_mm_s"]}
    # a reading the rules may not use must not survive as a machine-generated symptom either
    dropped = [name for name, value in usable.items() if value is None]
    if dropped:
        pat = re.compile(r"^(?:vibration velocity|" + "|".join(re.escape(n.replace("_", " ")) for n in dropped) + r") [\d.]+(?: \S+)?$", re.IGNORECASE)
        fields = {**fields, "symptoms": [x for x in fields.get("symptoms", []) if not pat.match(x)]}
    return fields, records, needs_review(records)


_RANK = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}


def _flag_urgency(records: list[dict], fields: dict, profile, priority: str) -> bool:
    """A held measurement that, if it were true, would raise the priority to P1/P2 marks the incident for URGENT human review. The incident
    priority itself is never raised by an unverified value; the urgency is a separate, visible indicator."""
    for rec in records:
        if rec["status"] not in HOLD_STATUSES and rec["status"] not in PENDING_STATUSES:
            continue
        best = priority
        for value in rec.get("candidate_values") or []:
            if profile:
                trial = {**fields, "signals": {**(fields.get("signals") or {}), rec["name"]: value}}
                implied = engine.decide_priority(profile, trial)
            else:
                implied = rules.decide_priority({**fields, rec["name"]: value})
            if _RANK[implied] < _RANK[best]:
                best = implied
        rec["implied_priority"] = best
        rec["potentially_critical"] = best in ("P1", "P2") and _RANK[best] < _RANK[priority]
    return any(r.get("potentially_critical") for r in records)


def _numeric_priority(profile, category: str, name: str, value: float) -> str:
    if profile:
        return engine.decide_priority(profile, {"category": category, "signals": {name: value}, "safety_flag": False, "symptoms": []})
    return rules.decide_priority({"category": category, name: value, "smoke_or_fire": False, "symptoms": []})


def verify_measurement(session: Session, *, tenant_id, user_id, incident_id, name: str, decision: str, comment: str, expected_trust_status: str,
                       correlation_id: str | None = None) -> Incident:
    """Human verification of one measurement (evidence class D). Server-controlled transition under a row lock; the reviewer must be authorised by the route,
    must not be the person who created the incident (separation of duties), and the decision must match the current state (no stale or duplicate decisions).
    Approval makes the observation eligible and recomputes numeric priority (never lowering the existing priority); rejection keeps it excluded."""
    incident = session.scalar(select(Incident).where(Incident.id == incident_id, Incident.tenant_id == tenant_id).with_for_update())
    if incident is None:
        raise NotFound("Incident not found")
    if incident.created_by == user_id:
        raise Invalid("The person who created the incident cannot verify its measurements (separation of duties).", code="separation_of_duties", status_code=403)
    records = [dict(r) for r in (incident.measurements or [])]
    idx = next((i for i, r in enumerate(records) if r.get("name") == name and r.get("status") in PENDING_STATUSES), None)
    if idx is None:
        done = next((r for r in records if r.get("name") == name and r.get("trust_status") in (HUMAN_VERIFIED, REJECTED, *ELIGIBLE_STATUSES)), None)
        raise Invalid("No pending candidate measurement with that name" + (f" (already {done['trust_status']})" if done else ""), code="measurement_not_pending", status_code=409)
    rec = records[idx]
    if not rec.get("provenance") or not all(k in rec["provenance"] for k in ENVELOPE_REQUIRED):  # a record created before envelopes existed: say so, never invent a source
        rec["provenance"] = build_provenance_envelope(rec, tenant_id=tenant_id, incident_id=incident.id, observation_id=rec.get("observation_id") or f"{incident.id}:{name}:legacy",
                                                      submitted_by=None, legacy=True)
        rec.setdefault("observation_id", rec["provenance"]["observation_id"])
    original_provenance = dict(rec["provenance"])
    if rec.get("trust_status") != expected_trust_status:
        raise Invalid(f"Stale decision: the measurement is {rec.get('trust_status')}, not {expected_trust_status}", code="stale_measurement_state", status_code=409)
    cand = rec.get("candidate_value")
    if decision == "approve" and cand is None:
        raise Invalid("There is no supported candidate value to approve", code="no_candidate_value", status_code=409)
    now = datetime.now(timezone.utc).isoformat()  # noqa: UP017
    before = incident.priority
    if decision == "approve":
        rec.update({"trust_status": HUMAN_VERIFIED, "evidence_class": "D", "status": "verified", "verification_status": "verified", "value": cand, "eligible_for_numeric_priority": True,
                    "review_required": False, "verified_by": str(user_id), "verified_at": now, "verification_comment": comment,
                    "reason": f"verified by an authorised reviewer on {now}: {comment}", "verification_reason": f"verified by an authorised reviewer on {now}: {comment}"})
        profile = get_profile(session, tenant_id)
        numeric = _numeric_priority(profile, incident.category, name, float(cand))
        new_priority = numeric if _RANK[numeric] < _RANK[before] else before
        applied = "numeric_rule" if new_priority != before else "numeric_rule_no_change"
    else:
        rec.update({"trust_status": REJECTED, "status": "rejected", "verification_status": "rejected", "eligible_for_numeric_priority": False, "review_required": False,
                    "verified_by": str(user_id), "verified_at": now, "verification_comment": comment, "reason": f"rejected by an authorised reviewer on {now}: {comment}",
                    "verification_reason": f"rejected by an authorised reviewer on {now}: {comment}"})
        new_priority, applied = before, "none"
    assert rec["provenance"] == original_provenance  # reviewer metadata never replaces the candidate's own provenance
    verification = {"decision": decision, "transition": f"{expected_trust_status}->{rec['trust_status']}", "reviewer_id": str(user_id), "reviewed_at": now, "comment": comment,
                    "incident_id": str(incident.id), "observation_id": rec.get("observation_id"), "priority_before": before, "priority_after": new_priority, "applied_rule": applied,
                    "provenance_envelope_unchanged": True}
    rec["verification"] = verification
    records[idx] = rec
    incident.measurements = records
    incident.priority = new_priority
    incident.notes = [*incident.notes, f"Measurement {name} {'verified' if decision == 'approve' else 'rejected'} by a reviewer ({now}). Justification: {comment}"]
    event = audit.record(session, tenant_id=tenant_id, actor_id=user_id, action=f"measurement.{'verified' if decision == 'approve' else 'rejected'}", entity_type="incident",
                 entity_id=incident.id, details={"measurement": name, "from": expected_trust_status, "to": rec["trust_status"], "candidate_value": cand, "comment": comment,
                                                 "evidence_class": rec.get("evidence_class"), "observation_id": rec.get("observation_id"), "provenance": original_provenance}, correlation_id=correlation_id)
    session.flush()  # assigns the audit event id so the verification block can link to it
    verification["audit_event_id"] = event.id
    rec["verification"] = verification
    incident.measurements = [*records[:idx], rec, *records[idx + 1:]]
    if decision == "approve":
        audit.record(session, tenant_id=tenant_id, actor_id=user_id, action="incident.priority_decided", entity_type="incident", entity_id=incident.id,
                     details={"tenant_id": str(tenant_id), "incident_id": str(incident.id), "asset_id": incident.asset_id, "observation_id": rec.get("observation_id"),
                              "evidence_class": "D", "verification_status": HUMAN_VERIFIED, "provenance": rec.get("provenance"), "measurement_type": rec.get("measurement_type"),
                              "value": cand, "unit": rec.get("unit"), "applied_rule": applied, "priority_before": before, "priority_after": new_priority, "resulting_priority": new_priority,
                              "numeric_rules_executed": True, "observations": [{"observation_id": rec.get("observation_id"), "evidence_class": "D", "verification_status": HUMAN_VERIFIED,
                                                                                "provenance": original_provenance, "measurement_type": rec.get("measurement_type"), "value": cand,
                                                                                "unit": rec.get("unit"), "simulated": False}],
                              "authorized_by": str(user_id), "decided_at": now, "reason": "numeric rule applied to a human-verified observation"}, correlation_id=correlation_id)
    METRICS.incr("measurement_verifications_total", tenant=str(tenant_id), decision=decision)
    return incident


def extract_incident(session: Session, *, tenant_id, user_id, report_text: str, embedder: Embedder,
                     llm: LLMClient, correlation_id: str | None = None, structured_observations: list[dict] | None = None,
                     numeric_locale: str | None = None) -> Incident:
    fallback_note = None
    profile = get_profile(session, tenant_id)  # None -> the platform's built-in equipment-maintenance defaults
    try:
        with METRICS.timer("llm_seconds", tenant=str(tenant_id), kind="extract", backend=llm.name):
            fields = llm.extract_fields(report_text, profile) if profile else llm.extract_fields(report_text)
        claimed = fields.get("asset_id")
        if claimed and claimed.upper() not in report_text.upper():  # defence in depth for any model client
            raise LLMOutputInvalid("model asset_id does not appear in the report (hallucination)")
    except LLMOutputInvalid as exc:
        METRICS.incr("llm_invalid_output_total", tenant=str(tenant_id), kind="extract")
        # Never trust invalid model output: fall back to deterministic rules and say so on the record.
        fields = engine.parse_report(profile, report_text) if profile else rules.parse_report(report_text)
        fallback_note = f"LLM extraction was invalid ({exc}); deterministic rules were used instead."
    label = profile.asset_label if profile else "equipment"
    if not fields.get("asset_id"):
        raise Invalid(f"Could not identify the {label} ID in the report.", code="asset_not_identified")
    allowed_categories = ({c.name for c in profile.categories} | {"other"}) if profile else set(DEFAULT_CATEGORIES)
    if fields.get("category") not in allowed_categories:
        raise Invalid("Extracted category is not one of the tenant's categories", code="invalid_extraction")
    if not fields.get("symptoms"):
        fields["symptoms"] = ["symptoms not itemized in report"]
    asset_id = fields["asset_id"]
    category = fields["category"]
    tun = get_tuning()
    measurements: list[dict] = []
    unsupported_numbers = False
    # always on (V41-14.02); the legacy tuning flag `numeric_verification` no longer gates it
    fields, measurements, unsupported_numbers = _verify_numbers(
        report_text, fields, profile, numeric_locale=numeric_locale, structured=structured_observations or [],
        provenance={"tenant_id": str(tenant_id), "submitted_by": str(user_id), "channel": "extract_api"})
    if not fields.get("symptoms"):
        fields["symptoms"] = ["symptoms not itemized in report"]
    category_conflict = False
    if tun.category_cross_check:  # E10: the model's category must agree with the deterministic keyword rules (unless they found no keyword)
        rule_category = (engine.parse_report(profile, report_text) if profile else rules.parse_report(report_text))["category"]
        category_conflict = rule_category not in ("other", category)
    # deterministic business rule (built-in defaults or the tenant's configured rules), never model-decided
    priority = engine.decide_priority(profile, fields) if profile else rules.decide_priority(fields)

    urgent_review = _flag_urgency(measurements, fields, profile, priority)

    written_ids = asset_candidates(report_text, profile.asset_id_pattern if profile else None)
    ambiguous_asset = len(written_ids) > 1  # several ids written: the chosen one is not demonstrably THE asset of the report, so a human must confirm it
    register_kind = profile.register_kind if profile else DEFAULT_REGISTER_KIND
    verified = asset_in_register(session, tenant_id, asset_id, register_kind)
    query = f"{category.replace('_', ' ')} {' '.join(fields['symptoms'])}"
    related = _related(session, tenant_id, asset_id, query, embedder,
                       profile.history_kind if profile else DEFAULT_HISTORY_KIND)

    guidance_query = f"troubleshoot {category.replace('_', ' ')} {' '.join(fields['symptoms'])}"
    if tun.guidance_query == "model_category":  # E10: name the equipment model (resolved through the tenant's own register)
        models = sorted({m for ms in resolve_models(session, tenant_id, [asset_id.upper()]).values() for m in ms})
        if models:
            guidance_query = f"troubleshoot {' '.join(models)} {category.replace('_', ' ')} {' '.join(fields['symptoms'])}"
    if tun.guidance_query == "asset_context":  # the equipment's own name (e.g. its family) is the missing context in the baseline query
        name = asset_name(session, tenant_id, asset_id)
        if name:
            guidance_query = f"troubleshoot {name} {category.replace('_', ' ')} {' '.join(fields['symptoms'])}"
    guidance = answer_question(session, tenant_id, guidance_query, embedder, llm, enforce_entities=False,
                               kinds=(profile.guidance_kinds if profile else DEFAULT_GUIDANCE_KINDS))
    notes = [fallback_note] if fallback_note else []
    for rec in measurements:
        if rec["status"] in PENDING_STATUSES:
            notes.append(f"Numeric candidate {rec['name']} = {rec['candidate_value']:g} {rec['unit']} is UNVERIFIED ({rec['evidence_class']}): {rec['reason']}. "
                         "The priority above was not derived from it.")
        if rec["status"] in HOLD_STATUSES:
            proposed = f" (the model proposed {rec['model_proposed_value']:g})" if rec.get("model_proposed_value") is not None else ""
            notes.append(f"Measurement {rec['name']} was not accepted as verified{proposed}: {rec['reason']}. It was not used for the priority.")
    if urgent_review:
        worst = min((r["implied_priority"] for r in measurements if r.get("potentially_critical")), key=lambda p: _RANK[p])
        notes.insert(0, f"URGENT REVIEW: an unverified measurement could indicate {worst}; the priority above was NOT raised because the value is not "
                        "supported by the report. A human must check the measurement before this incident is treated as routine.")
    if category_conflict:
        notes.append("The model's category disagrees with the deterministic keyword rules.")
    if guidance.grounded:
        action, citations = guidance.answer, guidance.citations
    else:
        action, citations = NO_EVIDENCE_ACTION, []
        notes.append("No grounded manual guidance found; escalation recommended.")
    if not verified:
        notes.append(f"{label.capitalize()} {asset_id} was not found in the tenant {label} register.")
    if ambiguous_asset:
        notes.append(f"The report names several {label} ids ({', '.join(written_ids)}); {asset_id} was chosen and must be confirmed by a person.")
    notes += _inventory_notes(session, tenant_id, _cited_passage_texts(session, tenant_id, citations),
                              quiet_if_unconfigured=profile is not None)
    if profile:
        notes += run_enrichments(session, tenant_id, profile, asset_id)

    # Automated external actions need an authorized equipment record AND grounded evidence. Otherwise a
    # human must review the incident before any ticket can be drafted from it.
    review_status = ("pending_review" if (verified and citations and not fallback_note and not unsupported_numbers
                                           and not category_conflict and not ambiguous_asset) else "needs_review")
    if review_status == "needs_review":
        reasons = [r for r, bad in ((f"{label} not in the authorized register", not verified),
                                    ("no grounded evidence", not citations),
                                    ("model output failed validation", bool(fallback_note)),
                                    ("a measurement could not be verified from the report", unsupported_numbers),
                                    ("category disagrees with the deterministic rules", category_conflict),
                                    (f"the report names several {label} ids", ambiguous_asset)) if bad]
        notes.append("Human review required before ticketing: " + "; ".join(reasons) + ".")
    try:
        draft = IncidentDraft(
            tenant_id=tenant_id, asset_id=asset_id, asset_verified=verified, category=category,
            symptoms=fields["symptoms"], related_incidents=related, priority=priority,
            citations=citations, recommended_action=action, notes=notes, review_status=review_status)
    except ValidationError as exc:
        raise Invalid(f"Extracted incident failed validation: {exc.errors()[0]['msg']}",
                      code="invalid_extraction") from exc

    incident = Incident(
        tenant_id=tenant_id, asset_id=draft.asset_id, asset_verified=draft.asset_verified,
        category=draft.category, symptoms=draft.symptoms,
        related_incidents=[r.model_dump() for r in draft.related_incidents], priority=draft.priority,
        citations=[c.model_dump() for c in draft.citations], recommended_action=draft.recommended_action,
        review_status=draft.review_status, report_text=report_text, notes=draft.notes, measurements=measurements,
        extraction_backend=f"{llm.name}{'+rules-fallback' if fallback_note else ''}/{embedder.name}",
        created_by=user_id)
    session.add(incident)
    session.flush()
    if measurements:  # trace each record to the stored report (no new identifiers are invented)
        stamped = []
        for i, m in enumerate(measurements):
            obs_id = f"{incident.id}:{m['name']}:{i}"
            stamped.append({**m, "source_document_id": str(incident.id), "incident_id": str(incident.id), "observation_id": obs_id,
                            "provenance": build_provenance_envelope(m, tenant_id=tenant_id, incident_id=incident.id, observation_id=obs_id, submitted_by=user_id)})
        incident.measurements = stamped
        for m in incident.measurements:  # invariant: no candidate leaves extraction without a complete, server-built envelope
            assert all(k in m["provenance"] for k in ENVELOPE_REQUIRED), "incomplete provenance envelope"
    METRICS.incr("incidents_extracted_total", tenant=str(tenant_id), review_status=review_status)
    audit.record(session, tenant_id=tenant_id, actor_id=user_id, action="incident.extracted",
                 entity_type="incident", entity_id=incident.id,
                 details={"asset_id": asset_id, "priority": priority, "backend": incident.extraction_backend,
                          "related": len(related), "citations": len(citations),
                          "measurements_verified": [m["name"] for m in measurements if m["status"] == "verified"], "review_urgency": "urgent" if urgent_review else "routine",
                          "measurements_unsupported": sum(1 for m in measurements if m["status"] in HOLD_STATUSES),
                          "measurement_decisions": [{"name": m["name"], "status": m["status"], "context": m["context_type"], "reason": m["reason"]} for m in measurements]},
                 correlation_id=correlation_id)
    eligible_obs = [m for m in incident.measurements if m.get("eligible_for_numeric_priority")]
    audit.record(session, tenant_id=tenant_id, actor_id=user_id, action="incident.priority_decided", entity_type="incident", entity_id=incident.id,
                 details={"tenant_id": str(tenant_id), "incident_id": str(incident.id), "asset_id": asset_id, "numeric_rules_executed": bool(eligible_obs),
                          "observations": [{"observation_id": m.get("observation_id"), "evidence_class": m.get("evidence_class"), "verification_status": m.get("trust_status"),
                                            "provenance": m.get("provenance"), "measurement_type": m.get("measurement_type"), "value": m.get("value"), "unit": m.get("unit"),
                                            "simulated": m.get("simulated", False)} for m in eligible_obs],
                          "excluded_candidates": [{"observation_id": m.get("observation_id"), "evidence_class": m.get("evidence_class"), "trust_status": m.get("trust_status")}
                                                  for m in incident.measurements if not m.get("eligible_for_numeric_priority")],
                          "applied_rule": "numeric_rule" if eligible_obs else "non_numeric_rules_only", "resulting_priority": priority,
                          "authorized_by": "trusted_source:simulation_fixture" if eligible_obs else None, "decided_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017
                          "reason": "only trust-eligible observations enter numeric priority" if eligible_obs else "no eligible observation: automated numeric rules did not execute"},
                 correlation_id=correlation_id)
    return incident
