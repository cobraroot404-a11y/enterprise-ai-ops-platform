"""Shared fixtures. Tests run against a real PostgreSQL (pgvector) test database with the deterministic
test-only AI backends. Nothing here measures real LLM or embedding quality."""
import dataclasses
import os
import threading
import time
import uuid
from pathlib import Path

import pytest
import ticketing_app
import uvicorn
from alembic import command
from alembic.config import Config
from app.core.config import get_settings
from app.core.security import hash_password
from app.database.session import Database
from app.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "sample-data" / "customer-a"
PASSWORD = "Test-Passw0rd!"
TEST_DB = "eaop_test"
TICKETING_KEY = "test-ticketing-key"
SERVICEDESK_KEY = "test-servicedesk-key"


class ServerThread:
    def __init__(self, app):
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self) -> str:
        self.thread.start()
        deadline = time.time() + 10
        while not self.server.started and time.time() < deadline:
            time.sleep(0.05)
        port = self.server.servers[0].sockets[0].getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        from app.connectors import egress  # test mock servers are the only development-only destinations
        egress.get_policy().add_dev_mock("*", url)
        return url

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=5)


def pytest_collection_modifyitems(config, items):
    if os.environ.get("RUN_REAL_AI") == "1":
        return
    skip = pytest.mark.skip(reason="real AI test: set RUN_REAL_AI=1 (needs Ollama + MiniLM locally)")
    for item in items:
        if "real_ai" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def settings():
    base = get_settings(db_name=TEST_DB)
    # Functional tests ALWAYS use the deterministic test-only backends, whatever .env says.
    return dataclasses.replace(base, jwt_secret="test-secret-not-for-production-0123456789",
                               llm_backend="deterministic", embedding_backend="deterministic")


@pytest.fixture(scope="session")
def owner_engine(settings):
    admin = create_engine(settings.url("owner").rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {TEST_DB}"))
    admin.dispose()
    cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend" / "migrations"))
    cfg.attributes["url"] = settings.url("owner")
    command.upgrade(cfg, "head")
    engine = create_engine(settings.url("owner"), pool_pre_ping=True)  # survives DB restarts in fault injection
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def app_db(settings, owner_engine):
    db = Database(settings, role="app")
    yield db
    db.dispose()


@pytest.fixture(scope="session")
def worker_db(settings, owner_engine):
    db = Database(settings, role="worker")
    yield db
    db.dispose()


@pytest.fixture(scope="session")
def ticketing_server():
    app = ticketing_app.create_app(api_key=TICKETING_KEY)
    server = ServerThread(app)
    url = server.start()
    yield type("Ticketing", (), {"url": url, "state": app.state.mock, "app": app})
    server.stop()


@pytest.fixture(scope="session")
def inventory_server():
    import inventory_app
    server = ServerThread(inventory_app.create_app(api_key=""))
    url = server.start()
    yield type("Inventory", (), {"url": url})
    server.stop()


@pytest.fixture(scope="session")
def _servicedesk_session():
    import servicedesk_app
    app = servicedesk_app.create_app(api_key=SERVICEDESK_KEY)
    server = ServerThread(app)
    url = server.start()
    yield type("ServiceDesk", (), {"url": url, "state": app.state.mock, "app": app})
    server.stop()


@pytest.fixture()
def servicedesk_server(_servicedesk_session):
    """The service-desk mock with clean state for every test (the server itself is shared for speed)."""
    state = _servicedesk_session.state
    with state.lock:
        state.tickets.clear()
        state.by_key.clear()
        state.failures.clear()
        state.requests = 0
    return _servicedesk_session


RECORDS_KEY = "records-test-key"


@pytest.fixture(scope="session")
def records_server():
    import records_app
    app = records_app.create_app(api_key=RECORDS_KEY)
    server = ServerThread(app)
    url = server.start()
    yield type("Records", (), {"url": url, "state": app.state.mock, "app": app})
    server.stop()


@pytest.fixture(scope="session")
def fleet_server():
    import fleet_app
    app = fleet_app.create_app(api_key="")
    server = ServerThread(app)
    url = server.start()
    yield type("Fleet", (), {"url": url, "app": app})
    server.stop()


@pytest.fixture(scope="session")
def crm_server():
    import crm_app
    app = crm_app.create_app(api_key="")
    server = ServerThread(app)
    url = server.start()
    yield type("Crm", (), {"url": url, "app": app})
    server.stop()


@pytest.fixture(scope="session", autouse=True)
def _egress_policy():
    """Tests run with the real policy code but authorize only the local mock servers (development-only mode)."""
    from app.connectors import egress
    policy = egress.EgressPolicy(production=False)
    egress.set_policy(policy)
    yield policy
    egress.set_policy(None)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("MOCK_TICKETING_API_KEY", TICKETING_KEY)
    monkeypatch.setenv("MERIDIAN_SERVICEDESK_KEY", SERVICEDESK_KEY)


@pytest.fixture()
def ticketing(ticketing_server, owner_engine):
    # The worker drains a global queue, so retire events left behind by earlier tests before each test.
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE outbox_events SET status = 'done' WHERE status IN ('pending', 'processing')"))
        # the same for the shared ingestion-job queue: jobs left active by earlier tests (outage simulations) must not be drained by unrelated tests
        conn.execute(text("UPDATE ingestion_jobs SET status = 'CANCELLED', claim_token = NULL, locked_until = NULL, payload = NULL, completed_at = now() "
                          "WHERE status IN ('QUEUED', 'PROCESSING', 'RETRY_PENDING')"))
    state = ticketing_server.state
    with state.lock:
        state.tickets.clear()
        state.by_key.clear()
        state.failures.clear()
        state.requests = 0
    return ticketing_server


@pytest.fixture()
def client(settings, app_db):
    return TestClient(create_app(settings, app_db))


@dataclasses.dataclass
class TenantEnv:
    id: str
    slug: str
    users: dict  # role -> email


def make_tenant(owner_engine, prefix: str, ticketing_url=None, inventory_url=None) -> TenantEnv:
    slug = f"{prefix}-{uuid.uuid4().hex[:8]}"
    users = {}
    with owner_engine.begin() as conn:
        tenant_id = conn.execute(text("INSERT INTO tenants (slug, name) VALUES (:s, :n) RETURNING id"),
                                 {"s": slug, "n": slug.upper()}).scalar()
        pw = hash_password(PASSWORD)
        for role in ("tenant_admin", "maintenance_supervisor", "support_engineer", "read_only_auditor"):
            email = f"{role}.{slug}@example.test"
            uid = conn.execute(text("INSERT INTO users (email, full_name, password_hash) "
                                    "VALUES (:e, :n, :p) RETURNING id"),
                               {"e": email, "n": role, "p": pw}).scalar()
            conn.execute(text("INSERT INTO memberships (tenant_id, user_id, role) VALUES (:t, :u, :r)"),
                         {"t": tenant_id, "u": uid, "r": role})
            users[role] = email
        if ticketing_url:
            conn.execute(text("INSERT INTO connectors (tenant_id, kind, name, base_url, secret_ref) "
                              "VALUES (:t, 'ticketing', 'mock-ticketing', :u, 'MOCK_TICKETING_API_KEY')"),
                         {"t": tenant_id, "u": ticketing_url})
        if inventory_url:
            conn.execute(text("INSERT INTO connectors (tenant_id, kind, name, base_url) "
                              "VALUES (:t, 'inventory', 'mock-inventory', :u)"),
                         {"t": tenant_id, "u": inventory_url})
    return TenantEnv(str(tenant_id), slug, users)


def onboard_meridian(client: TestClient, owner_engine, servicedesk, fleet, crm, slug_prefix="meridian") -> TenantEnv:
    """Onboard the fictional Meridian customer through the public API only (the supported onboarding path)."""
    import copy
    import json
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    from onboard_tenant import onboard

    config = copy.deepcopy(json.loads((ROOT / "onboarding" / "meridian.json").read_text(encoding="utf-8")))
    slug = f"{slug_prefix}-{uuid.uuid4().hex[:8]}"
    config["tenant"]["slug"] = slug
    for member in config["members"]:
        member["email"] = member["email"].replace("@", f".{slug}@")
    urls = {"ticketing": servicedesk.url, "fleet": fleet.url, "crm": crm.url}
    for connector in config["connectors"]:
        connector["base_url"] = urls[connector["kind"]]
    platform_email = "platform.onboarding@example.test"
    with owner_engine.begin() as conn:
        conn.execute(text("INSERT INTO users (email, full_name, password_hash, is_platform_admin) "
                          "VALUES (:e, 'Platform', :p, true) ON CONFLICT (email) DO NOTHING"),
                     {"e": platform_email, "p": hash_password(PASSWORD)})
    summary = onboard(config, client, password=PASSWORD, platform=(platform_email, PASSWORD), log=lambda *_: None)
    users = {m["role"]: m["email"] for m in config["members"]}
    return TenantEnv(summary["tenant_id"], slug, users)


def login(client: TestClient, tenant: TenantEnv, role: str) -> dict:
    resp = client.post("/api/v1/auth/login", json={"email": tenant.users[role], "password": PASSWORD,
                                                   "tenant": tenant.slug})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


SAMPLE_KINDS = {
    "apex_cp200_pump_manual.pdf": "equipment_manual",
    "apex_inspection_report_2026q3.pdf": "inspection_report",
    "equipment_register.csv": "equipment_register",
    "incident_history.csv": "incident_history",
    "maintenance_log.csv": "maintenance_log",
}


def ingest_samples(client: TestClient, headers: dict) -> dict:
    results = {}
    for name, kind in SAMPLE_KINDS.items():
        resp = client.post("/api/v1/documents", headers=headers, data={"kind": kind},
                           files={"file": (name, (SAMPLES / name).read_bytes())})
        assert resp.status_code == 201, resp.text
        results[name] = resp.json()
    return results


@pytest.fixture()
def apex(owner_engine, ticketing, inventory_server) -> TenantEnv:
    return make_tenant(owner_engine, "apex", ticketing.url, inventory_server.url)


@pytest.fixture()
def apex_loaded(client, apex):
    headers = login(client, apex, "support_engineer")
    ingest_samples(client, headers)
    return apex


REPORT = ("Pump P-101 shows abnormal vibration at the drive end, measured at 8.4 mm/s, "
          "with a grinding noise since this morning.")
