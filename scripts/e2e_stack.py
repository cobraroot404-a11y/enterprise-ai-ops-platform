"""Start an isolated, seeded stack for the Playwright end-to-end tests (and stop it when terminated).

  python scripts/e2e_stack.py [--real-ai]

Everything is separate from the development environment: its own database (eaop_e2e, or eaop_e2e_real with --real-ai),
its own ports (API 8210, mocks 8211-8215, UI 8220) and its own tenants (apex-e2e, meridian-e2e), seeded through the
same code and public APIs a real onboarding uses. Test accounts use the fixed TEST-ONLY password below; this script
refuses to run if EAOP_ENV=production.

  deterministic (default): functional UI tests with the deterministic test-only AI backends
  --real-ai              : real Ollama + MiniLM (Ollama is started with scripts/ollama_ctl.py)
"""
import argparse
import atexit
import copy
import json
import os
import secrets
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

E2E_PASSWORD = "E2e-Test-Passw0rd!"  # test-only; the stack only ever runs against local mock services
PORTS = {"api": 8210, "ticketing": 8211, "inventory": 8212, "fleet": 8213, "crm": 8214, "servicedesk": 8215, "ui": 8220}
KEYS = {"ticketing": "e2e-ticketing-key", "servicedesk": "e2e-servicedesk-key"}
APEX_SLUG, MERIDIAN_SLUG = "apex-e2e", "meridian-e2e"
children: list[subprocess.Popen] = []


def stop_all(*_):
    for p in children:
        if p.poll() is None:
            p.terminate()
    for p in children:
        try:
            p.wait(timeout=8)
        except subprocess.TimeoutExpired:
            p.kill()


def wait_http(url: str, seconds: int = 90) -> None:
    end = time.time() + seconds
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    raise SystemExit(f"timed out waiting for {url}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--real-ai", action="store_true")
    args = ap.parse_args()
    import e2e_guard

    e2e_guard.check("eaop_e2e_real" if args.real_ai else "eaop_e2e", PORTS)  # exits before anything is created or started
    import dev  # noqa: E402  (loads .env for database credentials)

    dev.load_env()
    db_name = "eaop_e2e_real" if args.real_ai else "eaop_e2e"
    origins = {k: f"http://127.0.0.1:{PORTS[k]}" for k in ("ticketing", "inventory", "fleet", "crm", "servicedesk")}
    env = {**os.environ, "POSTGRES_DB": db_name, "EAOP_ENV": "development", "JWT_SECRET": secrets.token_urlsafe(32),
           "LLM_BACKEND": "ollama" if args.real_ai else "deterministic",
           "EMBEDDING_BACKEND": "sentence_transformers" if args.real_ai else "deterministic",
           "MOCK_TICKETING_API_KEY": KEYS["ticketing"], "MOCK_SERVICEDESK_API_KEY": KEYS["servicedesk"],
           "MERIDIAN_SERVICEDESK_KEY": KEYS["servicedesk"], "EVALUATION_DIR": str(ROOT / "evaluation"),
           "EGRESS_ALLOWLIST": "{}",
           "EGRESS_DEV_MOCKS": json.dumps({APEX_SLUG: [origins["ticketing"], origins["inventory"]],
                                           MERIDIAN_SLUG: [origins["servicedesk"], origins["fleet"], origins["crm"]]})}
    os.environ.update(env)

    # ---- database ---------------------------------------------------------------------------------------------------
    from alembic import command
    from alembic.config import Config
    from app.core.config import get_settings
    from app.core.security import hash_password
    from sqlalchemy import create_engine, text

    settings = get_settings(db_name)
    admin = create_engine(settings.url("owner").rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {db_name} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {db_name}"))
    admin.dispose()
    cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend" / "migrations"))
    cfg.attributes["url"] = settings.url("owner")
    command.upgrade(cfg, "head")
    print("database ready", flush=True)

    atexit.register(stop_all)
    signal.signal(signal.SIGTERM, lambda *_: (stop_all(), sys.exit(0)))
    if args.real_ai:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "ollama_ctl.py"), "start"], check=True)

    def spawn(cmd: list[str]) -> None:
        children.append(subprocess.Popen(cmd, cwd=ROOT, env=env))

    py = sys.executable
    for name, mod, port in (("ticketing", "ticketing_app", PORTS["ticketing"]), ("inventory", "inventory_app", PORTS["inventory"]),
                            ("fleet", "fleet_app", PORTS["fleet"]), ("crm", "crm_app", PORTS["crm"]),
                            ("servicedesk", "servicedesk_app", PORTS["servicedesk"])):
        spawn([py, "-m", "uvicorn", f"{mod}:app", "--app-dir", f"mock-services/{name}", "--port", str(port), "--log-level", "warning"])
    spawn([py, "-m", "uvicorn", "app.main:create_app", "--factory", "--app-dir", "backend", "--port", str(PORTS["api"]),
           "--log-level", "warning"])
    spawn([py, "workers/run_worker.py"])
    wait_http(f"http://127.0.0.1:{PORTS['api']}/api/v1/health", 120)

    # ---- tenants: Apex (direct, for the built-in path) and Meridian (public onboarding path) ------------------------------
    import httpx
    from onboard_tenant import onboard

    owner = create_engine(settings.url("owner"))
    with owner.begin() as conn:
        conn.execute(text("INSERT INTO users (email, full_name, password_hash, is_platform_admin) VALUES "
                          "('platform@e2e.example.test', 'Platform Admin', :p, true)"), {"p": hash_password(E2E_PASSWORD)})
        tid = conn.execute(text("INSERT INTO tenants (slug, name) VALUES (:s, :n) RETURNING id"),
                           {"s": APEX_SLUG, "n": "Apex Industrial Manufacturing (fictional, e2e)"}).scalar()
        for role, local in (("tenant_admin", "admin"), ("maintenance_supervisor", "supervisor"),
                            ("support_engineer", "engineer"), ("read_only_auditor", "auditor")):
            uid = conn.execute(text("INSERT INTO users (email, full_name, password_hash) VALUES (:e, :n, :p) RETURNING id"),
                               {"e": f"{local}@apex-e2e.example.test", "n": f"Apex {local}", "p": hash_password(E2E_PASSWORD)}).scalar()
            conn.execute(text("INSERT INTO memberships (tenant_id, user_id, role) VALUES (:t, :u, :r)"), {"t": tid, "u": uid, "r": role})
        conn.execute(text("INSERT INTO connectors (tenant_id, kind, name, base_url, secret_ref) VALUES "
                          "(:t, 'ticketing', 'apex-ticketing', :u, 'MOCK_TICKETING_API_KEY')"), {"t": tid, "u": origins["ticketing"]})
        conn.execute(text("INSERT INTO connectors (tenant_id, kind, name, base_url) VALUES (:t, 'inventory', 'apex-inventory', :u)"),
                     {"t": tid, "u": origins["inventory"]})
    api = httpx.Client(base_url=f"http://127.0.0.1:{PORTS['api']}", timeout=300)
    tok = api.post("/api/v1/auth/login", json={"email": "engineer@apex-e2e.example.test", "password": E2E_PASSWORD,
                                               "tenant": APEX_SLUG}).json()["access_token"]
    kinds = {"apex_cp200_pump_manual.pdf": "equipment_manual", "apex_inspection_report_2026q3.pdf": "inspection_report",
             "equipment_register.csv": "equipment_register", "incident_history.csv": "incident_history",
             "maintenance_log.csv": "maintenance_log"}
    for name, kind in kinds.items():
        r = api.post("/api/v1/documents", headers={"Authorization": f"Bearer {tok}"}, data={"kind": kind},
                     files={"file": (name, (ROOT / "sample-data" / "customer-a" / name).read_bytes())})
        r.raise_for_status()

    config = copy.deepcopy(json.loads((ROOT / "onboarding" / "meridian.json").read_text(encoding="utf-8")))
    config["tenant"] = {"slug": MERIDIAN_SLUG, "name": "Meridian Fleet Logistics (fictional, e2e)"}
    for m in config["members"]:
        m["email"] = m["email"].replace("@meridian.", "@meridian-e2e.")
    for c in config["connectors"]:
        c["base_url"] = {"ticketing": origins["servicedesk"], "fleet": origins["fleet"], "crm": origins["crm"]}[c["kind"]]
    onboard(config, api, password=E2E_PASSWORD, platform=("platform@e2e.example.test", E2E_PASSWORD), log=lambda *_: None)
    print("tenants ready", flush=True)

    # ---- UI (started last so Playwright's readiness probe means the whole stack is ready) -----------------------------------
    vite = ROOT / "frontend" / "node_modules" / "vite" / "bin" / "vite.js"
    ui_env = {**env, "EAOP_API_URL": f"http://127.0.0.1:{PORTS['api']}"}
    children.append(subprocess.Popen(["node", str(vite), "preview", "--host", "127.0.0.1", "--port", str(PORTS["ui"]), "--strictPort"],
                                     cwd=ROOT / "frontend", env=ui_env))
    wait_http(f"http://127.0.0.1:{PORTS['ui']}/", 60)
    print("READY", flush=True)
    while all(p.poll() is None for p in children):
        time.sleep(1)
    print("a stack process exited; shutting down", flush=True)


if __name__ == "__main__":
    main()
