"""Seed the fictional Apex Industrial demo tenant, users, connectors and sample documents (idempotent).

Run: python scripts/seed_apex.py
All demo accounts share the password in SEED_PASSWORD (from .env). Demo data only; never production.
The development-only UI fixture tenant is seeded separately by scripts/seed_uitest.py.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.ai.embeddings import get_embedder  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.database.session import Database  # noqa: E402
from app.ingestion.service import ingest  # noqa: E402
from app.models import Connector, Membership, Tenant, User  # noqa: E402

SAMPLES = ROOT / "sample-data" / "customer-a"
KINDS = {
    "apex_cp200_pump_manual.pdf": "equipment_manual",
    "apex_inspection_report_2026q3.pdf": "inspection_report",
    "equipment_register.csv": "equipment_register",
    "incident_history.csv": "incident_history",
    "maintenance_log.csv": "maintenance_log",
}
ROLES = [
    ("tenant_admin", "admin", "Avery Admin"),
    ("maintenance_supervisor", "supervisor", "Sam Supervisor"),
    ("support_engineer", "engineer", "Erin Engineer"),
    ("read_only_auditor", "auditor", "Alex Auditor"),
]


def refuse_in_production() -> None:
    if os.environ.get("EAOP_ENV", "development").lower() in ("production", "prod"):
        sys.exit("Refusing to seed demo/test data when EAOP_ENV=production.")


def seed_tenant(slug: str, name: str, domain: str, password: str, *, platform_admin: bool = False) -> None:
    settings = get_settings()
    owner = Database(settings, role="owner", pool_size=1, max_overflow=0)
    with owner.session() as s:
        tenant = s.scalar(select(Tenant).where(Tenant.slug == slug))
        if tenant is None:
            tenant = Tenant(slug=slug, name=name)
            s.add(tenant)
            s.flush()
        elif tenant.name != name:
            tenant.name = name
        if platform_admin and s.scalar(select(User).where(User.email == "platform-admin@example.test")) is None:
            s.add(User(email="platform-admin@example.test", full_name="Platform Admin",
                       password_hash=hash_password(password), is_platform_admin=True))
        user_ids = {}
        for role, local, full_name in ROLES:
            email = f"{local}@{domain}"
            user = s.scalar(select(User).where(User.email == email))
            if user is None:
                user = User(email=email, full_name=full_name, password_hash=hash_password(password))
                s.add(user)
                s.flush()
            user_ids[role] = user.id
            if s.scalar(select(Membership).where(Membership.user_id == user.id,
                                                 Membership.tenant_id == tenant.id)) is None:
                s.add(Membership(tenant_id=tenant.id, user_id=user.id, role=role))
        for kind, cname, url, secret in (
            ("ticketing", f"{slug}-ticketing", "http://127.0.0.1:8101", "MOCK_TICKETING_API_KEY"),
            ("inventory", f"{slug}-inventory", "http://127.0.0.1:8102", None),
        ):
            if s.scalar(select(Connector).where(Connector.tenant_id == tenant.id, Connector.kind == kind)) is None:
                s.add(Connector(tenant_id=tenant.id, kind=kind, name=cname, base_url=url, secret_ref=secret))
        s.commit()
        tenant_id = tenant.id
    owner.dispose()

    app_db = Database(settings, role="app", pool_size=1, max_overflow=0)
    embedder = get_embedder(settings.embedding_backend)
    with app_db.session(tenant_id) as s:
        for filename, kind in KINDS.items():
            result = ingest(s, tenant_id=tenant_id, user_id=user_ids["support_engineer"], filename=filename,
                            data=(SAMPLES / filename).read_bytes(), kind=kind, embedder=embedder)
            print(f"{filename}: {result.status} ({result.chunk_count} chunks)")
        s.commit()
    app_db.dispose()
    print(f"Seeded tenant '{slug}'. Users: admin/supervisor/engineer/auditor@{domain}")


def main() -> None:
    refuse_in_production()
    password = os.environ.get("SEED_PASSWORD")
    if not password or password.startswith("change-me"):
        sys.exit("Set SEED_PASSWORD in .env to a non-default value before seeding.")
    seed_tenant("apex-industrial", "Apex Industrial Manufacturing (fictional)", "apex.example.test", password,
                platform_admin=True)


if __name__ == "__main__":
    main()
