"""Regression tests: test credentials and test-only configuration stay inside isolated test environments."""
import dataclasses
import subprocess
import sys
from pathlib import Path

import e2e_guard
import pytest
import secret_scan
from app.core import production_guard
from app.core.config import get_settings
from app.core.production_guard import ProductionConfigError, assert_production_safe
from app.main import create_app
from sqlalchemy import create_engine, text
from support import PASSWORD, login

ROOT = Path(__file__).resolve().parents[1]
E2E_PASSWORD = "E2e-Test-Passw0rd!"
STRONG = dataclasses.replace(get_settings(), jwt_secret="k" * 48, llm_backend="ollama", embedding_backend="sentence_transformers",
                             owner_password="real-owner-pw-1", app_db_password="real-app-pw-1", worker_db_password="real-worker-pw-1")


# ---- the E2E stack refuses anything but its own isolated resources -----------------------------------------------------
def test_e2e_guard_accepts_only_local_isolated_non_production_setups():
    ports = {"api": 8210, "ui": 8220}
    e2e_guard.check("eaop_e2e", ports, environ={"EAOP_ENV": "development", "DB_HOST": "127.0.0.1"})
    e2e_guard.check("eaop_e2e_real", ports, environ={})
    for env in ({"EAOP_ENV": "production"}, {"EAOP_ENV": "prod"}, {"EAOP_ENV": " Production "}):
        with pytest.raises(e2e_guard.UnsafeEnvironment, match="EAOP_ENV=production"):
            e2e_guard.check("eaop_e2e", ports, environ=env)
    for db in ("eaop", "eaop_test", "eaop_bench", "postgres", "prod"):
        with pytest.raises(e2e_guard.UnsafeEnvironment, match="database"):
            e2e_guard.check(db, ports, environ={})
    with pytest.raises(e2e_guard.UnsafeEnvironment, match="non-local"):
        e2e_guard.check("eaop_e2e", ports, environ={"DB_HOST": "db.internal.example"})
    with pytest.raises(e2e_guard.UnsafeEnvironment, match="ports"):
        e2e_guard.check("eaop_e2e", {"api": 8000}, environ={})  # the normal dev API port is not an e2e port


def test_e2e_stack_script_exits_immediately_in_production_without_touching_anything():
    env = {"EAOP_ENV": "production", "PATH": __import__("os").environ["PATH"], "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "e2e_stack.py")], env=env, capture_output=True, text=True, timeout=30)
    assert done.returncode != 0 and "EAOP_ENV=production" in (done.stdout + done.stderr)
    assert "database ready" not in done.stdout  # it stopped before creating any database


def test_e2e_ports_and_databases_are_disjoint_from_development_and_tests():
    dev_ports = {8000, 8101, 8102, 8103, 8104, 8105, 5173}
    assert not (e2e_guard.ISOLATED_PORTS & dev_ports)
    assert not (e2e_guard.ALLOWED_DATABASES & {"eaop", "eaop_test", "eaop_bench", "eaop_smoke"})


# ---- test credentials cannot reach the normal development environment or production --------------------------------------
def test_e2e_accounts_do_not_exist_in_the_development_database():
    settings = get_settings()
    engine = create_engine(settings.url("owner"))
    try:
        with engine.connect() as conn:
            count = conn.execute(text("SELECT count(*) FROM users WHERE email LIKE '%-e2e.example.test' "
                                      "OR email = 'platform@e2e.example.test'")).scalar()
    except Exception:  # noqa: BLE001 - no dev database on this machine: nothing to be exposed
        pytest.skip("development database not available")
    finally:
        engine.dispose()
    assert count == 0


def test_the_e2e_password_is_confined_to_the_e2e_files():
    out = subprocess.run(["git", "grep", "-l", E2E_PASSWORD], cwd=ROOT, capture_output=True, text=True).stdout.split()
    allowed = {"scripts/e2e_stack.py", "frontend/e2e/helpers.ts", "frontend/e2e/admin-config-and-quality.spec.ts",
               "frontend/e2e/screenshots.spec.ts", "backend/app/core/production_guard.py", "tests/test_environment_guards.py",
               "docs/phase6/phase6-closure-gate.md", "scripts/secret_scan.py", "docs/security/test-credentials.md"}
    assert set(out) <= allowed, sorted(set(out) - allowed)


def test_production_refuses_test_only_configuration(monkeypatch):
    assert_production_safe(dataclasses.replace(STRONG, llm_backend="deterministic"))  # fine outside production
    monkeypatch.setenv("EAOP_ENV", "production")
    monkeypatch.delenv("EGRESS_DEV_MOCKS", raising=False)  # a developer .env may legitimately set it; production may not
    assert_production_safe(STRONG)
    bad = {
        "deterministic backends": dataclasses.replace(STRONG, llm_backend="deterministic"),
        "weak jwt": dataclasses.replace(STRONG, jwt_secret="test-secret-not-for-production-0123456789"),
        "short jwt": dataclasses.replace(STRONG, jwt_secret="short"),
        "placeholder db password": dataclasses.replace(STRONG, app_db_password="change-me-app"),
        "empty db password": dataclasses.replace(STRONG, worker_db_password=""),
    }
    for label, settings in bad.items():
        with pytest.raises(ProductionConfigError):
            assert_production_safe(settings)
        assert label
    monkeypatch.setenv("EGRESS_DEV_MOCKS", '{"*": ["http://127.0.0.1:8101"]}')
    with pytest.raises(ProductionConfigError, match="EGRESS_DEV_MOCKS"):
        assert_production_safe(STRONG)


def test_the_application_will_not_start_in_production_with_test_settings(monkeypatch, settings, app_db):
    monkeypatch.setenv("EAOP_ENV", "production")
    with pytest.raises(ProductionConfigError):
        create_app(settings, app_db)  # the test settings use deterministic backends and a test JWT secret


def test_known_test_passwords_are_rejected_in_production_even_for_a_valid_account(client, apex, monkeypatch):
    login(client, apex, "support_engineer")  # accepted outside production
    assert production_guard.TEST_ONLY_PASSWORDS >= {E2E_PASSWORD, PASSWORD}
    monkeypatch.setenv("EAOP_ENV", "production")
    res = client.post("/api/v1/auth/login", json={"email": apex.users["support_engineer"], "password": PASSWORD, "tenant": apex.slug})
    assert res.status_code == 401 and res.json()["error"]["code"] == "invalid_credentials"
    res = client.post("/api/v1/auth/login", json={"email": "anyone@example.test", "password": E2E_PASSWORD})
    assert res.status_code == 401


# ---- repository secret scan ----------------------------------------------------------------------------------------------
def test_repository_and_artifacts_contain_no_secrets():
    findings = secret_scan.scan(ROOT)
    assert findings == [], findings


def test_secret_scan_detects_planted_secrets_without_printing_them(tmp_path):
    env = tmp_path / ".env"
    env.write_text("JWT_SECRET=planted-super-secret-value-123\nAPP_DB_PASSWORD=change-me-placeholder\n")
    (tmp_path / "leak.log").write_text("token planted-super-secret-value-123 was logged")
    (tmp_path / "clean.txt").write_text("nothing here; change-me-placeholder is only a placeholder")
    (tmp_path / "key.pem").write_text("-----BEGIN " + "PRIVATE KEY-----\nabc\n")  # built at runtime: not itself a finding
    (tmp_path / "jwt.txt").write_text("ey" + "JhbGciOiJIUzI1NiJ9." + "ey" + "JzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop")
    (tmp_path / "code.py").write_text('API_KEY = "abcdefghijklmnopqrstuvwxyz"\nok = "change-me-please-now-ok"\n')
    findings = secret_scan.scan(tmp_path)
    hit = {(p, r) for p, r in findings}
    assert ("leak.log", "contains the value of JWT_SECRET from .env") in hit
    assert ("key.pem", "private key block") in hit and ("jwt.txt", "JWT-shaped token") in hit
    assert ("code.py", "literal credential assignment") in hit
    assert not any(p == "clean.txt" for p, _ in findings)
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "secret_scan.py"), "--root", str(tmp_path)], capture_output=True, text=True)
    assert done.returncode == 1 and "planted-super-secret-value-123" not in done.stdout + done.stderr
