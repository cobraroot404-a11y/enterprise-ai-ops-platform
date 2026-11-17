"""Read-only audit checks that back the V4.1 reconciliation (no application behaviour is touched).

    python scripts/spec_audit_checks.py

Prints a JSON summary and writes docs/specification/v4.1-audit-check-results.json. Each check states what it compared and the command-level
evidence, so a reviewer can re-run it. Checks: original-specification integrity, LICENSE text versus the specification's exact license text,
repository structure versus Part 28, API namespaces versus Part 17, database entities versus Part 17, frontend pages versus Part 18,
Git provenance (authors, trailers, remote), unintended branding, Docker Compose services versus Part 23, directory contents.
"""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs/specification/ORIGINAL_MASTER_SPECIFICATION_V4.1.txt"
EXPECTED_SHA256 = "b1c573e2c209ac68712b36851d56af0fb4c464509b422f96899761b6427760da"


def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True, cwd=ROOT).stdout


def norm(s):
    return [line.rstrip() for line in s.replace("\r\n", "\n").split("\n")]


def main():
    out = {}
    raw = SPEC.read_bytes()
    blob = subprocess.run(["git", "show", f"HEAD:{SPEC.relative_to(ROOT).as_posix()}"], capture_output=True, cwd=ROOT).stdout
    out["spec_integrity"] = {"working_tree_sha256": hashlib.sha256(raw).hexdigest(), "committed_blob_sha256": hashlib.sha256(blob).hexdigest(), "expected": EXPECTED_SHA256,
                             "working_tree_matches": hashlib.sha256(raw).hexdigest() == EXPECTED_SHA256, "committed_blob_matches": hashlib.sha256(blob).hexdigest() == EXPECTED_SHA256,
                             "bytes": len(raw), "lines": raw.decode("utf-8").count("\n")}
    spec_lines = norm(raw.decode("utf-8"))
    # license: exact text between the markers in the specification (Part 3) versus LICENSE
    start = spec_lines.index("Proprietary Source-Visible License")
    end = spec_lines.index("Proprietary Source-Visible Software. Not Open Source.")
    want = [x for x in spec_lines[start:end + 1]]
    have = norm((ROOT / "LICENSE").read_text(encoding="utf-8"))
    while have and not have[-1]:
        have.pop()
    out["license_exact"] = {"spec_lines": f"{start + 1}-{end + 1}", "identical": want == have, "spec_line_count": len(want), "license_line_count": len(have)}
    if want != have:
        first = next((i for i, (a, b) in enumerate(zip(want, have, strict=False)) if a != b), min(len(want), len(have)))
        out["license_exact"]["first_difference_line"] = first + 1
    # repository structure (Part 28)
    dirs = ["backend/app/api", "backend/app/auth", "backend/app/core", "backend/app/database", "backend/app/models", "backend/app/schemas", "backend/app/services", "backend/app/connectors",
            "backend/app/ingestion", "backend/app/retrieval", "backend/app/ai", "backend/app/workflows", "backend/app/audit", "backend/app/observability", "backend/migrations", "backend/tests",
            "frontend/src/components", "frontend/src/pages", "frontend/src/hooks", "frontend/src/services", "frontend/src/types", "frontend/src/layouts", "frontend/src/styles", "frontend/tests",
            "workers", "mock-services/crm", "mock-services/inventory", "mock-services/ticketing", "evaluation/datasets", "evaluation/benchmarks", "evaluation/customer-acceptance",
            "evaluation/failure-reports", "evaluation/reports", "tests/acceptance", "tests/fault_injection", "infrastructure/docker", "infrastructure/terraform", "infrastructure/kubernetes",
            "infrastructure/monitoring", "scripts", "docs/architecture", "docs/customer-discovery", "docs/customer-delivery", "docs/customer-acceptance", "docs/customer-onboarding",
            "docs/integrations", "docs/security", "docs/deployment", "docs/operations", "docs/reliability", "docs/evaluation", "docs/performance", "sample-data/customer-a",
            "sample-data/customer-b", ".github/workflows"]
    files = [".env.example", ".gitignore", ".dockerignore", ".editorconfig", "LICENSE", "THIRD_PARTY_NOTICES.md", "README.md", "SECURITY.md", "CHANGELOG.md", "docker-compose.yml", "Makefile"]
    tracked = set(git("ls-files").splitlines())

    def content(d):
        return sorted(p for p in tracked if p.startswith(d + "/") and not p.endswith(".gitkeep"))

    out["structure"] = {"directories": {d: {"exists": (ROOT / d).is_dir(), "tracked_content_files": len(content(d))} for d in dirs},
                        "root_files": {f: (ROOT / f).is_file() for f in files}}
    out["structure"]["missing_dirs"] = [d for d, v in out["structure"]["directories"].items() if not v["exists"]]
    out["structure"]["empty_dirs"] = [d for d, v in out["structure"]["directories"].items() if v["exists"] and v["tracked_content_files"] == 0]
    out["structure"]["missing_root_files"] = [f for f, ok in out["structure"]["root_files"].items() if not ok]
    # API namespaces
    prefixes = set()
    for p in (ROOT / "backend/app/api").rglob("*.py"):  # routers declare their own prefix; main.py mounts them under /api/v1
        prefixes |= {f"/api/v1{x}" for x in re.findall(r'APIRouter\(prefix="(/[a-z_]+)"', p.read_text(encoding="utf-8"))}
    assert 'prefix = "/api/v1"' in (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
    needed = ["auth", "tenants", "connectors", "documents", "ingestion", "search", "ai", "incidents", "tickets", "approvals", "workflows", "audit", "metrics", "health"]
    out["api_namespaces"] = {n: (f"/api/v1/{n}" in prefixes) for n in needed}
    out["api_namespaces_found"] = sorted(prefixes)
    # database entities
    tables = set()
    for p in (ROOT / "backend/app").rglob("*.py"):
        tables |= set(re.findall(r'__tablename__\s*=\s*"([a-z_]+)"', p.read_text(encoding="utf-8")))
    mig = " ".join(p.read_text(encoding="utf-8") for p in (ROOT / "backend/migrations/versions").glob("*.py"))
    created = set(re.findall(r"CREATE TABLE (?:IF NOT EXISTS )?([a-z_]+)", mig, re.IGNORECASE))
    out["database"] = {"model_tables": sorted(tables), "migration_tables": sorted(created)}
    required_entities = {"Tenants": "tenants", "Users": "users", "Roles": "roles", "Memberships": "memberships", "Connectors": "connectors", "Documents": "documents", "Document versions": "document_versions",
                         "Document chunks": "document_chunks", "Embeddings": "embeddings", "Ingestion jobs": "ingestion_jobs", "Incidents": "incidents", "Tickets": "tickets", "Approvals": "approvals",
                         "Workflow executions": "workflow_executions", "Outbox events": "outbox_events", "Audit events": "audit_events", "Evaluation runs": "evaluation_runs"}
    all_tables = tables | created
    out["database"]["required_entities"] = {k: (v in all_tables) for k, v in required_entities.items()}
    # frontend pages
    nav = (ROOT / "frontend/src/nav.ts").read_text(encoding="utf-8")
    out["frontend_pages"] = {"nav_labels": re.findall(r'label:\s*"([^"]+)"', nav)}
    # git provenance
    log = git("log", "--format=%an|%ae|%cn|%ce|%b%x1e").split("\x1e")
    authors = sorted({"|".join(x.strip().split("|")[:2]) for x in log if x.strip()})
    committers = sorted({"|".join(x.strip().split("|")[2:4]) for x in log if x.strip()})
    trailers = [x for x in log if re.search(r"(?im)^(co-authored-by|signed-off-by|generated)", x)]
    out["git"] = {"commits": len(git("rev-list", "--all").split()), "distinct_authors": authors, "distinct_committers": committers, "commits_with_trailer_lines": len(trailers),
                  "remotes": git("remote").split(), "tags": git("tag").split(), "branches": git("branch", "--format=%(refname:short)").split()}
    # branding
    pat = re.compile(r"(claude|anthropic|chatgpt|openai|cursor|copilot|generated (?:by|with)|co-authored)", re.IGNORECASE)
    hits = {}
    for f in tracked:
        if f.endswith(("package-lock.json", ".pdf", ".png", ".lock")) or f == SPEC.relative_to(ROOT).as_posix() or f.startswith(("evaluation/reports/", "evaluation/datasets/", "frontend/node_modules")):
            continue
        try:
            body = (ROOT / f).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        m = pat.findall(body)
        if m:
            hits[f] = sorted({x.lower() for x in m})
    out["branding"] = {"files_with_matches": hits}
    # docker compose services
    comp = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    out["docker_compose"] = {"services": re.findall(r"^  ([a-z0-9_-]+):\s*$", comp, re.MULTILINE)}
    out["tracked_counts"] = {"ci_workflows": [p for p in tracked if p.startswith(".github/workflows/")], "terraform_files": [p for p in tracked if p.startswith("infrastructure/terraform/") and not p.endswith(".gitkeep")],
                             "dockerfiles": [p for p in tracked if "Dockerfile" in p], "third_party_notices_bytes": (ROOT / "THIRD_PARTY_NOTICES.md").stat().st_size if (ROOT / "THIRD_PARTY_NOTICES.md").exists() else 0,
                             "security_md_bytes": (ROOT / "SECURITY.md").stat().st_size if (ROOT / "SECURITY.md").exists() else 0}
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8") if (ROOT / ".gitignore").exists() else ""
    out["secrets_hygiene"] = {"env_ignored": bool(re.search(r"^\.env\b", gi, re.MULTILINE)), "tracked_env_files": [p for p in tracked if p.split("/")[-1].startswith(".env") and not p.endswith(".example")]}
    (ROOT / "docs/specification/v4.1-audit-check-results.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(out, indent=1)[:9000])


if __name__ == "__main__":
    sys.exit(main())
