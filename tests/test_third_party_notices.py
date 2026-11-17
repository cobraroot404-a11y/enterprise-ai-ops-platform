"""V41-03.02: the third-party notices are complete and current (every direct dependency listed, no unverified or undeclared licence, generated file up to date)."""
import json
import re
from pathlib import Path

from generate_third_party_notices import render

ROOT = Path(__file__).resolve().parents[1]
NOTICES = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
INVENTORY = json.loads((ROOT / "docs" / "security" / "third-party-license-inventory.json").read_text(encoding="utf-8"))


def requirement_names(path: str) -> set[str]:
    names = set()
    for line in (ROOT / path).read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line and not line.startswith("-"):
            names.add(re.split(r"[<>=!~\[; ]", line)[0].lower().replace("_", "-"))
    return names


def test_every_direct_python_requirement_is_in_the_notices():
    listed = {r["name"].lower().replace("_", "-") for r in INVENTORY["python"]}
    for file in ("backend/requirements.txt", "backend/requirements-dev.txt", "backend/requirements-ai.txt"):
        missing = requirement_names(file) - listed
        assert not missing, f"{file}: not in the lock file or notices: {sorted(missing)}"


def test_every_direct_frontend_dependency_is_in_the_notices():
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    declared = set(package.get("dependencies", {})) | set(package.get("devDependencies", {}))
    listed = {r["name"] for r in INVENTORY["node_direct"]}
    assert declared <= listed, sorted(declared - listed)


def test_no_unverified_or_undeclared_licence_remains():
    assert "to verify" not in NOTICES.lower() and "verify at audit" not in NOTICES.lower()
    bad = [r["name"] for r in INVENTORY["python"] + INVENTORY["node_all"] if r["license"] in ("UNDECLARED", "NOT INSTALLED HERE")]
    assert bad == []


def test_models_images_and_tools_are_listed_and_the_text_does_not_overclaim():
    for needle in ("qwen2.5:1.5b", "all-MiniLM-L6-v2", "pgvector/pgvector:pg16", "python:3.12-slim", "nginx:alpine", "Terraform CLI", "Ollama"):
        assert needle in NOTICES, needle
    assert "not a legal review" in NOTICES


def test_generated_files_are_up_to_date():
    # The recorded inventory comes from the reference environment, including
    # platform-specific wheels and Node packages.
    python_lock = (ROOT / "backend" / "requirements.lock.txt").read_text(encoding="utf-8")
    locked_python = dict(line.split("==", 1) for line in python_lock.splitlines() if line and not line.startswith("#"))
    assert {row["name"]: row["version"] for row in INVENTORY["python"]} == locked_python
    assert all(row["installed"] == row["version"] for row in INVENTORY["python"])

    node_lock = json.loads((ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8"))["packages"]
    for row in INVENTORY["node_all"] + INVENTORY["node_direct"]:
        assert node_lock[f"node_modules/{row['name']}"]["version"] == row["version"]

    notices, inventory = render(INVENTORY["python"], INVENTORY["node_direct"], INVENTORY["node_all"])
    assert inventory == INVENTORY
    assert notices == NOTICES
