"""V41-21 target "transient failure recovery at least 95% in the defined suite" (original specification Part 21).

THE DEFINED SUITE. A case injects a TRANSIENT failure sequence into the mock ticketing system while one or more approved tickets wait in the outbox. A case
is RECOVERED only if every ticket ends SUBMITTED with an external id, the mock holds exactly one external ticket per local ticket (no duplicates, including the
cases where the response is lost after the external ticket was created), and the database and the mock agree. The denominator is the number of cases below.
Not in the denominator, by definition: permanent errors (HTTP 400) and failure windows longer than the worker's attempt budget; those must NOT silently
recover, and are asserted separately as controls (they fail cleanly and a supervisor retry then succeeds).

Run: python -m pytest tests/fault_injection/test_recovery_rate.py -q      (set RECOVERY_REPORT=1 to also write evaluation/recovery/recovery-rate-report.json)
Limits: same-author suite; deterministic AI backends; local mock ticketing; ~11 cases, so the rate is coarse (one miss is 9%); no confidence claim."""
import datetime as dt
import json
import os
import sys

import pytest
from app.workflows import worker
from app.workflows.worker import WorkerConfig
from test_fault_injection import ROOT, approved_ticket, inject, integrity, ticket

TARGET = 0.95
FAST = WorkerConfig(backoff_base=0, http_timeout=1.0)
SLOW_TIMEOUT = WorkerConfig(backoff_base=0, http_timeout=0.4)
REPORT = ROOT / "evaluation" / "recovery" / "recovery-rate-report.json"

# id, description, failure sequence [(mode, count, extra)], tickets in the burst, worker configuration
CASES = [
    ("R01", "HTTP 503 once", [("503", 1, {})], 1, FAST),
    ("R02", "HTTP 503 twice", [("503", 2, {})], 1, FAST),
    ("R03", "HTTP 503 four times (the fifth and last attempt succeeds)", [("503", 4, {})], 1, FAST),
    ("R04", "HTTP 429 with Retry-After twice", [("429", 2, {})], 1, FAST),
    ("R05", "Network timeout once", [("timeout", 1, {"timeout_seconds": 2.0})], 1, SLOW_TIMEOUT),
    ("R06", "Malformed 200 response after the external ticket was created", [("malformed", 1, {})], 1, FAST),
    ("R07", "Response lost after creation, once", [("lost_response", 1, {})], 1, FAST),
    ("R08", "Response lost after creation, twice", [("lost_response", 2, {})], 1, FAST),
    ("R09", "Mixed sequence: 503, lost response, 429", [("503", 1, {}), ("lost_response", 1, {}), ("429", 1, {})], 1, FAST),
    ("R10", "Burst of 5 tickets through a window of 3 consecutive 503s", [("503", 3, {})], 5, FAST),
    ("R11", "Burst of 5 tickets through 3 lost responses", [("lost_response", 3, {})], 5, FAST),
]
RESULTS: list[dict] = []


@pytest.fixture()
def env(client, apex_loaded):
    from support import login

    return {"tenant": apex_loaded, "eng": login(client, apex_loaded, "support_engineer"), "sup": login(client, apex_loaded, "maintenance_supervisor")}


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_transient_failure_case_recovers_without_duplicates(case, client, env, worker_db, ticketing, owner_engine):
    case_id, description, sequence, burst, cfg = case
    tids = [approved_ticket(client, env) for _ in range(burst)]
    for mode, count, extra in sequence:
        inject(ticketing, mode, count, **extra)
    outcomes = worker.drain(worker_db, cfg, max_iterations=200)
    finals = [ticket(client, env, t) for t in tids]
    consistent = integrity(owner_engine, env["tenant"].id, ticketing).startswith("CONSISTENT")
    submitted = all(f["state"] == "SUBMITTED" and f["external_ticket_id"] for f in finals)
    duplicates = len(ticketing.state.tickets) - burst
    recovered = submitted and duplicates == 0 and consistent
    RESULTS.append({"id": case_id, "description": description, "failure_sequence": [f"{m} x{c}" for m, c, _ in sequence], "tickets": burst, "recovered": recovered,
                    "worker_outcomes": outcomes, "max_attempts_used": max(f["attempts"] for f in finals), "duplicate_external_tickets": duplicates, "integrity_consistent": consistent})
    assert recovered, RESULTS[-1]


def test_controls_permanent_errors_and_exhausted_windows_do_not_silently_recover(client, env, worker_db, ticketing):
    permanent = approved_ticket(client, env)
    inject(ticketing, "400", 1)
    worker.drain(worker_db, FAST)
    assert ticket(client, env, permanent)["state"] == "FAILED" and len(ticketing.state.tickets) == 0  # no retry storm on a permanent error
    exhausted = approved_ticket(client, env)
    inject(ticketing, "503", 5)
    worker.drain(worker_db, FAST, max_iterations=200)
    final = ticket(client, env, exhausted)
    assert final["state"] == "FAILED" and final["attempts"] == FAST.max_attempts and len(ticketing.state.tickets) == 0


def test_recovery_rate_over_the_defined_suite_meets_the_target_and_is_reported():
    if len(RESULTS) != len(CASES):
        pytest.skip("the whole suite must run in one session to compute a rate (do not select single cases)")
    recovered = sum(r["recovered"] for r in RESULTS)
    rate = recovered / len(RESULTS)
    report = {"generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "command": "RECOVERY_REPORT=1 python -m pytest tests/fault_injection/test_recovery_rate.py -q",
              "definition": "see the module docstring: a case is recovered iff every ticket ends SUBMITTED, no duplicate external ticket exists, and database and mock agree",
              "environment": {"backends": "deterministic test-only AI backends", "external_system": "local mock ticketing", "python": sys.version.split()[0]},
              "denominator": len(RESULTS), "recovered": recovered, "rate": round(rate, 4), "target": TARGET, "target_met": rate >= TARGET,
              "limits": "same-author suite; 11 cases so the rate is coarse; mock external system; not a production recovery measurement", "cases": sorted(RESULTS, key=lambda r: r["id"])}
    if os.environ.get("RECOVERY_REPORT") == "1":
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    assert rate >= TARGET, report
