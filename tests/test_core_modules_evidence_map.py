"""P9L417: the evidence map covers all 13 spec modules in order and cites only paths that exist."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "docs" / "architecture" / "core-modules-evidence-map.md"
MODULES = ["Authentication", "Tenant Management", "Customer Configuration", "Enterprise Connectors", "Document Ingestion",
           "Retrieval Engine", "AI Inference", "Incident Intelligence", "Workflow Orchestration", "Audit Logging",
           "Observability", "Evaluation", "Customer Dashboard"]


def test_all_13_modules_in_spec_order_with_code_test_and_evidence_cells():
    text = MAP.read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if re.match(r"\| \d+ \|", line)]
    assert [r.split("|")[2].strip() for r in rows] == MODULES
    for r in rows:
        cells = [c.strip() for c in r.split("|")[3:6]]
        assert all("`" in c for c in cells), r
        assert "tests" in cells[1] or "test_" in cells[1] or ".spec." in cells[1] or ".test." in cells[1]


def test_every_cited_path_exists_and_limits_are_stated():
    text = MAP.read_text(encoding="utf-8")
    paths = set(re.findall(r"`([A-Za-z0-9_./-]+(?:\.[a-z]+|/))`", text))
    paths = {p for p in paths if "/" in p and not p.startswith("GET")}
    assert len(paths) >= 30
    assert [p for p in sorted(paths) if not (ROOT / p).exists()] == []
    assert "read-only registry" in text and "not started or managed through the API" in text
    assert "OpenTelemetry" in text and "same-author" in text
