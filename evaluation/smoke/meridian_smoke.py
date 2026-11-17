"""Meridian real-AI SMOKE evaluation (limited functional check, NOT a benchmark).

Runs the real Ollama (qwen2.5:1.5b) and MiniLM models against Meridian's actual tenant-specific documents in an
isolated database (eaop_smoke), next to an Apex tenant for cross-tenant denial checks, and records raw inputs and
outputs plus pass/fail per functional property. It deliberately computes NO precision, recall, citation accuracy or
other quality rates: the sample is a handful of hand-written inputs over a 15-chunk synthetic corpus and says nothing
about AI quality. Comprehensive multi-tenant benchmarking is reserved for Phase 8.

  python scripts/ollama_ctl.py start
  python evaluation/smoke/meridian_smoke.py
  python scripts/ollama_ctl.py stop
"""
import argparse
import copy
import dataclasses
import datetime as dt
import hashlib
import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for sub in ("backend", "scripts", "evaluation/benchmarks", "mock-services/ticketing", "mock-services/inventory",
            "mock-services/servicedesk", "mock-services/fleet", "mock-services/crm"):
    sys.path.insert(0, str(ROOT / sub))

import capture_hardware  # noqa: E402
import crm_app  # noqa: E402
import fleet_app  # noqa: E402
import inventory_app  # noqa: E402
import run_phase3 as p3  # noqa: E402  (reused for ServerThread and version capture; unchanged)
import servicedesk_app  # noqa: E402
import ticketing_app  # noqa: E402
from app.ai.embeddings import get_embedder  # noqa: E402
from app.ai.llm import get_llm  # noqa: E402
from app.connectors import egress  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.database.session import Database  # noqa: E402
from app.main import create_app  # noqa: E402
from app.workflows import worker as worker_mod  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from onboard_tenant import onboard  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

SMOKE_DB = "eaop_smoke"
SAMPLES_A = ROOT / "sample-data" / "customer-a"
APEX_KINDS = {"apex_cp200_pump_manual.pdf": "equipment_manual", "apex_inspection_report_2026q3.pdf": "inspection_report",
              "equipment_register.csv": "equipment_register", "incident_history.csv": "incident_history",
              "maintenance_log.csv": "maintenance_log"}

QUESTIONS = [  # (id, text, answerable)
    ("Q1", "What should I do when the service brake line pressure falls below 55 psi?", True),
    ("Q2", "At what coolant temperature should the thermostat be replaced?", True),
    ("Q3", "What must be done before any under-vehicle maintenance work?", True),
    ("Q4", "Which part replaces a cracked rear brake chamber diaphragm?", True),
    ("Q5", "What is the chief executive's favourite colour?", False),
]
SEARCHES = ["brake line pressure air dryer leak", "coolant temperature thermostat radiator", "VH-2101 service history",
            "refrigeration unit cargo temperature", "telematics alert brake low"]
REPORTS = [  # (id, text, expected asset, expected priority from Meridian's deterministic rules, expected verified)
    ("R1", "Vehicle VH-2101 shows low brake pressure of 52 psi with a hissing noise at the rear axle.", "VH-2101", "P2", True),
    ("R2", "VH-2104 coolant temperature reached 118 C on the hill climb and steam was seen.", "VH-2104", "P1", True),
    ("R3", "VH-2102 brake line pressure is 38 psi and the driver reports poor braking.", "VH-2102", "P1", True),
    ("R4", "VH-2103 has a flat tyre on the rear axle.", "VH-2103", "P3", True),
    ("R5", "Vehicle VH-9999 shows low brake pressure of 50 psi.", "VH-9999", "P2", False),
    ("R6", "There is a strange noise somewhere in the depot but nobody knows which truck.", None, None, None),
]


class Recorder:
    def __init__(self):
        self.checks, self.raw = [], {}

    def check(self, cid: str, description: str, passed: bool, detail=None):
        self.checks.append({"id": cid, "description": description, "passed": bool(passed), "detail": detail})
        print(("PASS " if passed else "FAIL ") + cid, description)


def setup_database(settings):
    admin = create_engine(settings.url("owner").rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {SMOKE_DB} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {SMOKE_DB}"))
    admin.dispose()
    from alembic import command
    from alembic.config import Config
    cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend" / "migrations"))
    cfg.attributes["url"] = settings.url("owner")
    command.upgrade(cfg, "head")


def make_apex(owner, ticketing_url, inventory_url, password):
    slug = "apex-smoke"
    users = {}
    with owner.begin() as conn:
        tid = conn.execute(text("INSERT INTO tenants (slug, name) VALUES (:s, :n) RETURNING id"),
                           {"s": slug, "n": "[SMOKE] Apex comparison tenant (synthetic)"}).scalar()
        for role in ("tenant_admin", "maintenance_supervisor", "support_engineer", "read_only_auditor"):
            email = f"{role}@apex-smoke.example.test"
            uid = conn.execute(text("INSERT INTO users (email, full_name, password_hash) VALUES (:e, :n, :p) RETURNING id"),
                               {"e": email, "n": role, "p": hash_password(password)}).scalar()
            conn.execute(text("INSERT INTO memberships (tenant_id, user_id, role) VALUES (:t, :u, :r)"),
                         {"t": tid, "u": uid, "r": role})
            users[role] = email
        conn.execute(text("INSERT INTO connectors (tenant_id, kind, name, base_url, secret_ref) VALUES "
                          "(:t, 'ticketing', 'smoke-ticketing', :u, 'SMOKE_TICKETING_KEY')"), {"t": tid, "u": ticketing_url})
        conn.execute(text("INSERT INTO connectors (tenant_id, kind, name, base_url) VALUES (:t, 'inventory', "
                          "'smoke-inventory', :u)"), {"t": tid, "u": inventory_url})
    return str(tid), slug, users


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    started = dt.datetime.now(dt.timezone.utc)
    run_id = f"{started:%Y%m%dT%H%M%SZ}_meridian_smoke"
    out = ROOT / "evaluation" / "reports" / "phase5-meridian-smoke" / run_id
    out.mkdir(parents=True, exist_ok=True)
    rec = Recorder()
    password = "Smoke-" + uuid.uuid4().hex  # synthetic, per-run, never stored

    base = get_settings(SMOKE_DB)
    settings = dataclasses.replace(base, jwt_secret="smoke-" + uuid.uuid4().hex, llm_backend="ollama",
                                   embedding_backend="sentence_transformers")
    keys = {"ticketing": "smoke-" + uuid.uuid4().hex, "servicedesk": "smoke-" + uuid.uuid4().hex}
    os.environ["SMOKE_TICKETING_KEY"] = keys["ticketing"]
    os.environ["MERIDIAN_SERVICEDESK_KEY"] = keys["servicedesk"]
    setup_database(settings)
    owner = create_engine(settings.url("owner"))

    policy = egress.EgressPolicy(production=False)  # development-only mock origins, exactly the five local mocks
    egress.set_policy(policy)
    t_app = ticketing_app.create_app(api_key=keys["ticketing"])
    s_app = servicedesk_app.create_app(api_key=keys["servicedesk"])
    urls = {}
    for name, app in (("ticketing", t_app), ("servicedesk", s_app), ("inventory", inventory_app.create_app(api_key="")),
                      ("fleet", fleet_app.create_app(api_key="")), ("crm", crm_app.create_app(api_key=""))):
        urls[name] = p3.ServerThread(app).start()
        policy.add_dev_mock("*", urls[name])

    embedder, llm = get_embedder("sentence_transformers"), get_llm("ollama")
    app_db, worker_db = Database(settings, role="app"), Database(settings, role="worker")
    client = TestClient(create_app(settings, app_db))
    logging.getLogger("eaop").setLevel(logging.WARNING)

    # ---- tenants: Meridian through the public onboarding path, Apex for cross-tenant checks ---------------------------
    config = copy.deepcopy(json.loads((ROOT / "onboarding" / "meridian.json").read_text(encoding="utf-8")))
    config["tenant"]["slug"] = "meridian-smoke"
    for m in config["members"]:
        m["email"] = m["email"].replace("@meridian.", "@meridian-smoke.")
    for c in config["connectors"]:
        c["base_url"] = {"ticketing": urls["servicedesk"], "fleet": urls["fleet"], "crm": urls["crm"]}[c["kind"]]
    with owner.begin() as conn:
        conn.execute(text("INSERT INTO users (email, full_name, password_hash, is_platform_admin) "
                          "VALUES ('platform@smoke.example.test', 'Platform', :p, true)"), {"p": hash_password(password)})
    t0 = time.perf_counter()
    summary = onboard(config, client, password=password, platform=("platform@smoke.example.test", password),
                      log=lambda *_: None)
    rec.raw["meridian_onboarding"] = {"summary": summary, "seconds": round(time.perf_counter() - t0, 2)}
    m_id = summary["tenant_id"]
    m_users = {m["role"]: m["email"] for m in config["members"]}
    a_id, a_slug, a_users = make_apex(owner, urls["ticketing"], urls["inventory"], password)

    def login(slug, users, role):
        r = client.post("/api/v1/auth/login", json={"email": users[role], "password": password, "tenant": slug})
        r.raise_for_status()
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    mh = {r: login("meridian-smoke", m_users, r) for r in m_users}
    ah = {r: login(a_slug, a_users, r) for r in a_users}
    for name, kind in APEX_KINDS.items():
        client.post("/api/v1/documents", headers=ah["support_engineer"], data={"kind": kind},
                    files={"file": (name, (SAMPLES_A / name).read_bytes())}).raise_for_status()

    c = owner.connect()  # kept open for the whole run: read-only helper lookups as the table owner

    def tenant_of_chunk(chunk_id):
        return str(c.execute(text("SELECT tenant_id FROM document_chunks WHERE id = :i"), {"i": chunk_id}).scalar())

    def chunk_row(chunk_id):
        return c.execute(text("SELECT tenant_id, is_current, text FROM document_chunks WHERE id = :i"),
                         {"i": chunk_id}).first()

    profile = c.execute(text("SELECT provider, model, revision, dim FROM embedding_profiles WHERE tenant_id = :t AND active"),
                        {"t": m_id}).first()
    rec.check("S0", "Meridian tenant is indexed with the real MiniLM profile (not the deterministic embedder)",
              profile is not None and profile[0] == "sentence_transformers", dict(zip(("provider", "model", "revision", "dim"), profile or [], strict=False)))

    # ---- S1 retrieval is Meridian-only --------------------------------------------------------------------------
    searches, owners_ok = [], True
    for q in SEARCHES:
        hits = client.post("/api/v1/search", headers=mh["support_engineer"], json={"query": q, "k": 5}).json()["items"]
        owners = [tenant_of_chunk(h["chunk_id"]) for h in hits]
        owners_ok &= all(o == m_id for o in owners) and bool(hits)
        searches.append({"query": q, "results": [{"file": h["filename"], "page": h["page_number"], "record": h["record_id"],
                                                  "similarity": h["similarity"], "tenant_is_meridian": o == m_id}
                                                 for h, o in zip(hits, owners, strict=True)]})
    rec.raw["searches"] = searches
    rec.check("S1", "Every retrieved chunk for every search belongs to Meridian (and each search returned results)", owners_ok)

    # ---- S2 grounded answers: citation ownership and verbatim quotes ------------------------------------------------
    answers, own_ok, verbatim_ok, refuse_ok = [], True, True, True
    for qid, question, answerable in QUESTIONS:
        t0 = time.perf_counter()
        res = client.post("/api/v1/ai/ask", headers=mh["support_engineer"], json={"question": question}).json()
        row = {"id": qid, "question": question, "answerable_by_design": answerable, "grounded": res["grounded"],
               "insufficient_evidence": res["insufficient_evidence"], "answer": res["answer"], "problems": res["problems"],
               "citations": [], "seconds": round(time.perf_counter() - t0, 2)}
        for cit in res["citations"]:
            cr = chunk_row(cit["chunk_id"])
            norm = " ".join(cr.text.lower().split())
            row["citations"].append({"file": cit["filename"], "page": cit["page_number"], "record": cit["record_id"],
                                     "quote": cit["quote"], "chunk_tenant_is_meridian": str(cr.tenant_id) == m_id,
                                     "chunk_is_current": cr.is_current,
                                     "quote_in_chunk": " ".join(cit["quote"].lower().split()).rstrip(".") in norm})
            own_ok &= str(cr.tenant_id) == m_id and cr.is_current
            verbatim_ok &= row["citations"][-1]["quote_in_chunk"]
        if not answerable:
            refuse_ok &= (not res["grounded"]) and not res["citations"]
        answers.append(row)
    rec.raw["answers"] = answers
    rec.check("S2a", "Every citation emitted points at a current Meridian-owned chunk", own_ok,
              {"questions_with_grounded_answer": sum(1 for a in answers if a["grounded"]), "of": len(answers)})
    rec.check("S2b", "Every emitted citation quote is verbatim text of the cited chunk", verbatim_ok)
    rec.check("S2c", "The out-of-scope question received no answer and no citations", refuse_ok)

    # ---- S3 extraction, S4 asset validation, S5 review enforcement ---------------------------------------------------
    extractions, incidents = [], {}
    for rid, report, exp_asset, exp_prio, exp_verified in REPORTS:
        t0 = time.perf_counter()
        resp = client.post("/api/v1/incidents/extract", headers=mh["support_engineer"], json={"report_text": report})
        row = {"id": rid, "report": report, "http_status": resp.status_code, "seconds": round(time.perf_counter() - t0, 2),
               "expected": {"asset": exp_asset, "priority": exp_prio, "asset_verified": exp_verified}}
        if resp.status_code == 201:
            inc = resp.json()
            incidents[rid] = inc
            row["result"] = {k: inc[k] for k in ("asset_id", "asset_verified", "category", "priority", "review_status",
                                                 "recommended_action", "symptoms", "notes", "extraction_backend")}
            row["result"]["citations"] = [{"file": c["filename"], "page": c["page_number"], "record": c["record_id"]}
                                          for c in inc["citations"]]
        else:
            row["error"] = resp.json().get("error", {})
        extractions.append(row)
    rec.raw["extractions"] = extractions
    ok_rows = [r for r in extractions if r["http_status"] == 201]
    rec.check("S3a", "Asset ID extracted exactly as written in every report that contains one",
              all(r["result"]["asset_id"] == r["expected"]["asset"] for r in ok_rows) and len(ok_rows) == 5)
    from app.profile import engine  # noqa: E402
    from app.profile.schema import TenantProfile  # noqa: E402
    profile_model = TenantProfile.model_validate(config["profile"])
    consistent, observations = True, []
    for r in ok_rows:
        det = engine.parse_report(profile_model, r["report"])  # regex-derived signals and safety flag from the text
        recomputed = engine.decide_priority(profile_model, {"category": r["result"]["category"], "signals": det["signals"],
                                                            "safety_flag": det["safety_flag"]})
        consistent &= recomputed == r["result"]["priority"]
        observations.append({"id": r["id"], "model_category": r["result"]["category"], "keyword_rule_category": det["category"],
                             "priority": r["result"]["priority"], "priority_expected_if_category_matched_keywords": r["expected"]["priority"]})
    rec.raw["category_observations"] = observations
    rec.check("S3b", "Priority is exactly what the tenant's deterministic rules give for the extracted category and the regex-derived "
              "readings (the model never sets priority)", consistent)
    rec.check("S3c", "The report without a vehicle ID is rejected (asset_not_identified) rather than guessed",
              extractions[-1]["http_status"] == 422 and extractions[-1]["error"].get("code") == "asset_not_identified")
    rec.check("S4", "Registered vehicles are verified against the fleet register; the unregistered VH-9999 is not",
              all(r["result"]["asset_verified"] == r["expected"]["asset_verified"] for r in ok_rows))
    gate_ok = True
    for inc in incidents.values():
        expected = "pending_review" if (inc["asset_verified"] and inc["citations"]) else "needs_review"
        gate_ok &= inc["review_status"] == expected
    rec.check("S5a", "review_status is pending_review only when the vehicle is registered AND grounded evidence exists",
              gate_ok, {"statuses": {rid: i["review_status"] for rid, i in incidents.items()}})
    blocked = {rid: client.post("/api/v1/tickets", headers=mh["support_engineer"], json={"incident_id": inc["id"]}).status_code
               for rid, inc in incidents.items() if inc["review_status"] == "needs_review"}
    rec.raw["draft_attempts_on_needs_review"] = blocked
    rec.check("S5b", "No ticket can be drafted from an incident in needs_review (HTTP 409)",
              all(code == 409 for code in blocked.values()), blocked)

    # ---- S6 approval and submission with the customer-specific mapping; unregistered asset stays blocked ------------------
    r5 = incidents["R5"]
    client.post(f"/api/v1/incidents/{r5['id']}/review", headers=mh["maintenance_supervisor"],
                json={"decision": "accept", "comment": "Smoke test: supervisor accepts the unregistered vehicle for review."})
    t5 = client.post("/api/v1/tickets", headers=mh["support_engineer"], json={"incident_id": r5["id"]}).json()
    client.post(f"/api/v1/tickets/{t5['id']}/request-approval", headers=mh["support_engineer"])
    unreg = client.post(f"/api/v1/approvals/{t5['id']}/decision", headers=mh["maintenance_supervisor"], json={"decision": "approved"})
    rec.check("S6a", "A supervisor-accepted incident for an UNREGISTERED vehicle still cannot be approved for release",
              unreg.status_code == 409 and unreg.json()["error"]["code"] == "asset_not_registered", unreg.json())

    r1 = incidents["R1"]
    if r1["review_status"] == "needs_review":
        client.post(f"/api/v1/incidents/{r1['id']}/review", headers=mh["maintenance_supervisor"],
                    json={"decision": "accept", "comment": "Smoke test: supervisor reviewed the brake report."})
    t1 = client.post("/api/v1/tickets", headers=mh["support_engineer"], json={"incident_id": r1["id"]}).json()
    client.post(f"/api/v1/tickets/{t1['id']}/request-approval", headers=mh["support_engineer"])
    sent_before = s_app.state.mock.requests
    appr = client.post(f"/api/v1/approvals/{t1['id']}/decision", headers=mh["maintenance_supervisor"], json={"decision": "approved"})
    outcomes = worker_mod.drain(worker_db, worker_mod.WorkerConfig(backoff_base=0))
    final = client.get(f"/api/v1/tickets/{t1['id']}", headers=mh["support_engineer"]).json()
    orders = list(s_app.state.mock.tickets.values())
    rec.raw["submission"] = {"approval_http": appr.status_code, "worker_outcomes": outcomes, "ticket": final,
                             "service_desk_orders": orders, "service_desk_requests_during_run": s_app.state.mock.requests - sent_before,
                             "maintenance_system_tickets": len(t_app.state.mock.tickets)}
    rec.check("S6b", "Approved ticket was submitted once to Meridian's service desk and stored with a WO- id",
              final["state"] == "SUBMITTED" and str(final["external_ticket_id"]).startswith("WO-") and len(orders) == 1)
    rec.check("S6c", "Customer-specific mapping applied: payload keys and urgency follow Meridian's connector config",
              bool(orders) and set(orders[0]["payload"]) == {"summary", "details", "urgency", "vehicle_ref", "source_ref"}
              and orders[0]["payload"]["urgency"] == "high" and orders[0]["payload"]["vehicle_ref"] == "VH-2101")
    rec.check("S6d", "Apex's maintenance ticketing system received nothing from Meridian's workflow",
              len(t_app.state.mock.tickets) == 0)

    # ---- S7 audit completeness -----------------------------------------------------------------------------------------
    audit = client.get("/api/v1/audit", headers=mh["read_only_auditor"], params={"limit": 100}).json()["items"]
    actions = [a["action"] for a in audit]
    needed = {"profile.updated", "incident.extracted", "incident.review_accept", "ticket.drafted", "approval.approved",
              "ticket.submitted", "ai.ask", "document.created"}
    rec.raw["audit_actions_seen"] = sorted(set(actions))
    rec.check("S7", "Audit trail contains every expected event type for the exercised workflow",
              needed <= set(actions) or needed - {"document.created"} <= set(actions), {"missing": sorted(needed - set(actions))})

    # ---- S8 cross-tenant denial -------------------------------------------------------------------------------------------
    denials = {}
    a_inc = client.post("/api/v1/incidents/extract", headers=ah["support_engineer"],
                        json={"report_text": "Pump P-101 shows abnormal vibration at 8.4 mm/s, grinding noise."}).json()
    for role in ("tenant_admin", "maintenance_supervisor", "support_engineer"):
        denials[f"apex.{role}.GET meridian incident"] = client.get(f"/api/v1/incidents/{r1['id']}", headers=ah[role]).status_code
        denials[f"apex.{role}.GET meridian ticket"] = client.get(f"/api/v1/tickets/{t1['id']}", headers=ah[role]).status_code
        denials[f"apex.{role}.approve meridian ticket"] = client.post(f"/api/v1/approvals/{t1['id']}/decision", headers=ah[role],
                                                                        json={"decision": "approved"}).status_code
        denials[f"meridian.{role}.GET apex incident"] = client.get(f"/api/v1/incidents/{a_inc['id']}", headers=mh[role]).status_code
    doc_id = client.get("/api/v1/documents", headers=mh["support_engineer"]).json()["items"][0]["id"]
    denials["apex.GET meridian document"] = client.get(f"/api/v1/documents/{doc_id}", headers=ah["support_engineer"]).status_code
    a_hits = client.post("/api/v1/search", headers=ah["support_engineer"], json={"query": "brake line pressure air dryer VH-2101", "k": 10}).json()["items"]
    a_ans = client.post("/api/v1/ai/ask", headers=ah["support_engineer"], json={"question": "What should I do if brake line pressure is below 55 psi?"}).json()
    leak = [h for h in a_hits if tenant_of_chunk(h["chunk_id"]) == m_id] + [c for c in a_ans["citations"] if tenant_of_chunk(c["chunk_id"]) == m_id]
    rec.raw["cross_tenant"] = {"status_codes": denials, "apex_search_hits": len(a_hits), "meridian_chunks_seen_by_apex": len(leak)}
    rec.check("S8", "Apex users cannot read or act on Meridian objects (and vice versa), and Apex retrieval never returns Meridian chunks",
              all(code in (403, 404, 409, 422) for code in denials.values()) and not leak, denials)

    # ---- write evidence ---------------------------------------------------------------------------------------------------------
    finished = dt.datetime.now(dt.timezone.utc)
    passed = sum(1 for c in rec.checks if c["passed"])
    versions = p3.versions(llm, embedder)
    manifest = {"run_id": run_id, "label": "LIMITED FUNCTIONAL SMOKE TEST - not a statistically representative AI-quality benchmark",
                "command": "python " + " ".join(sys.argv), "started_utc": started.isoformat(), "finished_utc": finished.isoformat(),
                "backends": {"llm": "ollama", "embedding": "sentence_transformers"}, "versions": versions,
                "hardware": capture_hardware.collect(), "database": SMOKE_DB,
                "inputs": {"onboarding_config_sha256": hashlib.sha256((ROOT / "onboarding" / "meridian.json").read_bytes()).hexdigest(),
                           "meridian_documents": [d["file"] for d in config["documents"]],
                           "searches": SEARCHES, "questions": [q[:2] for q in QUESTIONS], "reports": [r[:2] for r in REPORTS]},
                "egress_policy": "development-only mock origins: " + ", ".join(sorted(urls.values())),
                "checks_passed": passed, "checks_total": len(rec.checks)}
    (out / "raw.json").write_text(json.dumps(rec.raw, indent=1, default=str), encoding="utf-8", newline="\n")
    (out / "checks.json").write_text(json.dumps(rec.checks, indent=1, default=str), encoding="utf-8", newline="\n")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str), encoding="utf-8", newline="\n")
    lines = [f"# Meridian real-AI smoke test ({run_id})", "",
             "**Limited functional smoke testing. Not a statistically representative AI-quality benchmark.** The inputs are a "
             "handful of hand-written questions and reports over a 15-chunk synthetic corpus. No precision, recall, citation "
             "accuracy or other rate is claimed. Multi-tenant benchmarking is reserved for Phase 8.", "",
             f"Models: Ollama {versions.get('ollama')} `{versions.get('ollama_model')}` (digest `{str(versions.get('ollama_model_digest'))[:16]}...`), "
             f"{versions.get('embedding_profile')}. Raw outputs: `raw.json`; per-check results: `checks.json`; configuration: `manifest.json`.", "",
             f"Result: **{passed} of {len(rec.checks)} functional checks passed.**", "", "| Check | Property | Result |", "|---|---|---|"]
    lines += [f"| {c['id']} | {c['description']} | {'PASS' if c['passed'] else 'FAIL'} |" for c in rec.checks]
    (out / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"{passed}/{len(rec.checks)} checks passed; written to {out}")
    c.close()
    app_db.dispose()
    worker_db.dispose()
    return 0 if passed == len(rec.checks) else 1


if __name__ == "__main__":
    sys.exit(main())
