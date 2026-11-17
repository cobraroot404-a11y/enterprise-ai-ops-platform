"""V41-28.01: the repository has the structure listed in specification Part 28. Every listed directory must contain at least one TRACKED file (git does not store empty directories),
and every listed root file must be tracked. The expected tree is spelled out here, in the specification's order, because the specification text loses its indentation."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = [
    "backend/app/api", "backend/app/auth", "backend/app/core", "backend/app/database", "backend/app/models", "backend/app/schemas", "backend/app/services", "backend/app/connectors",
    "backend/app/ingestion", "backend/app/retrieval", "backend/app/ai", "backend/app/workflows", "backend/app/audit", "backend/app/observability", "backend/migrations", "backend/tests",
    "frontend/src/components", "frontend/src/pages", "frontend/src/hooks", "frontend/src/services", "frontend/src/types", "frontend/src/layouts", "frontend/src/styles", "frontend/tests",
    "workers", "mock-services/crm", "mock-services/inventory", "mock-services/ticketing",
    "evaluation/datasets", "evaluation/benchmarks", "evaluation/customer-acceptance", "evaluation/failure-reports", "evaluation/reports",
    "tests/acceptance", "tests/fault_injection", "infrastructure/docker", "infrastructure/terraform", "infrastructure/kubernetes", "infrastructure/monitoring", "scripts",
    "docs/architecture", "docs/customer-discovery", "docs/customer-delivery", "docs/customer-acceptance", "docs/customer-onboarding", "docs/integrations", "docs/security",
    "docs/deployment", "docs/operations", "docs/reliability", "docs/evaluation", "docs/performance", "sample-data/customer-a", "sample-data/customer-b", ".github/workflows",
]
ROOT_FILES = [".env.example", ".gitignore", ".dockerignore", ".editorconfig", "LICENSE", "THIRD_PARTY_NOTICES.md", "README.md", "SECURITY.md", "CHANGELOG.md", "docker-compose.yml", "Makefile"]
TRACKED = set(subprocess.run(["git", "ls-files"], capture_output=True, text=True, cwd=ROOT, check=True).stdout.splitlines())


def test_every_listed_directory_exists_and_holds_tracked_files():
    empty = [d for d in DIRECTORIES if not any(f.startswith(d + "/") and not f.endswith(".gitkeep") for f in TRACKED)]  # a placeholder file is not content
    assert empty == [], empty


def test_every_listed_root_file_is_tracked():
    assert [f for f in ROOT_FILES if f not in TRACKED] == []


def test_the_specification_tree_listed_here_matches_the_specification_text():
    spec = (ROOT / "docs" / "specification" / "ORIGINAL_MASTER_SPECIFICATION_V4.1.txt").read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(spec) if line.startswith("PART 28"))
    end = next(i for i in range(start, len(spec)) if spec[i].startswith("PART 29"))
    leaves = {line.strip().rstrip("/") for line in spec[start:end]}
    for name in {d.rsplit("/", 1)[-1] for d in DIRECTORIES} | set(ROOT_FILES):
        assert name in leaves, f"{name} is not in the specification's Part 28 listing"


def test_terraform_and_container_files_are_present_not_only_the_directories():
    for path in ("infrastructure/terraform/main.tf", "infrastructure/docker/Dockerfile.backend", "infrastructure/kubernetes/eaop.yaml", "infrastructure/monitoring/prometheus.yml",
                 "frontend/src/layouts/AppLayout.tsx", "frontend/tests/setup.ts"):
        assert path in TRACKED or (ROOT / path).exists(), path
