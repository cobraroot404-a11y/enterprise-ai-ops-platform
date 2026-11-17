"""Launcher tests (Batch 6, Level 1): preflight, environment validation, ownership-safe cleanup and failure paths of scripts/demo.py.

Most tests use tiny fake services (python one-liners) and injected steps so they are fast and need no application stack. The database tests create and drop real
throwaway databases named eaop_demo_test_* on the local PostgreSQL (the same server the backend tests use) and skip when it is unavailable. Nothing here touches the shared
`eaop` database or any process the tests did not start."""
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import demo  # noqa: E402
import demo_smoke  # noqa: E402

PY = sys.executable
GOOD_ENV = {
    "POSTGRES_PASSWORD": "pg-secret-value", "APP_DB_PASSWORD": "app-secret-value", "WORKER_DB_PASSWORD": "worker-secret-value", "JWT_SECRET": "jwt-secret-value-0123456789",
    "SEED_PASSWORD": "seed-secret-value", "MOCK_TICKETING_API_KEY": "ticketing-key-value", "MOCK_SERVICEDESK_API_KEY": "desk-key-value", "MERIDIAN_SERVICEDESK_KEY": "desk-key-value",
    "EAOP_ENV": "development", "EGRESS_ALLOWLIST": "{}",
    "EGRESS_DEV_MOCKS": json.dumps({"apex-industrial": ["http://127.0.0.1:8101", "http://127.0.0.1:8102"], "meridian-fleet": ["http://127.0.0.1:8103", "http://127.0.0.1:8104", "http://127.0.0.1:8105"]}),
}


@pytest.fixture()
def state_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "STATE_DIR", tmp_path / "demo-state")
    monkeypatch.setattr(demo, "STATE_FILE", tmp_path / "demo-state" / "state.json")
    return tmp_path


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def server_spec(name: str, port: int, *, exit_immediately: bool = False, never_ready: bool = False) -> dict:
    code = "import sys" if exit_immediately else (
        f"import http.server,socketserver;socketserver.TCPServer.allow_reuse_address=True;http.server.HTTPServer(('127.0.0.1',{port}),http.server.SimpleHTTPRequestHandler).serve_forever()")
    ready = (lambda: False) if never_ready else (lambda: demo.http_status(f"http://127.0.0.1:{port}/") is not None and "responds")
    return {"name": name, "cmd": [PY, "-c", code], "cwd": ROOT, "port": port, "ready": ready}


def make_demo(state_dir, services, steps=None, ready_seconds=6.0, env=None):
    d = demo.Demo(ports={"api": free_port(), "ticketing": 1, "inventory": 2, "fleet": 3, "crm": 4, "servicedesk": 5, "ui": free_port()}, env_file=env or dict(GOOD_ENV),
                  services=services, steps={"preflight": lambda: [], "create_db": lambda: None, "drop_db": lambda: True, "migrate": lambda: None, "seed": lambda: "seeded", "onboard": lambda: "onboarded",
                                            **(steps or {})}, ready_seconds=ready_seconds)
    d.db_name = demo.DB_PREFIX + "test_" + uuid.uuid4().hex[:6]
    d.state["db_name"] = d.db_name
    return d


# ------------------------------------------------------------------------------------------------------------------------------- environment validation
def test_a_missing_env_file_gives_an_actionable_error(tmp_path):
    with pytest.raises(demo.DemoError) as exc:
        demo.load_env_file(tmp_path / ".env")
    assert "copy .env.example" in str(exc.value)


def test_env_file_json_values_keep_their_quotes(tmp_path):
    (tmp_path / ".env").write_text('JWT_SECRET=abc\nEGRESS_DEV_MOCKS={"apex-industrial":["http://127.0.0.1:8101"]}\n# comment\n', encoding="utf-8")
    values = demo.load_env_file(tmp_path / ".env")
    assert json.loads(values["EGRESS_DEV_MOCKS"]) == {"apex-industrial": ["http://127.0.0.1:8101"]}


def test_valid_environment_passes():
    assert demo.validate_env(GOOD_ENV) == []


def test_invalid_json_is_named_without_printing_its_value():
    env = {**GOOD_ENV, "EGRESS_DEV_MOCKS": "{apex-industrial:[http://127.0.0.1:8101]}"}  # what a shell does to the quotes
    problems = demo.validate_env(env)
    assert any("EGRESS_DEV_MOCKS is not a valid JSON object" in p for p in problems)
    assert not any("apex-industrial:[http" in p for p in problems)


def test_missing_secrets_unauthorised_mocks_mismatched_keys_and_production_are_reported():
    problems = demo.validate_env({**GOOD_ENV, "JWT_SECRET": "", "MERIDIAN_SERVICEDESK_KEY": "other", "EAOP_ENV": "production",
                                  "EGRESS_DEV_MOCKS": json.dumps({"apex-industrial": ["http://127.0.0.1:8101"]})})
    text = " | ".join(problems)
    assert "JWT_SECRET is missing" in text and "must equal MOCK_SERVICEDESK_API_KEY" in text and "production" in text and "8105" in text
    assert "pg-secret-value" not in text


# ------------------------------------------------------------------------------------------------------------------------------- preflight
def test_preflight_reports_missing_environment_postgres_and_ports_without_changing_anything(tmp_path):
    busy = socket.socket()
    busy.bind(("127.0.0.1", 0))
    busy.listen(1)
    port = busy.getsockname()[1]
    try:
        results = demo.preflight({**GOOD_ENV, "POSTGRES_PORT": "1"}, ports={"api": port, "ui": free_port()}, root=ROOT)
    finally:
        busy.close()
    by_name = {r["check"]: r for r in results}
    assert by_name["ports free"]["ok"] is False and f"api:{port}" in by_name["ports free"]["detail"]
    assert "never stops processes it did not start" in by_name["ports free"]["hint"]
    assert by_name["postgresql"]["ok"] is False and "dev.py up" in by_name["postgresql"]["hint"]


def test_preflight_flags_a_missing_ollama_model_without_downloading(monkeypatch):
    import ollama_ctl
    monkeypatch.setattr(ollama_ctl, "find_exe", lambda: "ollama.exe")
    monkeypatch.setattr(ollama_ctl, "is_up", lambda: True)
    monkeypatch.setattr(ollama_ctl, "get", lambda path, timeout=3.0: {"models": [{"name": "some-other-model"}]})
    results = demo.preflight({**GOOD_ENV, "OLLAMA_MODEL": "missing-model:1b"}, ai="real", ports={"api": free_port(), "ui": free_port()}, root=ROOT)
    model = next(r for r in results if r["check"] == "ollama model")
    assert model["ok"] is False and "ollama pull missing-model:1b" in model["hint"] and "never downloaded" in model["hint"]


# ------------------------------------------------------------------------------------------------------------------------------- database ownership
def test_database_names_outside_the_demo_namespace_are_refused():
    for bad in ("eaop", "eaop_test", "postgres", "eaop_demo_x; DROP DATABASE eaop"):
        with pytest.raises(demo.DemoError):
            demo.safe_db_name(bad, "eaop")
    with pytest.raises(demo.DemoError):
        demo.safe_db_name("eaop_demo_same", "eaop_demo_same")
    demo.safe_db_name("eaop_demo_20261113_ab12", "eaop")


def _postgres_or_skip():
    if os.environ.get("GITHUB_ACTIONS") == "true":
        env = {key: os.environ[key] for key in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "DB_HOST")}
    else:
        env_file = ROOT / ".env"
        if not env_file.is_file():
            pytest.skip("local PostgreSQL integration requires a checkout .env")
        env = demo.load_env_file(env_file)
    try:
        with demo._admin(env) as conn:
            conn.exec_driver_sql("SELECT 1")
    except Exception:  # noqa: BLE001
        pytest.skip("local PostgreSQL is not available")
    return env


def test_a_real_disposable_database_is_created_once_and_dropped_only_by_name_and_ownership():
    env = _postgres_or_skip()
    name = demo.DB_PREFIX + "test_" + uuid.uuid4().hex[:8]
    demo.create_database(env, name)
    with pytest.raises(demo.DemoError):  # a second creation must not adopt an existing database
        demo.create_database(env, name)
    assert demo.drop_database(env, name) is True
    with demo._admin(env) as conn:
        assert conn.exec_driver_sql("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).first() is None
        assert conn.exec_driver_sql("SELECT 1 FROM pg_database WHERE datname = %s", (env.get("POSTGRES_DB", "eaop"),)).first() is not None  # the shared database is untouched


# ------------------------------------------------------------------------------------------------------------------------------- orchestration and cleanup
def test_successful_start_records_processes_and_down_stops_only_them(state_dir):
    bystander = subprocess.Popen([PY, "-c", "import time;time.sleep(120)"])
    d = make_demo(state_dir, [server_spec("fake-api", free_port()), server_spec("fake-mock", free_port())])
    try:
        d.start(with_ui=False)
        state = demo.load_state()
        assert [p["name"] for p in state["processes"]] == ["fake-api", "fake-mock"] and state["db_created"] is True
        pids = [p["pid"] for p in state["processes"]]
        assert all(demo.process_info(pid) for pid in pids)
        results = d.teardown(demo.load_state())
        assert {r["result"] for r in results if r["resource"].startswith("process")} == {"stopped"}
        assert not any(demo.process_info(pid) for pid in pids)
        assert bystander.poll() is None  # an unrelated process was never touched
        assert demo.load_state() is None
    finally:
        bystander.kill()
        d.teardown()


def test_repeated_invocation_is_refused_and_down_twice_is_safe(state_dir):
    d = make_demo(state_dir, [server_spec("fake-api", free_port())])
    d.start(with_ui=False)
    try:
        second = make_demo(state_dir, [server_spec("fake-api", free_port())])
        with pytest.raises(demo.DemoError) as exc:
            second.start(with_ui=False)
        assert "demo.py down" in str(exc.value)
        assert second.state["processes"] == [] and second.state["db_created"] is False  # the refused run created nothing
    finally:
        first = d.teardown(demo.load_state())
    again = d.teardown(d.state)  # nothing recorded any more: must not raise
    assert any("stopped" in r["result"] or "already" in r["result"] for r in first)
    assert all(r["result"] in ("already stopped", "dropped") or r["resource"] == "database" for r in again)


@pytest.mark.parametrize("failing", ["exit", "not_ready"])
def test_mock_or_backend_readiness_failure_cleans_up_partial_state(state_dir, failing):
    started_ok = server_spec("fake-mock", free_port())
    bad = server_spec("fake-api", free_port(), exit_immediately=failing == "exit", never_ready=failing == "not_ready")
    d = make_demo(state_dir, [started_ok, bad], ready_seconds=3.0)
    with pytest.raises(demo.DemoError) as exc:
        d.start(with_ui=False)
    assert "fake-api" in str(exc.value)
    if failing == "not_ready":  # a service that is alive but never ready is explained, not just timed out
        assert "process alive" in str(exc.value) and "accepts connections" in str(exc.value) and "log tail" in str(exc.value)
    pids = [p["pid"] for p in d.state["processes"]]
    assert len(pids) == 2
    results = d.teardown()
    assert not any(demo.process_info(pid) for pid in pids)
    assert any(r["resource"].startswith("database") and r["result"] == "dropped" for r in results)
    assert demo.load_state() is None


@pytest.mark.parametrize("which", ["migrate", "seed", "create_db", "onboard"])
def test_migration_fixture_and_database_failures_stop_startup_and_clean_up(state_dir, which):
    def boom():
        raise demo.DemoError(which, "injected failure")
    d = make_demo(state_dir, [server_spec("fake-api", free_port())], steps={which: boom})
    with pytest.raises(demo.DemoError):
        d.start(with_ui=False)
    created = which != "create_db"
    assert d.state["db_created"] is created  # recorded before teardown: only a database this run created is ever dropped
    results = d.teardown()
    assert demo.load_state() is None
    assert (not created) or any(r["resource"].startswith("database") and r["result"] == "dropped" for r in results)
    if not created:
        assert any(r["resource"] == "database" and "nothing dropped" in r["result"] for r in results)
    assert not any(demo.process_info(p["pid"]) for p in d.state["processes"])
    assert which in {t["step"] for t in d.timeline} | {t["step"].split()[0] for t in d.timeline} or d.timeline[-1]["ok"] is False


def test_an_interrupted_startup_is_cleaned_up(state_dir):
    def interrupted():
        raise KeyboardInterrupt
    d = make_demo(state_dir, [server_spec("fake-api", free_port())], steps={"seed": interrupted})
    with pytest.raises(KeyboardInterrupt):
        d.start(with_ui=False)
    assert demo.load_state() is not None  # recorded before anything was created, so `down` can always find it
    d.teardown(demo.load_state())
    assert demo.load_state() is None


def test_a_recycled_pid_is_not_terminated(state_dir):
    other = subprocess.Popen([PY, "-c", "import time;time.sleep(60)"])
    try:
        record = {"name": "x", "pid": other.pid, "created": "1999-01-01T00:00:00.0000000Z"}  # the recorded creation time does not match this process
        assert "pid was reused" in demo.stop_record(record)
        assert other.poll() is None
    finally:
        other.kill()


def test_preflight_failure_prevents_any_creation(state_dir):
    d = make_demo(state_dir, [server_spec("fake-api", free_port())], steps={"preflight": lambda: [{"check": "ports free", "ok": False, "detail": "in use: api:8000", "hint": "stop it yourself"}]})
    with pytest.raises(demo.DemoError) as exc:
        d.start(with_ui=False)
    assert "ports free" in str(exc.value)
    assert d.state["processes"] == [] and d.state["db_created"] is False and demo.load_state() is None


# ------------------------------------------------------------------------------------------------------------------------------- evidence
def test_reports_never_contain_secret_values(tmp_path):
    report = {"run_id": "t", "mode": "smoke", "ai": "deterministic", "success": True, "failures": ["leaked seed-secret-value and jwt-secret-value-0123456789 in a message"],
              "timeline": [{"step": "x", "ok": True, "seconds": 1, "detail": "token desk-key-value"}], "cleanup": []}
    demo_smoke.write_report(tmp_path, report, GOOD_ENV)
    text = (tmp_path / "report.json").read_text(encoding="utf-8") + (tmp_path / "report.md").read_text(encoding="utf-8")
    for secret in ("seed-secret-value", "jwt-secret-value-0123456789", "desk-key-value", "pg-secret-value"):
        assert secret not in text
    assert "[redacted]" in text


def test_the_demo_state_directory_is_git_ignored():
    assert ".demo/" in (ROOT / ".gitignore").read_text(encoding="utf-8")
    time.sleep(0)
