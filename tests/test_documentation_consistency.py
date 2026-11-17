"""Batch 4 documentation consistency: the README, runbook, architecture and demo guides only reference files, scripts, environment variables and ports that exist.

Static checks only (nothing is started). They verify references; they do not prove that a command works: which commands were actually executed is recorded in
docs/planning/batch4-report.md."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ["README.md", "docs/operations/local-runbook.md", "docs/architecture/system-architecture.md", "docs/customer-delivery/apex-demo-guide.md",
        "docs/customer-delivery/meridian-demo-guide.md", "docs/customer-delivery/demo-handover.md"]
PATH_PREFIXES = ("backend/", "frontend/", "docs/", "scripts/", "evaluation/", "tests/", "onboarding/", "sample-data/", "mock-services/", "workers/", "infrastructure/")
PATH_SUFFIXES = (".md", ".py", ".json", ".yml", ".csv", ".txt", ".ts", ".tsx", ".sql")


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_markdown_links_resolve():
    broken = []
    for rel in DOCS:
        base = (ROOT / rel).parent
        for target in re.findall(r"\]\(([^)\s]+)\)", read(rel)):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            path = target.split("#")[0]
            if path and not (base / path).resolve().exists():
                broken.append((rel, target))
    assert broken == []


def test_backticked_repository_paths_exist():
    missing = []
    for rel in DOCS:
        for token in re.findall(r"`([^`\n]+)`", read(rel)):
            token = token.strip().split(" ")[0].rstrip(",.;:")
            if token.startswith(PATH_PREFIXES) and token.endswith(PATH_SUFFIXES) and not re.search(r"[*<>{}$]", token) and not (ROOT / token).exists():
                missing.append((rel, token))
    assert missing == []


def test_dev_script_tasks_named_in_the_docs_exist():
    dev = read("scripts/dev.py")
    tasks = set(re.findall(r'^\s*"([a-z-]+)": \[', dev, re.M)) | set(re.findall(r'^\s*"([a-z]+)": \[PY', dev, re.M)) | {"stack"}
    used = set()
    for rel in DOCS:
        used |= set(re.findall(r"scripts/dev\.py ([a-z-]+)", read(rel)))
    assert used and used <= tasks, used - tasks


def test_environment_variable_names_in_the_runbook_exist_in_the_example_file():
    example = {m.group(1) for m in re.finditer(r"^#?\s*([A-Z][A-Z0-9_]{3,})=", read(".env.example"), re.M)}
    runbook = read("docs/operations/local-runbook.md")
    section = runbook.split("## 2. Environment configuration", 1)[1].split("Two backend modes", 1)[0]
    named = set(re.findall(r"`([A-Z][A-Z0-9_]{3,})`", section))
    assert named and named <= example, named - example


def test_documented_ports_match_the_launcher():
    dev = read("scripts/dev.py")
    ports = set(re.findall(r'"--port", "(\d+)"', dev))
    assert ports == {"8000", "8101", "8102", "8103", "8104", "8105", "8106"}  # 8106: the records mock (Batch 11A)
    architecture = read("docs/architecture/system-architecture.md") + read("docs/operations/local-runbook.md")
    for port in sorted(ports) + ["5173", "11434", "5432"]:
        assert port in architecture, port


def test_requirement_closure_is_recorded_consistently():
    import json
    items = json.loads(read("docs/specification/v4.1-requirements.json"))
    items = items["requirements"] if isinstance(items, dict) else items
    by_id = {r["id"]: r for r in items}
    assert by_id["V41-17.03"]["status"] == "V"
    numeric_validation = by_id["V41-14.02"]
    assert numeric_validation["status"] == "V"
    assert "docs/planning/gate-c-owner-disposition.md" in numeric_validation["evidence"]
    assert "63/64" in numeric_validation["gap"]
    assert {k: by_id[k]["status"] for k in ("V41-12.03", "V41-12.04", "V41-12.05")} == {"V41-12.03": "V", "V41-12.04": "V", "V41-12.05": "V"}  # owner decision, 2026-11-13
    assert {k: by_id[k]["status"] for k in ("V41-12.01", "V41-11.01")} == {"V41-12.01": "V", "V41-11.01": "V"}  # Batch 11B assessment (webhooks and CSV connector now exist), recorded for owner review
    assert {k: by_id[k]["status"] for k in ("V41-11.02", "V41-16.04")} == {"V41-11.02": "V", "V41-16.04": "V"}  # shared (PostgreSQL) rate limiting with tests across processes, owner-directed work after the release candidate; per-process concurrency limits and the absence of IP-keyed or edge limits are recorded limitations


def test_readme_does_not_claim_production_readiness_or_full_compliance():
    text = read("README.md").lower()
    for phrase in ("production-ready", "production ready", "fully compliant", "fully implements"):
        assert phrase not in text
    assert "not a production system" in text and "proprietary source-visible license" in text
