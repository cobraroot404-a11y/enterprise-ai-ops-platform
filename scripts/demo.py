#!/usr/bin/env python
"""One-command local demonstration launcher (Batch 6). Wraps the existing tools (scripts/dev.py process table, scripts/migrate.py, scripts/seed_apex.py,
scripts/onboard_tenant.py, scripts/ollama_ctl.py, the Vite dev server and the Playwright setup); it adds no second infrastructure system.

    python scripts/demo.py preflight [--ai real]     check prerequisites; changes nothing
    python scripts/demo.py up [--ai real]            create a DISPOSABLE database, migrate to head, seed Apex, start the services, onboard Meridian, then return
                                                     (services keep running, detached; stop them with `down`)
    python scripts/demo.py smoke [--no-browser]      the same startup, then Apex and Meridian workflows (API), a bounded browser smoke, a report, and teardown
    python scripts/demo.py status                    show what the last `up` created and whether it is ready
    python scripts/demo.py down                      stop ONLY the processes this launcher recorded and drop ONLY the database it created
    python scripts/demo.py backup [--database NAME]  export a disposable demo database to backups/demo/ (pg_dump from the project's PostgreSQL container)
    python scripts/demo.py restore-check FILE        restore a backup into a NEW isolated database, verify it, drop it

Ownership rules: every process and the database are recorded in .demo/state.json when they are created. `down` re-checks a process's creation time before it
terminates it (a recycled PID is left alone), refuses to drop any database whose name does not start with `eaop_demo_` or that is the configured shared one, and
never touches a port holder it did not start. Secrets are read through the existing .env loader (scripts/dev.py), are never printed, and are redacted from reports."""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))

import dev  # noqa: E402  (the existing task table and .env loader)

STATE_DIR = ROOT / ".demo"
STATE_FILE = STATE_DIR / "state.json"
REPORT_ROOT = ROOT / "evaluation" / "demo-runs"
DB_PREFIX = "eaop_demo_"
PORTS = {"api": 8000, "ticketing": 8101, "inventory": 8102, "fleet": 8103, "crm": 8104, "servicedesk": 8105, "records": 8106, "ui": 5173}
REQUIRED_SECRETS = ["POSTGRES_PASSWORD", "APP_DB_PASSWORD", "WORKER_DB_PASSWORD", "JWT_SECRET", "SEED_PASSWORD", "MOCK_TICKETING_API_KEY", "MOCK_SERVICEDESK_API_KEY",
                    "MERIDIAN_SERVICEDESK_KEY"]
JSON_SETTINGS = ["EGRESS_ALLOWLIST", "EGRESS_DEV_MOCKS"]
TENANTS = {"apex-industrial": ("8101", "8102"), "meridian-fleet": ("8103", "8104", "8105")}
NT = os.name == "nt"
EST = timezone(timedelta(hours=-5))


class DemoError(Exception):
    """A failure with an actionable explanation. `step` names where it happened."""

    def __init__(self, step: str, message: str, hint: str = ""):
        super().__init__(f"[{step}] {message}" + (f"\n    -> {hint}" if hint else ""))
        self.step, self.message, self.hint = step, message, hint


def say(msg: str) -> None:
    print(f"[demo {datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ------------------------------------------------------------------------------------------------------------------------------------------ environment
def load_env_file(path: Path) -> dict:
    """Parse .env exactly like scripts/dev.py does (raw text after the first '='), so JSON values keep their quotes. Never goes through a shell."""
    if not path.exists():
        raise DemoError("environment", f"{path.name} was not found at {path}", "copy .env.example to .env and replace every placeholder value (see docs/operations/local-runbook.md)")
    values = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.strip() and not raw.startswith("#") and "=" in raw:
            key, _, value = raw.partition("=")
            values[key.strip()] = value.strip()
    return values


def validate_env(env: dict, ports: dict | None = None) -> list[str]:
    """Return problems (names only, never values) in the structured and required settings."""
    ports = ports or PORTS
    problems = []
    for name in REQUIRED_SECRETS:
        if not env.get(name, "").strip():
            problems.append(f"{name} is missing or empty")
    if env.get("MOCK_SERVICEDESK_API_KEY") and env.get("MERIDIAN_SERVICEDESK_KEY") and env["MOCK_SERVICEDESK_API_KEY"] != env["MERIDIAN_SERVICEDESK_KEY"]:
        problems.append("MERIDIAN_SERVICEDESK_KEY must equal MOCK_SERVICEDESK_API_KEY")
    if env.get("EAOP_ENV", "development").lower() in ("production", "prod"):
        problems.append("EAOP_ENV is production: the demo refuses to create demo data in a production configuration")
    parsed = {}
    for name in JSON_SETTINGS:
        raw = env.get(name, "").strip()
        if not raw:
            problems.append(f"{name} is not set (expected a JSON object)")
            continue
        try:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("not an object")
            parsed[name] = value
        except ValueError:
            problems.append(f"{name} is not a valid JSON object (usually quotes were stripped by a shell: edit .env directly and keep the double quotes; the launcher reads .env itself)")
    mocks = parsed.get("EGRESS_DEV_MOCKS")
    if mocks is not None:
        for slug, offsets in TENANTS.items():
            allowed = mocks.get(slug, [])
            for off in offsets:
                origin = f"http://127.0.0.1:{off}"
                if origin not in allowed:
                    problems.append(f"EGRESS_DEV_MOCKS does not allow {origin} for tenant {slug} (connector creation would be rejected)")
    return problems


def child_env(env_file: dict, db_name: str, ai: str, ports: dict) -> dict:
    """Environment for every process the launcher starts: the .env values, the disposable database, and the chosen AI backend."""
    env = {**os.environ, **env_file}
    env["POSTGRES_DB"] = db_name
    env["EAOP_API_URL"] = f"http://127.0.0.1:{ports['api']}"
    if ai == "real":
        env["LLM_BACKEND"], env["EMBEDDING_BACKEND"] = "ollama", "sentence_transformers"
    else:
        env["LLM_BACKEND"], env["EMBEDDING_BACKEND"] = "deterministic", "deterministic"
    env["PYTHONUNBUFFERED"] = "1"
    return env


# ------------------------------------------------------------------------------------------------------------------------------------------ preflight
def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def check(name: str, ok: bool, detail: str, hint: str = "") -> dict:
    return {"check": name, "ok": ok, "detail": detail, "hint": hint}


def ollama_model_present(model: str) -> bool:
    import ollama_ctl
    return any(m.get("name") == model for m in ollama_ctl.get("/api/tags").get("models", []))


def preflight(env_file: dict, *, ai: str = "deterministic", ports: dict | None = None, root: Path = ROOT, need_ui: bool = True, need_browser: bool = False) -> list[dict]:
    """Run every prerequisite check and return the results; raise nothing (callers decide). Changes no state."""
    ports = ports or PORTS
    results = []
    results.append(check("python environment", all(__import__("importlib.util").util.find_spec(m) for m in ("fastapi", "uvicorn", "sqlalchemy", "alembic", "psycopg")),
                         f"{sys.executable}", "run with the project's virtual environment: .venv\\Scripts\\python scripts\\demo.py ..."))
    problems = validate_env(env_file, ports)
    results.append(check("environment configuration", not problems, "; ".join(problems) if problems else "required settings present, JSON settings valid, mock origins authorised", "fix .env (names only are shown here; values are never printed)"))
    node = shutil.which("node")
    results.append(check("node", bool(node), node or "node not found", "install Node 20+ (not done automatically)"))
    results.append(check("frontend dependencies", (root / "frontend" / "node_modules" / "vite").exists() or not need_ui, "frontend/node_modules/vite present" if (root / "frontend" / "node_modules" / "vite").exists() else "missing",
                         "run `npm install` in frontend/ (not done automatically)"))
    if need_browser:
        pw = (root / "frontend" / "node_modules" / "@playwright" / "test").exists()
        results.append(check("playwright", pw, "@playwright/test present" if pw else "missing", "run `npm install` in frontend/ (the browser is the installed Microsoft Edge; nothing is downloaded)"))
    free = shutil.disk_usage(root).free / 1e9
    results.append(check("disk space", free >= 2.0, f"{free:.0f} GB free", "free at least 2 GB"))
    busy = [f"{name}:{port}" for name, port in ports.items() if (name != "ui" or need_ui) and port_in_use(port)]
    results.append(check("ports free", not busy, "all required ports free" if not busy else "in use: " + ", ".join(busy),
                         "another program (possibly your own dev stack) holds these ports; the launcher never stops processes it did not start. Stop that program yourself or run `python scripts/demo.py down` if it is a previous demo"))
    db_ok, db_detail = False, ""
    if not any(p.startswith("POSTGRES_PASSWORD") for p in validate_env(env_file, ports)):
        try:
            with _admin(env_file) as conn:
                conn.exec_driver_sql("SELECT 1")
                has_vector = conn.exec_driver_sql("SELECT count(*) FROM pg_available_extensions WHERE name = 'vector'").scalar()
            db_ok, db_detail = bool(has_vector), "PostgreSQL reachable, pgvector available" if has_vector else "PostgreSQL reachable but pgvector is not available"
        except Exception as exc:  # noqa: BLE001
            db_detail = f"cannot connect to PostgreSQL ({type(exc).__name__})"
    else:
        db_detail = "skipped: POSTGRES_PASSWORD missing"
    host = env_file.get("DB_HOST", "127.0.0.1")
    if host not in ("127.0.0.1", "localhost", "::1"):
        db_ok, db_detail = False, f"DB_HOST is {host}: the demo only creates databases on a local server"
    results.append(check("postgresql", db_ok, db_detail, "start it with `python scripts/dev.py up` (Docker Desktop must be running)"))
    if ai == "real":
        import ollama_ctl
        exe = ollama_ctl.find_exe()
        results.append(check("ollama installed", bool(exe), exe or "not installed", "see docs/operations/real-ai-setup-windows.md (nothing is installed automatically)"))
        model = env_file.get("OLLAMA_MODEL") or "qwen2.5:1.5b"
        present = False
        if exe and ollama_ctl.is_up():
            try:
                present = ollama_model_present(model)
            except Exception:  # noqa: BLE001
                present = False
            detail = f"model {model} {'present' if present else 'NOT present'}"
        elif exe:
            detail = "Ollama is not running; it is started (and later stopped) by the launcher only if you ask for a real-AI run; the model check then happens at start"
            present = True
        else:
            detail = "no Ollama"
        results.append(check("ollama model", present, detail, f"run `ollama pull {model}` yourself (models are never downloaded automatically)"))
        cache = root / "data" / "models"
        results.append(check("embedding model cache", cache.exists() and any(cache.iterdir()), str(cache.relative_to(root)) if cache.exists() else "missing",
                             "see docs/operations/real-ai-setup-windows.md"))
    return results


def _admin(env_file: dict):
    from sqlalchemy import create_engine
    from app.core.config import get_settings
    saved = {k: os.environ.get(k) for k in env_file}
    os.environ.update(env_file)
    try:
        url = get_settings(db_name="postgres").url("owner")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    engine = create_engine(url, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 5})
    return engine.connect()


# ------------------------------------------------------------------------------------------------------------------------------------------ database
def safe_db_name(name: str, shared: str) -> None:
    if not name.startswith(DB_PREFIX) or name == shared or not name.replace("_", "").isalnum():
        raise DemoError("database", f"refusing to use database '{name}'", f"the demo only creates or drops databases named {DB_PREFIX}<id>, never the configured shared one")


def create_database(env_file: dict, name: str) -> None:
    safe_db_name(name, env_file.get("POSTGRES_DB", "eaop"))
    with _admin(env_file) as conn:
        if conn.exec_driver_sql("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).first():
            raise DemoError("database", f"database {name} already exists", "this run did not create it, so it will not be used or dropped; try again")
        conn.exec_driver_sql(f'CREATE DATABASE "{name}"')


def drop_database(env_file: dict, name: str) -> bool:
    safe_db_name(name, env_file.get("POSTGRES_DB", "eaop"))
    with _admin(env_file) as conn:
        conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        return conn.exec_driver_sql("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).first() is None


def database_revision(env_file: dict, name: str) -> str | None:
    from sqlalchemy import create_engine
    from app.core.config import get_settings
    saved = {k: os.environ.get(k) for k in env_file}
    os.environ.update(env_file)
    try:
        url = get_settings(db_name=name).url("owner")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    with create_engine(url).connect() as conn:
        return conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar()


def head_revision() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend" / "migrations"))
    return ScriptDirectory.from_config(cfg).get_current_head()


# ------------------------------------------------------------------------------------------------------------------------------------------ processes
def process_info(pid: int) -> dict | None:
    """Creation time and command line of a process, or None if it is gone. Used to prove a recorded PID is still the process we started."""
    if not NT:
        try:
            os.kill(pid, 0)
        except OSError:
            return None
        return {"created": "posix", "cmd": ""}
    script = f"$p = Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}'; if ($p) {{ $p.CreationDate.ToUniversalTime().ToString('o') + '|' + $p.CommandLine }}"
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True, timeout=30).stdout.strip()
    if not out:
        return None
    created, _, cmd = out.partition("|")
    return {"created": created, "cmd": cmd}


def kill_tree(pid: int) -> None:
    if NT:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, timeout=60)
    else:
        os.kill(pid, 15)


def spawn(name: str, cmd: list[str], cwd: Path, env: dict, log: Path) -> dict:
    log.parent.mkdir(parents=True, exist_ok=True)
    flags = (0x00000008 | 0x00000200 | 0x08000000) if NT else 0  # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW
    handle = open(log, "ab")  # noqa: SIM115 - owned by the child for its lifetime
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=handle, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=flags, close_fds=True)
    info = process_info(proc.pid) or {"created": "", "cmd": ""}
    return {"name": name, "pid": proc.pid, "created": info["created"], "log": str(log), "marker": Path(cmd[-1]).name if cmd else name}


def stop_record(rec: dict) -> str:
    """Terminate a recorded process only if it is still the very process we started."""
    info = process_info(rec["pid"])
    if info is None:
        return "already stopped"
    if rec.get("created") and info["created"] != rec["created"]:
        return "pid was reused by another program: left untouched"
    kill_tree(rec["pid"])
    for _ in range(20):
        if not NT:
            # A terminated child still answers kill(pid, 0) until it is reaped.
            try:
                if os.waitpid(rec["pid"], os.WNOHANG)[0]:
                    return "stopped"
            except ChildProcessError:
                pass  # A separate launcher can stop this process but cannot reap it.
        if process_info(rec["pid"]) is None:
            return "stopped"
        time.sleep(0.25)
    return "still running after kill (check manually)"


# ------------------------------------------------------------------------------------------------------------------------------------------ readiness
def http_status(url: str, timeout: float = 2.0) -> int | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 - local URL
            return r.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (OSError, ValueError):
        return None


def http_detail(url: str, timeout: float = 5.0) -> str:
    """One-line outcome of a single request, for diagnostics: the status, or how it failed (refused, timed out, reset)."""
    started = time.time()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 - local URL
            return f"HTTP {r.status} in {time.time() - started:.1f}s"
    except urllib.error.HTTPError as exc:
        return f"HTTP {exc.code} in {time.time() - started:.1f}s"
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__} after {time.time() - started:.1f}s"


def log_tail(path: Path, lines: int = 8, env_file: dict | None = None) -> str:
    try:
        text = "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return "(no log)"
    for name, value in (env_file or {}).items():
        if any(k in name for k in ("PASSWORD", "SECRET", "KEY", "TOKEN")) and len(value) >= 6:
            text = text.replace(value, "[redacted]")
    return text[-1200:]


def wait_until(label: str, probe, seconds: float, proc_alive=None) -> str:
    """Poll `probe()` (returns a detail string when ready, else a falsy value) for a bounded time."""
    deadline, last = time.time() + seconds, ""
    while time.time() < deadline:
        if proc_alive is not None and not proc_alive():
            raise DemoError("startup", f"{label}: the process exited before it became ready", "see its log under .demo/<run id>/logs/")
        got = probe()
        if got:
            return got
        time.sleep(0.4)
    raise DemoError("startup", f"{label} was not ready after {seconds:.0f}s {last}", "see its log under .demo/<run id>/logs/")


# ------------------------------------------------------------------------------------------------------------------------------------------ state
def load_state() -> dict | None:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return None


def save_state(state: dict) -> None:
    """Atomic update (write a temp file, then replace), so a reader never sees a half-written state file."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_name(f"state.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8", newline="\n")
    os.replace(tmp, STATE_FILE)


def claim_state(state: dict) -> None:
    """Exclusive creation of the state file: of two concurrent launchers exactly one wins, the other is refused before it creates anything."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(STATE_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise DemoError("state", "another demo run has claimed the state file at the same moment", "wait for it to finish, or run `python scripts/demo.py down`") from None
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(state, handle, indent=1)


def launcher_alive(state: dict) -> bool:
    """True while the launcher process that wrote this state (during `up` or `smoke`) is still the same running process."""
    pid, created = state.get("launcher_pid"), state.get("launcher_created")
    if not pid or state.get("phase") == "running":
        return False
    info = process_info(pid)
    return info is not None and (not created or info["created"] == created)


def describe_state(state: dict) -> str:
    if launcher_alive(state):
        return f"run {state.get('run_id')} is in progress (launcher pid {state['launcher_pid']})"
    return f"run {state.get('run_id')} was recorded earlier (phase {state.get('phase', 'unknown')}; its launcher is no longer running)"


class Demo:
    def __init__(self, *, ai: str = "deterministic", ports: dict | None = None, root: Path = ROOT, env_file: dict | None = None, services=None, steps=None, ready_seconds: float = 90.0):
        self.ai, self.ports, self.root = ai, ports or dict(PORTS), root
        self.env_file = env_file if env_file is not None else load_env_file(root / ".env")
        self.run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        self.db_name = DB_PREFIX + self.run_id.replace("-", "_")
        self.run_dir = STATE_DIR / self.run_id
        self.state = {"run_id": self.run_id, "db_name": self.db_name, "db_created": False, "processes": [], "ollama_started": False, "ports": self.ports, "ai": ai, "phase": "starting", "launcher_pid": os.getpid(), "launcher_created": (process_info(os.getpid()) or {}).get("created", ""), "started_at": datetime.now(EST).isoformat(timespec="seconds")}
        self.services_override, self.steps, self.ready_seconds = services, steps or {}, ready_seconds
        self.webhook_secrets: dict | None = None
        self.records_key: str | None = None  # set by `smoke --rest`: the records mock starts too and the connectors use this run-only key
        self.fault_file: Path | None = None  # set by `smoke --ingestion`: API and worker then start through scripts/fault_boot.py
        self.timeline: list[dict] = []
        self.env = child_env(self.env_file, self.db_name, ai, self.ports)

    # ---- helpers
    def step(self, name: str, fn):
        t0 = time.time()
        say(name)
        try:
            detail = fn()
            self.timeline.append({"step": name, "ok": True, "seconds": round(time.time() - t0, 1), "detail": detail if isinstance(detail, str) else ""})
            return detail
        except BaseException as exc:
            self.timeline.append({"step": name, "ok": False, "seconds": round(time.time() - t0, 1), "detail": (str(exc).splitlines() or [type(exc).__name__])[0][:300]})
            raise

    def python_step(self, args: list[str], label: str, timeout: float = 300) -> str:
        log = self.run_dir / "logs" / f"{label}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "ab") as handle:
            res = subprocess.run([sys.executable, *args], cwd=self.root, env=self.env, stdout=handle, stderr=subprocess.STDOUT, timeout=timeout)
        if res.returncode:
            raise DemoError(label, f"exited with code {res.returncode}", f"see {log.relative_to(self.root)}")
        return f"ok (log {log.relative_to(self.root)})"

    def services(self) -> list[dict]:
        if self.services_override is not None:
            return self.services_override
        py = sys.executable
        specs = []
        for name in ("ticketing", "inventory", "fleet", "crm", "servicedesk") + (("records",) if self.records_key else ()):
            cmd = [py if part == dev.PY else part for part in dev.PROCESSES[name]]
            cmd[cmd.index("--port") + 1] = str(self.ports[name])
            specs.append({"name": name, "cmd": cmd, "cwd": self.root, "port": self.ports[name], "ready": lambda p=self.ports[name]: http_status(f"http://127.0.0.1:{p}/") is not None and "responds over HTTP"})
        worker_log = self.run_dir / "logs" / "worker.log"
        worker_cmd = [py, "scripts/fault_boot.py", "worker"] if self.fault_file else [py, "workers/run_worker.py"]
        specs.append({"name": "worker", "cmd": worker_cmd, "cwd": self.root, "port": None,
                      "ready": lambda: worker_log.exists() and b"worker started" in worker_log.read_bytes() and "logged 'worker started'"})
        api_cmd = [py if part == dev.PY else part for part in dev.PROCESSES["api"]]
        api_cmd[api_cmd.index("--port") + 1] = str(self.ports["api"])
        if self.fault_file:
            api_cmd = [py, "scripts/fault_boot.py", "api", "--port", str(self.ports["api"])]
        specs.append({"name": "api", "cmd": api_cmd, "cwd": self.root, "port": self.ports["api"],
                      "ready": lambda: http_status(f"http://127.0.0.1:{self.ports['api']}/api/v1/health") == 200 and "GET /api/v1/health 200 (database reachable)"})
        return specs

    def ui_spec(self) -> dict:
        vite = self.root / "frontend" / "node_modules" / "vite" / "bin" / "vite.js"
        return {"name": "ui", "cmd": [shutil.which("node") or "node", str(vite), "--host", "127.0.0.1", "--port", str(self.ports["ui"])], "cwd": self.root / "frontend", "port": self.ports["ui"],
                "ready": lambda: all(http_status(f"http://127.0.0.1:{self.ports['ui']}{path}") == 200 for path in ("/", "/src/main.tsx", "/api/v1/health")) and "page, entry module and /api proxy answer 200"}

    def start_service(self, spec: dict) -> str:
        rec = spawn(spec["name"], spec["cmd"], spec["cwd"], self.env, self.run_dir / "logs" / f"{spec['name']}.log")
        self.state["processes"].append(rec)
        save_state(self.state)
        alive = lambda: process_info(rec["pid"]) is not None  # noqa: E731
        try:
            return wait_until(spec["name"], spec["ready"], self.ready_seconds, alive)
        except DemoError as exc:
            raise DemoError(exc.step, exc.message + " | " + self.diagnose(spec, rec), exc.hint) from None

    def diagnose(self, spec: dict, rec: dict) -> str:
        """Evidence captured when a service is not ready in time (so a rare stall is explained next time instead of guessed): is the process alive, does the port accept connections,
        what do a request that needs no database and the readiness request return now, and the last lines of its log (secrets redacted)."""
        parts = [f"process {'alive' if process_info(rec['pid']) else 'GONE'}"]
        port = spec.get("port")
        if port:
            parts.append(f"port {port} {'accepts connections' if port_in_use(port) else 'REFUSES connections'}")
            parts.append("GET / -> " + http_detail(f"http://127.0.0.1:{port}/"))
            if spec["name"] == "api":
                parts.append("GET /api/v1/health -> " + http_detail(f"http://127.0.0.1:{port}/api/v1/health", timeout=10.0))
        parts.append("log tail: " + log_tail(Path(rec["log"]), env_file=self.env_file).replace("\n", " // "))
        return "; ".join(parts)

    # ---- phases
    def start(self, with_ui: bool = True, onboard: bool = True) -> None:
        if (state := load_state()) is not None:
            raise DemoError("state", describe_state(state), "run `python scripts/demo.py down` first (it stops only what that run created); a run that is still in progress must finish or be interrupted first")
        self.step("preflight", lambda: self._preflight(with_ui))
        self.state["started_by"] = "demo.py"
        claim_state(self.state)  # recorded BEFORE creating anything (exclusively), so an interruption can always be cleaned up and two launchers cannot both own the state
        if self.ai == "real":
            self.step("ollama (real-AI mode)", self._start_ollama)
        self.step(f"create disposable database {self.db_name}", self._create_db)
        self.step("apply migrations (alembic upgrade head)", self._migrate)
        self.step("seed Apex Industrial fixtures", self.steps.get("seed", lambda: self.python_step(["scripts/seed_apex.py"], "seed-apex")))
        for spec in self.services():
            self.step(f"start {spec['name']} and wait for readiness", lambda s=spec: self.start_service(s))
        if onboard:
            self.step("onboard Meridian Fleet (public API)", self.steps.get("onboard", lambda: self.python_step(["scripts/onboard_tenant.py", "onboarding/meridian.json", "--api", f"http://127.0.0.1:{self.ports['api']}"], "onboard-meridian")))
        if with_ui:
            self.step("start frontend and wait for readiness", lambda: self.start_service(self.ui_spec()))

    def _preflight(self, with_ui: bool) -> str:
        results = preflight(self.env_file, ai=self.ai, ports=self.ports, root=self.root, need_ui=with_ui) if "preflight" not in self.steps else self.steps["preflight"]()
        bad = [r for r in results if not r["ok"]]
        self.preflight_results = results
        if bad:
            raise DemoError("preflight", "; ".join(f"{r['check']}: {r['detail']}" for r in bad), " | ".join(r["hint"] for r in bad if r["hint"]))
        return f"{len(results)} checks passed"

    def _start_ollama(self) -> str:
        import ollama_ctl
        if not ollama_ctl.is_up():
            if not ollama_ctl.start():
                raise DemoError("ollama", "Ollama could not be started", "see docs/operations/real-ai-setup-windows.md")
            self.state["ollama_started"] = True
            save_state(self.state)
        model = self.env_file.get("OLLAMA_MODEL") or "qwen2.5:1.5b"
        if not ollama_model_present(model):
            raise DemoError("ollama", f"model {model} is not available locally", f"run `ollama pull {model}` yourself; the launcher never downloads models")
        return f"model {model} present"

    def _create_db(self) -> str:
        (self.steps.get("create_db") or (lambda: create_database(self.env_file, self.db_name)))()
        self.state["db_created"] = True
        save_state(self.state)
        return "created"

    def _migrate(self) -> str:
        if "migrate" in self.steps:
            self.steps["migrate"]()
        else:
            self.python_step(["scripts/migrate.py"], "migrate")
            got, want = database_revision(self.env_file, self.db_name), head_revision()
            if got != want:
                raise DemoError("migrate", f"database is at revision {got}, expected head {want}")
        self.state["revision"] = database_revision(self.env_file, self.db_name) if "migrate" not in self.steps else "(injected)"
        return f"revision {self.state['revision']}"

    # ---- teardown
    def teardown(self, state: dict | None = None) -> list[dict]:
        """Stop what this run created (reverse order), then drop its database. Safe to repeat, safe after a partial startup, and RESUMABLE: the state file is updated
        after every resource, so an interrupted shutdown is finished by the next `down` without touching anything twice."""
        state = state or self.state
        results = []

        def persist():
            current = load_state()
            if current is not None and current.get("run_id") == state.get("run_id"):
                save_state(state)

        for rec in list(reversed(state.get("processes", []))):
            results.append({"resource": f"process {rec['name']} (pid {rec['pid']})", "result": stop_record(rec)})
            state["processes"].remove(rec)
            persist()
        if state.get("ollama_started"):
            try:
                import ollama_ctl
                ollama_ctl.stop()
                results.append({"resource": "ollama (started by this run)", "result": "stopped"})
            except Exception as exc:  # noqa: BLE001
                results.append({"resource": "ollama", "result": f"stop failed: {type(exc).__name__}"})
            state["ollama_started"] = False
            persist()
        if state.get("db_created"):
            try:
                gone = (self.steps.get("drop_db") or (lambda: drop_database(self.env_file, state["db_name"])))()
                results.append({"resource": f"database {state['db_name']}", "result": "dropped" if gone is not False else "still present"})
                if gone is not False:
                    state["db_created"] = False
                    persist()
            except Exception as exc:  # noqa: BLE001
                results.append({"resource": f"database {state['db_name']}", "result": f"drop failed: {type(exc).__name__}: {str(exc)[:120]}"})
        else:
            results.append({"resource": "database", "result": "none created by this run: nothing dropped"})
        leftover = state.get("processes") or state.get("db_created")
        if not leftover and STATE_FILE.exists() and (load_state() or {}).get("run_id") == state.get("run_id"):
            STATE_FILE.unlink()
        return results


# ------------------------------------------------------------------------------------------------------------------------------------------ backup / restore
BACKUP_DIR = ROOT / "backups" / "demo"
RESTORE_PREFIX = DB_PREFIX + "restore_"
TENANT_TABLES = ["documents", "incidents", "tickets", "audit_events", "approvals", "outbox_events", "connectors", "memberships", "document_chunks"]


def _pg(env_file: dict, args: list[str], *, stdin=None, stdout=None, timeout: float = 600):
    """Run a PostgreSQL client tool inside the project's own postgres container (docker compose exec). The password travels as an inherited environment variable,
    never on a command line, in a log or in a backup."""
    env = {**os.environ, **env_file, "PGPASSWORD": env_file.get("POSTGRES_PASSWORD", "")}
    cmd = ["docker", "compose", "exec", "-T", "-e", "PGPASSWORD", "postgres", *args]
    return subprocess.run(cmd, cwd=ROOT, env=env, stdin=stdin, stdout=stdout if stdout is not None else subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)


def _owner_connection(env_file: dict, db_name: str):
    from sqlalchemy import create_engine
    from app.core.config import get_settings
    saved = {k: os.environ.get(k) for k in env_file}
    os.environ.update(env_file)
    try:
        url = get_settings(db_name=db_name).url("owner")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return create_engine(url).connect()


def database_snapshot(env_file: dict, db_name: str) -> dict:
    """Facts used to prove a restore: revision, tenants, exact row counts of every public table (taken as the superuser owner, which bypasses row-level security), per-tenant counts of the
    tenant-scoped tables, and the row-level-security flags of every table."""
    with _owner_connection(env_file, db_name) as conn:
        if not conn.exec_driver_sql("SELECT rolsuper FROM pg_roles WHERE rolname = current_user").scalar():
            raise DemoError("backup", "the PostgreSQL owner role is not a superuser, so row counts under forced row-level security cannot be taken", "use the project's compose database user")
        tables = [r[0] for r in conn.exec_driver_sql("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1")]
        counts = {t: conn.exec_driver_sql(f'SELECT count(*) FROM "{t}"').scalar() for t in tables}
        tenants = {str(r[0]): r[1] for r in conn.exec_driver_sql("SELECT id, slug FROM tenants ORDER BY slug")}
        per_tenant = {tid: {t: conn.exec_driver_sql(f'SELECT count(*) FROM "{t}" WHERE tenant_id = %s', (tid,)).scalar() for t in TENANT_TABLES if t in tables} for tid in tenants}
        rls = {r[0]: [r[1], r[2]] for r in conn.exec_driver_sql("SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'r' ORDER BY 1")}
        policies = conn.exec_driver_sql("SELECT count(*) FROM pg_policies WHERE schemaname = 'public'").scalar()
        revision = conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar()
    return {"revision": revision, "tenants": tenants, "row_counts": counts, "per_tenant_counts": per_tenant, "rls_flags": rls, "policy_count": policies}


def backup_database(env_file: dict, db_name: str, out_dir: Path) -> dict:
    """pg_dump (custom format) of ONE explicitly named disposable demo database into out_dir (outside .demo/, so teardown never removes it) plus a manifest of what it must restore to."""
    import hashlib
    safe_db_name(db_name, env_file.get("POSTGRES_DB", "eaop"))
    owner = env_file.get("POSTGRES_USER", "eaop")
    snapshot = database_snapshot(env_file, db_name)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")  # noqa: UP017
    target = out_dir / f"{db_name}-{stamp}.dump"
    with open(target, "wb") as handle:
        res = _pg(env_file, ["pg_dump", "-U", owner, "-d", db_name, "-Fc"], stdout=handle)
    if res.returncode:
        target.unlink(missing_ok=True)
        raise DemoError("backup", f"pg_dump failed (exit {res.returncode}): {res.stderr.decode('utf-8', 'replace')[:300]}", "is the PostgreSQL container running? (python scripts/dev.py up)")
    manifest = {"file": str(target.relative_to(ROOT)) if target.is_relative_to(ROOT) else str(target), "database": db_name, "created_at": datetime.now(EST).isoformat(timespec="seconds"), "format": "pg_dump custom (-Fc)",
                "bytes": target.stat().st_size, "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "contains": "tenant data, audit log and password HASHES of the fictional demo accounts; no .env values, API keys or connection strings",
                **snapshot}
    Path(str(target) + ".manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8", newline="\n")
    return manifest


def restore_check(env_file: dict, backup: Path, *, keep: bool = False) -> dict:
    """Restore a backup into a NEW database owned by this call, verify it against the manifest, then drop it (unless keep). Never touches any other database."""
    import hashlib
    backup = backup if backup.is_absolute() else ROOT / backup
    manifest_path = Path(str(backup) + ".manifest.json")
    if not backup.exists() or not manifest_path.exists():
        raise DemoError("restore", f"backup or manifest not found: {backup}", "create one with `python scripts/demo.py backup`")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checks = []

    def add(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    add("backup file matches its manifest (sha256, size)", hashlib.sha256(backup.read_bytes()).hexdigest() == manifest["sha256"] and backup.stat().st_size == manifest["bytes"], f"{manifest['bytes']} bytes")
    restore_db = RESTORE_PREFIX + datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:4]
    safe_db_name(restore_db, env_file.get("POSTGRES_DB", "eaop"))
    owner, created = env_file.get("POSTGRES_USER", "eaop"), False
    result = {"restore_db": restore_db, "restore_db_state": "not created", "checks": checks, "ok": False, "manifest": manifest["file"]}
    if not checks[0]["ok"]:  # a tampered or truncated backup is never restored
        return result
    try:
        create_database(env_file, restore_db)
        created = True
        with open(backup, "rb") as handle:
            res = _pg(env_file, ["pg_restore", "-U", owner, "-d", restore_db, "--exit-on-error"], stdin=handle)
        add("pg_restore into a new isolated database", res.returncode == 0, "completed" if res.returncode == 0 else res.stderr.decode("utf-8", "replace")[:300])
        if res.returncode == 0:
            snap = database_snapshot(env_file, restore_db)
            add("migration revision preserved", snap["revision"] == manifest["revision"], snap["revision"])
            add("tenants preserved", snap["tenants"] == manifest["tenants"], ", ".join(sorted(snap["tenants"].values())))
            add("row counts of every table equal the source", snap["row_counts"] == manifest["row_counts"], f"{len(snap['row_counts'])} tables, {sum(snap['row_counts'].values())} rows")
            add("per-tenant counts equal the source", snap["per_tenant_counts"] == manifest["per_tenant_counts"], "documents, incidents, tickets, audit, approvals, outbox, connectors, memberships, chunks")
            add("row-level security enabled and forced exactly as in the source", snap["rls_flags"] == manifest["rls_flags"] and snap["policy_count"] == manifest["policy_count"], f"{snap['policy_count']} policies")
            add("tenant isolation holds for the restricted application role", *_isolation_check(env_file, restore_db, manifest))
            add("backup contains no secret values from .env", *_secret_scan(env_file, backup, owner))
    except DemoError as exc:
        add("restore", False, str(exc))
    finally:
        if created and not keep:
            try:
                result["restore_db_state"] = "dropped" if drop_database(env_file, restore_db) else "still present"
            except Exception as exc:  # noqa: BLE001
                result["restore_db_state"] = f"drop failed: {type(exc).__name__}"
        elif created:
            result["restore_db_state"] = "kept (--keep)"
    result["ok"] = bool(checks) and all(c["ok"] for c in checks)
    return result


def _isolation_check(env_file: dict, db_name: str, manifest: dict) -> tuple[bool, str]:
    """Connect to the RESTORED database as the restricted application role: each tenant sees exactly its own rows, and with no tenant context nothing is visible."""
    from sqlalchemy import create_engine
    from app.core.config import get_settings
    saved = {k: os.environ.get(k) for k in env_file}
    os.environ.update(env_file)
    try:
        url = get_settings(db_name=db_name).url("app")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    engine = create_engine(url)
    seen_total = {t: 0 for t in ("documents", "incidents", "tickets", "audit_events")}
    with engine.connect() as conn:
        for tid in manifest["tenants"]:
            with conn.begin():
                conn.exec_driver_sql("SELECT set_config('app.tenant_id', %s, true)", (tid,))
                for table in seen_total:
                    visible = conn.exec_driver_sql(f'SELECT count(*) FROM "{table}"').scalar()
                    if visible != manifest["per_tenant_counts"][tid][table]:
                        return False, f"tenant {manifest['tenants'][tid]} sees {visible} {table} rows, expected {manifest['per_tenant_counts'][tid][table]}"
                    seen_total[table] += visible
        with conn.begin():
            blind = {t: conn.exec_driver_sql(f'SELECT count(*) FROM "{t}"').scalar() for t in seen_total}
    engine.dispose()
    if any(blind.values()):
        return False, f"rows are visible without a tenant context: {blind}"
    return True, f"{len(manifest['tenants'])} tenants each see only their own rows; with no tenant context 0 rows are visible"


def _secret_scan(env_file: dict, backup: Path, owner: str) -> tuple[bool, str]:
    with open(backup, "rb") as handle:
        res = _pg(env_file, ["pg_restore", "-f", "-"], stdin=handle)
    text = res.stdout.decode("utf-8", "replace")
    if res.returncode or "CREATE TABLE" not in text:
        return False, f"could not read the dump as text (exit {res.returncode}); the scan would prove nothing"
    names = [k for k, v in env_file.items() if any(w in k for w in ("PASSWORD", "SECRET", "KEY", "TOKEN")) and len(v) >= 6 and v in text]
    return (not names and res.returncode == 0), ("no secret value found in the dump text" if not names else "found values of: " + ", ".join(names))


def backup_and_verify(env_file: dict, db_name: str) -> dict:
    manifest = backup_database(env_file, db_name, BACKUP_DIR)
    check = restore_check(env_file, ROOT / manifest["file"] if not Path(manifest["file"]).is_absolute() else Path(manifest["file"]))
    if not check["ok"]:
        raise DemoError("backup", "the backup did not restore cleanly: " + "; ".join(c["check"] + ": " + c["detail"] for c in check["checks"] if not c["ok"]))
    return {"file": manifest["file"], "bytes": manifest["bytes"], "sha256": manifest["sha256"], "source_database": db_name, "restore_database": check["restore_db"], "restore_database_state": check["restore_db_state"],
            "checks": check["checks"], "tenants": sorted(manifest["tenants"].values()), "tables": len(manifest["row_counts"]), "rows": sum(manifest["row_counts"].values())}


# ------------------------------------------------------------------------------------------------------------------------------------------ commands
def env_from(args) -> dict:
    return load_env_file(Path(args.env_file) if getattr(args, "env_file", None) else ROOT / ".env")


def cmd_preflight(args) -> int:
    env_file = env_from(args)
    results = preflight(env_file, ai=args.ai, need_browser=True)
    for r in results:
        print(f"  {'ok  ' if r['ok'] else 'FAIL'} {r['check']}: {r['detail']}" + ("" if r["ok"] or not r["hint"] else f"\n       -> {r['hint']}"))
    return 0 if all(r["ok"] for r in results) else 1


def print_access(demo: Demo) -> None:
    p = demo.ports
    say(f"READY. UI http://127.0.0.1:{p['ui']}  API docs http://127.0.0.1:{p['api']}/docs  (database {demo.db_name}, disposable)")
    say("Accounts: admin|supervisor|engineer|auditor @apex.example.test (tenant apex-industrial) and @meridian.example.test (tenant meridian-fleet); password = SEED_PASSWORD in your .env")
    say("Mock external systems are simulated (ticketing 8101, inventory 8102, fleet 8103, CRM 8104, service desk 8105). Stop everything with: python scripts/demo.py down")


def make_demo(args) -> "Demo":
    """Factory used by the commands (tests replace it to inject fake services)."""
    return Demo(ai=args.ai, env_file=env_from(args))


def cmd_up(args) -> int:
    demo = make_demo(args)
    try:
        demo.start()
        demo.state["phase"] = "running"  # the launcher exits now; the services keep running until `down`
        save_state(demo.state)
    except (DemoError, KeyboardInterrupt, Exception) as exc:  # noqa: BLE001 - any failure: clean up what this run created, then explain
        say(("interrupted" if isinstance(exc, KeyboardInterrupt) else "FAILED") + ": " + (str(exc) or type(exc).__name__))
        for r in demo.teardown():
            say(f"cleanup: {r['resource']}: {r['result']}")
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    print_access(demo)
    return 0


def cmd_status(_args) -> int:
    state = load_state()
    if not state:
        say("no demo run is recorded")
        return 0
    say(f"{describe_state(state)}; database {state['db_name']} (created by this run: {state['db_created']})")
    for rec in state["processes"]:
        info = process_info(rec["pid"])
        mine = info is not None and (not rec.get("created") or info["created"] == rec["created"])
        say(f"  {rec['name']:12s} pid {rec['pid']:>6} {'running' if mine else 'not running'}")
    p = state["ports"]
    api_port, ui_port = p["api"], p["ui"]
    api_health = http_status(f"http://127.0.0.1:{api_port}/api/v1/health")
    ui_page = http_status(f"http://127.0.0.1:{ui_port}/")
    say(f"  api health: {api_health}   ui: {ui_page}")
    return 0


def cmd_down(args) -> int:
    state = load_state()
    if not state:
        say("nothing to stop: no demo run is recorded")
        return 0
    if launcher_alive(state):
        say(f"refusing to shut down: {describe_state(state)}. Let it finish, or interrupt that launcher (Ctrl-C) and run `down` again")
        return 2
    demo = Demo(ai=state.get("ai", "deterministic"), ports=state["ports"], env_file=env_from(args))
    demo.run_id, demo.db_name = state["run_id"], state["db_name"]
    try:
        results = demo.teardown(state)
    except KeyboardInterrupt:
        say("shutdown interrupted; the state file was updated after every resource, so running `down` again resumes where this stopped")
        return 130
    for r in results:
        say(f"{r['resource']}: {r['result']}")
    return 0 if not any("failed" in r["result"] or "still" in r["result"] for r in results) else 1


def cmd_smoke(args) -> int:
    import demo_smoke
    t0 = time.time()
    demo = make_demo(args)
    if getattr(args, "ingestion", False):
        demo.fault_file = demo.run_dir / "embed.fault"
        demo.env["EAOP_FAULT_FILE"] = str(demo.fault_file)
    if getattr(args, "rest", False):
        import secrets
        demo.records_key = secrets.token_hex(16)  # run-only credential: never written to .env or any report
        demo.env["MOCK_RECORDS_API_KEY"] = demo.env["RECORDS_API_KEY"] = demo.records_key
        demo.webhook_secrets = {"current": secrets.token_hex(24), "next": secrets.token_hex(24)}  # run-only HMAC signing secrets (environment only, never recorded)
        demo.env["WEBHOOK_DEMO_SECRET"], demo.env["WEBHOOK_DEMO_SECRET_NEXT"] = demo.webhook_secrets["current"], demo.webhook_secrets["next"]
        mocks = json.loads(demo.env.get("EGRESS_DEV_MOCKS") or "{}")
        for slug in ("apex-industrial", "meridian-fleet"):
            mocks.setdefault(slug, [])
            if f"http://127.0.0.1:{PORTS['records']}" not in mocks[slug]:
                mocks[slug].append(f"http://127.0.0.1:{PORTS['records']}")
        demo.env["EGRESS_DEV_MOCKS"] = json.dumps(mocks)  # the child processes only: the records mock is one more development-only local origin
    report = {"run_id": demo.run_id, "mode": "smoke", "ai": args.ai, "started_at": demo.state["started_at"], "executed": [], "failures": [], "skipped": []}
    report["git_head"] = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    rc, cleanup = 0, []
    try:
        demo.start(with_ui=not args.no_browser)
        demo.state["phase"] = "smoke"
        save_state(demo.state)
        report["preflight"] = getattr(demo, "preflight_results", [])
        report["database"] = {"name": demo.db_name, "revision": demo.state.get("revision"), "head": head_revision(), "created_by_this_run": demo.state["db_created"]}
        password = demo.env["SEED_PASSWORD"]
        api = f"http://127.0.0.1:{demo.ports['api']}/api/v1"
        report["workflows"] = demo.step("customer workflows through the API (Apex and Meridian)", lambda: demo_smoke.run_workflows(api, password))
        if getattr(args, "ingestion", False):
            report["ingestion"] = demo.step("live ingestion checkpoint: jobs, retry (simulated outage), reprocessing, deletion races", lambda: demo_smoke.run_ingestion(api, password, demo.fault_file))
        if getattr(args, "rest", False):
            report["rest"] = demo.step("live REST pull synchronization: connector, pagination, rate limit, health probe, recovery (both tenants)",
                                       lambda: demo_smoke.run_rest(api, password, f"http://127.0.0.1:{demo.ports['records']}", demo.records_key))
            report["integrations"] = demo.step("live CSV connector and signed webhook integrations (both tenants)",
                                               lambda: demo_smoke.run_integrations(api, password, f"http://127.0.0.1:{demo.ports['records']}", demo.records_key, demo.webhook_secrets))
        if getattr(args, "compare", False):
            import workflow_comparison
            report["comparison"] = demo.step("manual versus automated measurement protocol (class A measured automated; no B or C data unless supplied)", lambda: workflow_comparison.run(
                api, password, demo_smoke.login, REPORT_ROOT / demo.run_id / "comparison", {"ai": args.ai, "llm": demo.env.get("LLM_BACKEND"), "embedding": demo.env.get("EMBEDDING_BACKEND"),
                                                                                              "note": "deterministic test-only backends: CI/functional only" if args.ai == "deterministic" else "real local backends"}))
        if args.no_browser:
            report["skipped"].append("browser smoke (--no-browser)")
        else:
            report["browser"] = demo.step("browser smoke (Playwright, Microsoft Edge, against this demo stack)", lambda: demo_smoke.run_browser(demo, REPORT_ROOT / demo.run_id))
        if args.backup:
            report["backup"] = demo.step("backup the demo database and prove it restores (isolated restore database)", lambda: backup_and_verify(demo.env_file, demo.db_name))
    except (DemoError, KeyboardInterrupt, Exception) as exc:  # noqa: BLE001
        rc = 130 if isinstance(exc, KeyboardInterrupt) else 1
        report["failures"].append(str(exc) or type(exc).__name__)
        say("FAILED: " + (str(exc) or type(exc).__name__))
    finally:
        cleanup = demo.teardown()
        for r in cleanup:
            say(f"cleanup: {r['resource']}: {r['result']}")
    report.update({"timeline": demo.timeline, "cleanup": cleanup, "duration_seconds": round(time.time() - t0, 1), "finished_at": datetime.now(EST).isoformat(timespec="seconds")})
    report["success"] = rc == 0 and all(r["result"] != "still running after kill (check manually)" for r in cleanup) and not any("failed" in r["result"] for r in cleanup)
    demo_smoke.write_report(REPORT_ROOT / demo.run_id, report, demo.env_file)
    say(f"smoke {'PASSED' if report['success'] else 'FAILED'} in {report['duration_seconds']}s; report: evaluation/demo-runs/{demo.run_id}/report.md")
    return 0 if report["success"] else 1


def cmd_steps(_args) -> int:
    """Print the 27 specification demonstration steps (docs/customer-delivery/demonstration-27-steps.md) with the newest recorded live run. Starts nothing."""
    import json as _json

    table = Path(__file__).resolve().parents[1] / "docs" / "customer-delivery" / "demonstration-27-steps.md"
    rows = [[c.strip() for c in line.strip().strip("|").split("|")] for line in table.read_text(encoding="utf-8").splitlines()
            if line.startswith("|") and line.split("|")[1].strip().isdigit()]
    if len(rows) != 27:
        raise DemoError("steps", f"the step table has {len(rows)} rows, expected 27", "fix docs/customer-delivery/demonstration-27-steps.md")
    for number, step, how, evidence in rows:
        say(f"{int(number):2d}. {step}  [{how}]  evidence: {evidence}")
    runs = sorted((Path(__file__).resolve().parents[1] / "evaluation" / "demo-runs").glob("*/report.json"))
    if runs:
        last = _json.loads(runs[-1].read_text(encoding="utf-8"))
        say(f"newest recorded live run: {last.get('run_id')} ({'PASSED' if last.get('success') else 'FAILED'}, {last.get('duration_seconds')} s, git {str(last.get('git_head'))[:7]})")
    else:
        say("no recorded live run yet: `python scripts/demo.py smoke` creates one")
    say("steps 26 and 27 are explanations (see the document); 24 reruns need Ollama; nothing was started by this command")
    return 0


def cmd_backup(args) -> int:
    env_file = env_from(args)
    name = args.database or (load_state() or {}).get("db_name")
    if not name:
        raise DemoError("backup", "no database selected", "pass --database eaop_demo_<id> or start a demo with `up` first")
    manifest = backup_database(env_file, name, Path(args.out) if args.out else BACKUP_DIR)
    say(f"backup written: {manifest['file']} ({manifest['bytes']} bytes, sha256 {manifest['sha256'][:12]}...); manifest {manifest['file']}.manifest.json")
    return 0


def cmd_restore_check(args) -> int:
    result = restore_check(env_from(args), Path(args.backup), keep=args.keep)
    for item in result["checks"]:
        say(f"  {'ok  ' if item['ok'] else 'FAIL'} {item['check']}: {item['detail']}")
    say(f"restore check {'PASSED' if result['ok'] else 'FAILED'}; restore database {result['restore_db']} {result['restore_db_state']}")
    return 0 if result["ok"] else 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="One-command local demonstration launcher")
    sub = ap.add_subparsers(dest="command", required=True)
    for name in ("preflight", "up", "smoke"):
        p = sub.add_parser(name)
        p.add_argument("--env-file", help="use this file instead of .env (for example a copy with one setting changed)")
        p.add_argument("--ai", choices=["deterministic", "real"], default="deterministic", help="deterministic (default, test-only backends) or real (Ollama + MiniLM; needs them installed)")
        if name == "smoke":
            p.add_argument("--no-browser", action="store_true", help="skip the Playwright browser smoke")
            p.add_argument("--ingestion", action="store_true", help="also run the live ingestion checkpoint (retry with a SIMULATED embedding outage switch, reprocessing, deletion races); starts API and worker through scripts/fault_boot.py")
            p.add_argument("--rest", action="store_true", help="also run the live REST pull synchronization checkpoint against the local records mock (a run-only API key is generated)")
            p.add_argument("--compare", action="store_true", help="also run the manual-versus-automated measurement protocol (evaluation/comparison/protocol.md): class A measured automated only unless observed or assumed data files exist")
            p.add_argument("--backup", action="store_true", help="after the workflows, back up the demo database and prove the backup restores into a new isolated database")
    sub.add_parser("status")
    sub.add_parser("steps", help="print the 27 demonstration steps and the newest recorded run; starts nothing")
    bk = sub.add_parser("backup", help="export an explicitly selected disposable demo database (pg_dump inside the project's PostgreSQL container) to backups/demo/")
    bk.add_argument("--database", help="eaop_demo_<id>; defaults to the database of the recorded demo run")
    bk.add_argument("--out", help="output directory (default backups/demo, git-ignored)")
    bk.add_argument("--env-file")
    rc = sub.add_parser("restore-check", help="restore a backup into a NEW isolated database, verify integrity, tenant isolation and absence of secrets, then drop it")
    rc.add_argument("backup", help="path to a .dump file produced by `backup`")
    rc.add_argument("--keep", action="store_true", help="keep the restored database (it is named eaop_demo_restore_<id>; drop it with `down`-style care)")
    rc.add_argument("--env-file")
    down = sub.add_parser("down")
    down.add_argument("--env-file", help="the same file the run was started with, if you used --env-file")
    args = ap.parse_args(argv)
    try:
        return {"preflight": cmd_preflight, "up": cmd_up, "smoke": cmd_smoke, "status": cmd_status, "steps": cmd_steps, "down": cmd_down, "backup": cmd_backup, "restore-check": cmd_restore_check}[args.command](args)
    except DemoError as exc:
        print(f"demo: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
