"""Refuse to run with test-only configuration or test credentials when EAOP_ENV=production.

Fixed credentials exist only for the isolated end-to-end and unit-test environments. This module makes sure they, the
test-only AI backends and the mock-destination exceptions cannot be used in a production configuration by mistake.
"""
import os

from app.core.errors import Unauthorized

# Credentials that appear in test fixtures in this repository. They are public by construction.
TEST_ONLY_PASSWORDS = frozenset({"E2e-Test-Passw0rd!", "Test-Passw0rd!"})
_WEAK_SECRET_MARKERS = ("test", "change-me", "changeme", "secret-not-for-production", "bench-", "smoke-")


def is_production() -> bool:
    return os.environ.get("EAOP_ENV", "development").strip().lower() in ("production", "prod")


class ProductionConfigError(RuntimeError):
    pass


def assert_production_safe(settings) -> None:
    """Raise ProductionConfigError if the settings contain anything meant only for tests. No-op outside production."""
    if not is_production():
        return
    problems = []
    secret = settings.jwt_secret or ""
    if len(secret) < 32 or any(marker in secret.lower() for marker in _WEAK_SECRET_MARKERS):
        problems.append("JWT_SECRET is missing, shorter than 32 characters or looks like a test/placeholder value")
    if settings.llm_backend == "deterministic" or settings.embedding_backend == "deterministic":
        problems.append("the deterministic AI backends are test-only and cannot be used in production")
    if os.environ.get("EGRESS_DEV_MOCKS", "").strip() not in ("", "{}"):
        problems.append("EGRESS_DEV_MOCKS (development-only mock destinations) must not be set")
    passwords = {"owner": settings.owner_password, "app": settings.app_db_password,
                 "worker": settings.worker_db_password}
    for name, password in passwords.items():
        if not password or "change-me" in password.lower():
            problems.append(f"the {name} database password is empty or a placeholder")
    if problems:
        raise ProductionConfigError("refusing to start in production: " + "; ".join(problems))


def reject_test_credentials(password: str) -> None:
    """In production a known test password is never accepted, whatever the account's stored hash says."""
    if is_production() and password in TEST_ONLY_PASSWORDS:
        raise Unauthorized("Invalid credentials", code="invalid_credentials")
