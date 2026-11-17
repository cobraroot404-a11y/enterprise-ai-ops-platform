#!/usr/bin/env python
"""Run the V41-17.03 API-quality suite and write evaluation/api-quality/api-quality-evidence.json from the ACTUAL results (JUnit XML).

    python scripts/api_quality_report.py

Each test is named test_pN_*; N maps to one of the nine properties. A property is `verified` only when all of its tests passed, `known_defect` when a strict-xfail test
documents an open defect, and `failed` otherwise. Nothing is hand-entered; the file records the command, commit, snapshot hash and per-test outcomes."""
import hashlib
import re
import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
OUT = ROOT / "evaluation" / "api-quality" / "api-quality-evidence.json"
SUITES = ["tests/test_api_contract.py", "tests/test_api_response_schemas.py", "tests/test_api_response_contract.py", "tests/test_api_error_contract.py"]
PROPERTIES = {1: "typed contracts", 2: "validation", 3: "pagination", 4: "standardized errors", 5: "OpenAPI documentation", 6: "database migrations", 7: "transactions", 8: "constraints",
              9: "indexes"}


def status_counts() -> dict:
    """Success status counts and the error statuses per operation, read from the live OpenAPI document (not from prose)."""
    sys.path.insert(0, str(BACKEND))
    import dataclasses
    from app.core.config import get_settings
    from app.main import create_app
    spec = create_app(dataclasses.replace(get_settings(db_name="eaop_test"), jwt_secret="report-secret-not-for-production-0123456789", llm_backend="deterministic", embedding_backend="deterministic")).openapi()
    success, errors, total = {}, {}, 0
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            total += 1
            for code in op["responses"]:
                if code.startswith("2"):
                    success.setdefault(code, []).append(f"{method.upper()} {path}")
                else:
                    errors[code] = errors.get(code, 0) + 1
    return {"operations": total, "success": {c: len(v) for c, v in sorted(success.items())}, "created_201": sorted(success.get("201", [])), "operations_documenting_each_error_status": dict(sorted(errors.items())),
            "default_validation_schema_documented": "HTTPValidationError" in spec["components"]["schemas"]}


def error_contract(tests) -> dict:
    mine = [t for t in tests if t["test"] in ERROR_TESTS]
    return {"tests": len(mine), "passed": sum(t["outcome"] == "passed" for t in mine), "failed": [t["test"] for t in mine if t["outcome"] != "passed"], "checks": sorted(ERROR_TESTS)}


ERROR_TESTS = {"test_openapi_documents_the_standardized_error_envelope_not_the_framework_default", "test_the_declared_statuses_are_exactly_the_table_and_cover_every_operation",
               "test_every_observed_error_response_conforms_to_the_documented_schema_and_headers", "test_declared_and_emitted_error_statuses_agree_in_both_directions",
               "test_every_observed_error_code_is_named_in_the_status_description", "test_statuses_that_an_operation_cannot_produce_are_not_declared",
               "test_status_counts_and_the_creating_operations_are_exactly_as_documented"}


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        junit = Path(tmp) / "junit.xml"
        cmd = [sys.executable, "-m", "pytest", *SUITES, "-q", "-p", "no:cacheprovider", f"--junitxml={junit}"]
        proc = subprocess.run(cmd, cwd=BACKEND, capture_output=True, text=True)
        tests = []
        for case in ET.parse(junit).getroot().iter("testcase"):
            name = case.get("name")
            outcome = "passed"
            note = None
            for child in case:
                if child.tag in ("failure", "error"):
                    outcome, note = "failed", (child.get("message") or "")[:200]
                elif child.tag == "skipped":
                    outcome, note = ("known_defect" if "xfail" in (child.get("type") or "") or "KNOWN DEFECT" in (child.get("message") or "") else "skipped"), (child.get("message") or "")[:300]
            tests.append({"test": name, "outcome": outcome, "note": note})
    props, supplementary = {}, []
    for t in tests:
        m = re.match(r"test_p(\d)_", t["test"])
        if m:
            props.setdefault(int(m.group(1)), []).append(t)
        else:
            supplementary.append(t)
    summary = {}
    for n, label in PROPERTIES.items():
        rows = props.get(n, [])
        if not rows or any(r["outcome"] == "failed" for r in rows):
            status = "failed"
        elif any(r["outcome"] == "known_defect" for r in rows):
            status = "known_defect"
        else:
            status = "verified"
        summary[f"P{n} {label}"] = {"status": status, "tests": len(rows), "passed": sum(r["outcome"] == "passed" for r in rows), "known_defects": [r["note"] for r in rows if r["outcome"] == "known_defect"]}
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip())
    snap = BACKEND / "tests" / "snapshots" / "openapi_contract.json"
    evidence = {"requirement": "V41-17.03", "title": "API quality: nine properties", "generated_at": datetime.now(timezone(timedelta(hours=-5))).isoformat(timespec="seconds") + " (EST)",
                "command": "cd backend && python -m pytest tests/test_api_contract.py tests/test_api_response_schemas.py tests/test_api_response_contract.py tests/test_api_error_contract.py", "pytest_exit_code": proc.returncode, "commit_at_run": commit, "working_tree_dirty_at_run": dirty,
                "openapi_snapshot_sha256": hashlib.sha256(snap.read_bytes()).hexdigest(), "properties": summary, "tests": tests,
                "runtime_response_compatibility": {"tests": len(supplementary), "passed": sum(t["outcome"] == "passed" for t in supplementary), "failed": [t["test"] for t in supplementary if t["outcome"] == "failed"],
                                       "note": "pre-Batch-3 baseline comparison, strict schema conformance of every runtime response, secret-field scan, error-response contract (Batch 3.1)"},
                "http_status_counts": status_counts(), "error_contract": error_contract(tests),
                "all_nine_verified": all(v["status"] == "verified" for v in summary.values()) and not any(t["outcome"] == "failed" for t in supplementary), "evidence_note": "generated from JUnit results of the run recorded here; same-author tests"}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(evidence, indent=1) + "\n", encoding="utf-8", newline="\n")
    for k, v in summary.items():
        print(f"{k}: {v['status']} ({v['passed']}/{v['tests']})")
    print("exit code of pytest:", proc.returncode, "| all nine verified:", evidence["all_nine_verified"])
    return 0 if proc.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
