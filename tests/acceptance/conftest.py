"""Customer acceptance (UAT) harness.

Every scenario records: test id, requirement ids, customer, preconditions, test data, steps, expected result, actual result,
pass/fail, evidence and execution timestamp. The session writes machine-readable JSON and human-readable Markdown reports to
evaluation/customer-acceptance/<mode>/.

Modes (environment variable UAT_BACKEND):
  deterministic (default)  the deterministic TEST-ONLY AI backends: proves workflow, security and integration behaviour.
                           It is NOT acceptance evidence for AI behaviour.
  real                     real Ollama (qwen2.5:1.5b) + MiniLM: the acceptance evidence for scenarios that need AI.
"""
import contextlib
import dataclasses
import datetime as dt
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pytest
from app.main import create_app
from fastapi.testclient import TestClient
from support import ingest_samples, login, make_tenant, onboard_meridian

ROOT = Path(__file__).resolve().parents[2]
MODE = os.environ.get("UAT_BACKEND", "deterministic").lower()
REPORT_DIR = ROOT / "evaluation" / "customer-acceptance" / MODE
RECORDS: list["Uat"] = []


@dataclass
class Uat:
    id: str
    customer: str
    title: str
    requirement_ids: list
    preconditions: str
    test_data: str
    steps: list
    expected: str
    actual: str = ""
    status: str = "FAIL"
    evidence: dict = field(default_factory=dict)
    limitations: str = ""
    backend_mode: str = MODE
    executed_utc: str = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc).isoformat())
    error: str = ""


@contextlib.contextmanager
def _uat(id_, customer, title, requirement_ids, preconditions, test_data, steps, expected, limitations=""):
    record = Uat(id_, customer, title, requirement_ids, preconditions, test_data, steps, expected, limitations=limitations)
    try:
        yield record
        record.status = "PASS"
    except BaseException as exc:  # noqa: BLE001 - record, then re-raise
        record.status = "FAIL"
        record.error = f"{type(exc).__name__}: {str(exc)[:400]}"
        raise
    finally:
        record.executed_utc = dt.datetime.now(dt.timezone.utc).isoformat()
        RECORDS.append(record)


@pytest.fixture()
def uat():
    return _uat


@pytest.fixture(scope="session")
def uat_mode():
    return MODE


@pytest.fixture(scope="session")
def real_stack():
    if MODE != "real":
        return None
    sys.path.insert(0, str(ROOT / "scripts"))
    import ollama_ctl
    from app.ai.embeddings import get_embedder
    from app.ai.llm import get_llm

    ollama_ctl.start()
    model = get_llm("ollama")
    assert model.version() is not None and model.digest, "Ollama and the approved model are required for UAT_BACKEND=real"
    return {"embedder": get_embedder("sentence_transformers"), "llm": model}


@pytest.fixture()
def uat_client(settings, app_db, real_stack):
    if MODE == "real":
        settings = dataclasses.replace(settings, llm_backend="ollama", embedding_backend="sentence_transformers")
    return TestClient(create_app(settings, app_db))


@pytest.fixture()
def apex_uat(uat_client, owner_engine, ticketing, inventory_server):
    tenant = make_tenant(owner_engine, "uatapex", ticketing.url, inventory_server.url)
    ingest_samples(uat_client, login(uat_client, tenant, "support_engineer"))
    return tenant


@pytest.fixture()
def meridian_uat(uat_client, owner_engine, servicedesk_server, fleet_server, crm_server):
    state = servicedesk_server.state
    with state.lock:
        state.tickets.clear()
        state.by_key.clear()
        state.failures.clear()
        state.requests = 0
    return onboard_meridian(uat_client, owner_engine, servicedesk_server, fleet_server, crm_server, "uatmer")


def pytest_sessionfinish(session, exitstatus):
    if not RECORDS:
        return
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    latest = {r.id: r for r in RECORDS}
    previous = REPORT_DIR / "uat-report.json"
    if previous.exists():  # keep scenarios not run in this session
        try:
            for old in json.loads(previous.read_text(encoding="utf-8"))["scenarios"]:
                latest.setdefault(old["id"], Uat(**old))
        except (ValueError, KeyError, TypeError):
            pass
    rows = [latest[k] for k in sorted(latest)]
    stamp = dt.datetime.now(dt.timezone.utc).isoformat()
    ai_note = ("Real Ollama (qwen2.5:1.5b) + MiniLM: acceptance evidence for AI behaviour." if MODE == "real" else
               "Deterministic TEST-ONLY backends: workflow, security and integration evidence only; NOT acceptance evidence for AI behaviour.")
    report = {"generated_utc": stamp, "mode": MODE, "ai_evidence": ai_note,
              "command": f"UAT_BACKEND={MODE} python -m pytest tests/acceptance -q",
              "summary": {"scenarios": len(rows), "passed": sum(r.status == "PASS" for r in rows),
                          "failed": sum(r.status != "PASS" for r in rows)},
              "scenarios": [asdict(r) for r in rows]}
    (REPORT_DIR / "uat-report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md = [f"# Customer acceptance report ({MODE})", "", f"Generated {stamp} by `{report['command']}`.", "", f"**{ai_note}**", "",
          f"**{report['summary']['passed']} of {report['summary']['scenarios']} scenarios passed.**", "",
          "| Test | Customer | Title | Requirements | Result |", "|---|---|---|---|---|"]
    md += [f"| {r.id} | {r.customer} | {r.title} | {', '.join(r.requirement_ids)} | {r.status} |" for r in rows]
    md.append("")
    for r in rows:
        md += [f"## {r.id}: {r.title} - {r.status}", "", f"*Customer: {r.customer}. Backend mode: {r.backend_mode}. Executed {r.executed_utc}*", "",
               f"- **Requirement IDs:** {', '.join(r.requirement_ids)}", f"- **Preconditions:** {r.preconditions}",
               f"- **Test data:** {r.test_data}", "- **Steps:**"] + [f"  {i}. {s}" for i, s in enumerate(r.steps, 1)]
        md += [f"- **Expected result:** {r.expected}", f"- **Actual result:** {r.actual}",
               f"- **Evidence:** `evaluation/customer-acceptance/{MODE}/uat-report.json` (scenario `{r.id}`): "
               + "; ".join(f"{k}={json.dumps(v, default=str)[:160]}" for k, v in r.evidence.items())]
        if r.limitations:
            md.append(f"- **Outstanding limitations:** {r.limitations}")
        if r.error:
            md.append(f"- **Error:** {r.error}")
        md.append("")
    (REPORT_DIR / "uat-report.md").write_text("\n".join(md), encoding="utf-8")
