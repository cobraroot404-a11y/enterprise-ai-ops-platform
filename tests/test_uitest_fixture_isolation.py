"""The apex-uitest fixture must stay development-only and isolated from demo/benchmark/production paths."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_seed_uitest_refuses_production():
    env = {**os.environ, "EAOP_ENV": "production", "UITEST_PASSWORD": "synthetic-test-pass-1"}
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "seed_uitest.py")], env=env,
                            capture_output=True, text=True, check=False)
    assert result.returncode != 0 and "production" in (result.stderr + result.stdout).lower()


def test_seed_uitest_requires_explicit_password():
    env = {k: v for k, v in os.environ.items() if k != "UITEST_PASSWORD"}
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "seed_uitest.py")], env=env,
                            capture_output=True, text=True, check=False)
    assert result.returncode != 0 and "UITEST_PASSWORD" in (result.stderr + result.stdout)


def test_fixture_is_marked_and_not_wired_into_deployments():
    source = (ROOT / "scripts" / "seed_uitest.py").read_text(encoding="utf-8")
    assert "[TEST FIXTURE]" in source and "synthetic" in source
    for path in ("docker-compose.yml", ".github/workflows/ci.yml", "Makefile"):
        assert "uitest" not in (ROOT / path).read_text(encoding="utf-8").lower(), path
    apex = (ROOT / "scripts" / "seed_apex.py").read_text(encoding="utf-8")
    assert 'seed_tenant("apex-industrial"' in apex and 'seed_tenant("apex-uitest"' not in apex
    dev = (ROOT / "scripts" / "dev.py").read_text(encoding="utf-8")
    assert '"seed": [[PY, "scripts/seed_apex.py"]]' in dev  # default seed never touches the fixture
