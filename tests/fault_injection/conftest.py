"""Fault-injection recorder: every scenario records initial state, fault, expected, actual, recovery, final
state, data-integrity result, duplicate external-action count, evidence and pass/fail. The session writes JSON + Markdown
reports to evaluation/failure-reports/phase7/ (the Phase 4 reports are preserved unchanged)."""
import contextlib
import datetime as dt
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "evaluation" / "failure-reports" / "phase7"
RECORDS: list["Scenario"] = []


@dataclass
class Scenario:
    id: str
    name: str
    initial_state: str
    injected_fault: str
    expected_behavior: str
    actual_behavior: str = ""
    recovery_action: str = ""
    final_state: str = ""
    data_integrity: str = ""
    duplicate_external_actions: int | None = None
    evidence: list = field(default_factory=list)
    passed: bool = False
    error: str = field(default="")
    recorded_utc: str = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc).isoformat())


class _Capture(logging.Handler):
    """Collects the application's own structured log lines (already redacted by the JSON formatter) as evidence."""

    def __init__(self):
        super().__init__()
        from app.observability.logging import JsonFormatter
        self.setFormatter(JsonFormatter())
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(self.format(record))


@contextlib.contextmanager
def _scenario(id_, name, initial, fault, expected):
    sc = Scenario(id_, name, initial, fault, expected)
    capture = _Capture()
    logger = logging.getLogger("eaop")
    logger.addHandler(capture)
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        yield sc
        sc.passed = True
    except BaseException as exc:  # noqa: BLE001 - record the failure, then re-raise it
        sc.passed = False
        sc.error = f"{type(exc).__name__}: {str(exc)[:300]}"
        raise
    finally:
        logger.removeHandler(capture)
        logger.setLevel(previous_level)
        interesting = [ln for ln in capture.lines if '"level": "INFO"' not in ln or '"event"' in ln or '"status": 5' in ln]
        sc.evidence = (interesting or capture.lines)[:12]
        sc.evidence.append(f"{len(capture.lines)} structured log line(s) captured during this scenario")
        RECORDS.append(sc)


@pytest.fixture()
def fi():
    return _scenario


def pytest_sessionfinish(session, exitstatus):
    if not RECORDS:
        return
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc)
    latest = {r.id: r for r in RECORDS}  # last record per scenario id
    previous = REPORT_DIR / "fi-report.json"
    if previous.exists():  # keep scenarios not run this session (e.g. opt-in FI-10) with their own timestamps
        try:
            for old in json.loads(previous.read_text(encoding="utf-8"))["scenarios"]:
                latest.setdefault(old["id"], Scenario(**old))
        except (ValueError, KeyError, TypeError):
            pass
    rows = [latest[k] for k in sorted(latest)]
    report = {
        "generated_utc": stamp.isoformat(),
        "command": "RUN_DISRUPTIVE=1 python -m pytest tests/fault_injection -q",
        "environment": {"backends": "deterministic test-only", "database": "eaop_test (PostgreSQL 16 + pgvector)",
                        "mock_services": "local ticketing and inventory mocks", "python": sys.version.split()[0]},
        "summary": {"scenarios": len(rows), "passed": sum(r.passed for r in rows),
                    "failed": sum(not r.passed for r in rows)},
        "scenarios": [asdict(r) for r in rows],
    }
    (REPORT_DIR / "fi-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    md = ["# Fault-injection report (Phase 7: FI-01 to FI-10 per the V4.1 specification)", "", f"Generated {stamp.isoformat()} by `{report['command']}`.",
          "Deterministic test-only AI backends; local mock services; isolated test database.", "",
          f"**{report['summary']['passed']} of {report['summary']['scenarios']} scenarios passed.**", ""]
    for r in rows:
        md += [f"## {r.id}: {r.name} - {'PASS' if r.passed else 'FAIL'}", "", f"*Recorded {r.recorded_utc}*", "",
               f"- **Initial state:** {r.initial_state}", f"- **Injected fault:** {r.injected_fault}",
               f"- **Expected behavior:** {r.expected_behavior}", f"- **Actual behavior:** {r.actual_behavior}",
               f"- **Recovery action:** {r.recovery_action}", f"- **Final state:** {r.final_state}",
               f"- **Data-integrity result:** {r.data_integrity}",
               f"- **Duplicate external actions:** {r.duplicate_external_actions}"]
        if r.error:
            md.append(f"- **Error:** {r.error}")
        md += ["- **Evidence (application log lines, redacted):**"] + [f"  - `{ln[:300]}`" for ln in r.evidence] + [""]
    (REPORT_DIR / "fi-report.md").write_text("\n".join(md), encoding="utf-8")
