"""Batch 7: process and resource ownership of scripts/demo.py under interruption, staleness, concurrency and failed browser runs, plus the backup / restore-check procedure.

Fast tests use fake services and injected steps (see test_demo_launcher.py). The backup integration test creates, backs up, restores and drops real throwaway databases named
eaop_demo_test_* / eaop_demo_restore_* on the local PostgreSQL and is skipped when it is unavailable. Nothing touches the shared `eaop` database or a process the tests did not start."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import uuid
from pathlib import Path

import demo
import demo_smoke
import pytest
from test_demo_launcher import GOOD_ENV, ROOT, free_port, make_demo, server_spec


@pytest.fixture()
def state_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "STATE_DIR", tmp_path / "demo-state")
    monkeypatch.setattr(demo, "STATE_FILE", tmp_path / "demo-state" / "state.json")
    return tmp_path


def dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


# ------------------------------------------------------------------------------------------------------------------------------- state file
def test_state_updates_are_atomic_and_leave_no_temporary_files(state_dir):
    demo.save_state({"run_id": "a", "processes": []})
    demo.save_state({"run_id": "a", "processes": [{"name": "x"}]})
    assert demo.load_state()["processes"] == [{"name": "x"}]
    assert [p.name for p in demo.STATE_DIR.iterdir()] == ["state.json"]


def test_claim_is_exclusive(state_dir):
    demo.claim_state({"run_id": "first"})
    with pytest.raises(demo.DemoError) as exc:
        demo.claim_state({"run_id": "second"})
    assert "claimed the state file" in str(exc.value)
    assert demo.load_state()["run_id"] == "first"


def test_concurrent_launchers_exactly_one_wins_and_the_loser_creates_nothing(state_dir):
    outcomes, demos = {}, {}

    def attempt(i):
        d = make_demo(state_dir, [server_spec(f"fake-{i}", free_port())])
        demos[i] = d
        try:
            d.start(with_ui=False)
            outcomes[i] = "started"
        except demo.DemoError as exc:
            outcomes[i] = "refused: " + exc.message[:60]

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    winners = [i for i, o in outcomes.items() if o == "started"]
    try:
        assert len(winners) == 1, outcomes
        state = demo.load_state()
        assert state["run_id"] == demos[winners[0]].run_id  # the loser did not overwrite the winner's record
        for i, d in demos.items():
            if i not in winners:
                assert d.state["processes"] == [] and d.state["db_created"] is False  # refused before creating anything
    finally:
        for i in winners:
            demos[i].teardown(demo.load_state())


def test_a_stale_state_is_described_as_stale_and_down_cleans_it_up(state_dir):
    d = make_demo(state_dir, [server_spec("fake-api", free_port())])
    d.start(with_ui=False)
    state = demo.load_state()
    state["launcher_pid"] = dead_pid()  # the launcher that wrote this state is gone: the run was interrupted
    state["launcher_created"] = "1999-01-01T00:00:00Z"
    demo.save_state(state)
    second = make_demo(state_dir, [server_spec("fake-api", free_port())])
    with pytest.raises(demo.DemoError) as exc:
        second.start(with_ui=False)
    assert "no longer running" in str(exc.value) and "demo.py down" in str(exc.value)
    results = d.teardown(demo.load_state())
    assert any(r["result"] == "stopped" for r in results) and demo.load_state() is None


def test_down_refuses_while_the_recording_launcher_is_still_working(state_dir, monkeypatch, capsys):
    bystander = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"])
    try:
        info = demo.process_info(os.getpid())
        demo.save_state({"run_id": "r", "db_name": demo.DB_PREFIX + "x", "db_created": False, "processes": [{"name": "b", "pid": bystander.pid, "created": demo.process_info(bystander.pid)["created"]}],
                         "ports": demo.PORTS, "ai": "deterministic", "phase": "starting", "launcher_pid": os.getpid(), "launcher_created": info["created"]})
        monkeypatch.setattr(demo, "env_from", lambda args: dict(GOOD_ENV))
        assert demo.cmd_down(argparse.Namespace(env_file=None)) == 2
        assert bystander.poll() is None and demo.load_state() is not None
        assert "refusing to shut down" in capsys.readouterr().out
    finally:
        bystander.kill()


def test_a_running_phase_state_is_not_blocked_by_a_dead_or_reused_launcher_pid(state_dir):
    state = {"run_id": "r", "phase": "running", "launcher_pid": os.getpid(), "launcher_created": "x"}
    assert demo.launcher_alive(state) is False  # `up` returned on purpose; only `down` is expected now


# ------------------------------------------------------------------------------------------------------------------------------- interrupted and resumed shutdown
def test_an_interrupted_shutdown_is_resumed_by_the_next_down_without_repeating_work(state_dir, monkeypatch):
    d = make_demo(state_dir, [server_spec("fake-a", free_port()), server_spec("fake-b", free_port()), server_spec("fake-c", free_port())])
    d.start(with_ui=False)
    names = [p["name"] for p in demo.load_state()["processes"]]
    assert names == ["fake-a", "fake-b", "fake-c"]
    real_stop, calls = demo.stop_record, []

    def interrupting(rec):
        calls.append(rec["name"])
        if len(calls) == 2:
            raise KeyboardInterrupt
        return real_stop(rec)

    monkeypatch.setattr(demo, "stop_record", interrupting)
    with pytest.raises(KeyboardInterrupt):
        d.teardown(demo.load_state())
    remaining = demo.load_state()
    assert [p["name"] for p in remaining["processes"]] == ["fake-b", "fake-a"] or [p["name"] for p in remaining["processes"]] == ["fake-a", "fake-b"]  # fake-c was stopped and removed
    assert "fake-c" not in [p["name"] for p in remaining["processes"]] and remaining["db_created"] is True
    monkeypatch.setattr(demo, "stop_record", real_stop)
    results = d.teardown(demo.load_state())
    assert {r["resource"].split()[1] for r in results if r["resource"].startswith("process")} == {"fake-a", "fake-b"}  # fake-c is not touched again
    assert any(r["result"] == "dropped" for r in results) and demo.load_state() is None


def test_a_stale_pid_record_is_dropped_from_the_state_without_killing_the_new_owner(state_dir):
    other = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"])
    try:
        demo.save_state({"run_id": "r", "db_name": demo.DB_PREFIX + "x", "db_created": False, "processes": [{"name": "old", "pid": other.pid, "created": "1999-01-01T00:00:00Z"}], "ports": demo.PORTS})
        d = make_demo(state_dir, [])
        results = d.teardown(demo.load_state())
        assert "pid was reused" in results[0]["result"] and other.poll() is None and demo.load_state() is None
    finally:
        other.kill()


# ------------------------------------------------------------------------------------------------------------------------------- failed browser run
def test_a_failed_browser_smoke_still_cleans_up_and_writes_a_failure_report(state_dir, monkeypatch):
    monkeypatch.setattr(demo, "REPORT_ROOT", state_dir / "evaluation" / "demo-runs")
    fake = make_demo(state_dir, [server_spec("fake-api", free_port())])
    fake.ui_spec = lambda: server_spec("fake-ui", free_port())  # no real Vite server in this unit test
    monkeypatch.setattr(demo, "make_demo", lambda args: fake)
    monkeypatch.setattr(demo_smoke, "run_workflows", lambda api, pw: {"tenants": {}})

    def failing_browser(d, outdir):
        raise demo_smoke.SmokeFailure("browser smoke failed or incomplete: 0 passed, 2 failed of 2")

    monkeypatch.setattr(demo_smoke, "run_browser", failing_browser)
    fake.env["SEED_PASSWORD"] = "seed-secret-value"
    rc = demo.cmd_smoke(argparse.Namespace(ai="deterministic", no_browser=False, backup=False, env_file=None))
    assert rc == 1
    report = json.loads((state_dir / "evaluation" / "demo-runs" / fake.run_id / "report.json").read_text(encoding="utf-8"))
    assert report["success"] is False and "browser smoke failed" in report["failures"][0]
    assert any(c["result"] == "stopped" for c in report["cleanup"]) and any(c["result"] == "dropped" for c in report["cleanup"])
    assert demo.load_state() is None
    assert "seed-secret-value" not in json.dumps(report)


# ------------------------------------------------------------------------------------------------------------------------------- backup and restore
def test_backup_refuses_databases_that_are_not_disposable_demo_databases(tmp_path):
    for name in ("eaop", "eaop_test", "postgres", "eaop_demo_x; DROP DATABASE eaop"):
        with pytest.raises(demo.DemoError):
            demo.backup_database(dict(GOOD_ENV), name, tmp_path)


def test_restore_check_needs_the_manifest_and_refuses_a_tampered_backup_without_creating_anything(tmp_path):
    with pytest.raises(demo.DemoError):
        demo.restore_check(dict(GOOD_ENV), tmp_path / "missing.dump")
    dump = tmp_path / "x.dump"
    dump.write_bytes(b"not a real dump")
    (tmp_path / "x.dump.manifest.json").write_text(json.dumps({"file": "x.dump", "sha256": hashlib.sha256(b"something else").hexdigest(), "bytes": 3, "revision": "0008", "tenants": {}, "row_counts": {}, "per_tenant_counts": {},
                                                               "rls_flags": {}, "policy_count": 0}), encoding="utf-8")
    result = demo.restore_check(dict(GOOD_ENV), dump)
    assert result["ok"] is False and result["restore_db_state"] == "not created" and len(result["checks"]) == 1


def _postgres_or_skip():
    env_file = ROOT / ".env"
    if not env_file.is_file():
        pytest.skip("local PostgreSQL integration requires a checkout .env")
    env = demo.load_env_file(env_file)
    try:
        with demo._admin(env) as conn:
            conn.exec_driver_sql("SELECT 1")
        import subprocess as sp
        if sp.run(["docker", "compose", "ps", "-q", "postgres"], cwd=ROOT, capture_output=True, text=True, timeout=30).stdout.strip() == "":
            pytest.skip("the project's PostgreSQL container is not running")
    except Exception:  # noqa: BLE001
        pytest.skip("local PostgreSQL / docker is not available")
    return env


def test_a_real_backup_restores_into_a_new_database_with_data_rls_and_isolation_intact(tmp_path):
    env = _postgres_or_skip()
    name = demo.DB_PREFIX + "test_" + uuid.uuid4().hex[:8]
    demo.create_database(env, name)
    restored = None
    try:
        child = demo.child_env(env, name, "deterministic", demo.PORTS)
        for script in ("scripts/migrate.py", "scripts/seed_apex.py"):
            assert subprocess.run([sys.executable, script], cwd=ROOT, env=child, capture_output=True, timeout=300).returncode == 0
        manifest = demo.backup_database(env, name, tmp_path)
        assert Path(manifest["file"]).exists() or (ROOT / manifest["file"]).exists()
        assert manifest["revision"] == demo.head_revision() and "apex-industrial" in manifest["tenants"].values() and sum(manifest["row_counts"].values()) > 20
        for secret_name, value in env.items():  # the manifest never carries credentials
            if any(w in secret_name for w in ("PASSWORD", "SECRET", "KEY")) and len(value) >= 6:
                assert value not in json.dumps(manifest)
        dump = Path(manifest["file"]) if Path(manifest["file"]).is_absolute() else ROOT / manifest["file"]
        result = demo.restore_check(env, dump)
        restored = result["restore_db"]
        assert result["ok"], [c for c in result["checks"] if not c["ok"]]
        assert result["restore_db_state"] == "dropped"
        with demo._admin(env) as conn:  # the restore database is gone, the source and the shared database are untouched
            assert conn.exec_driver_sql("SELECT 1 FROM pg_database WHERE datname = %s", (restored,)).first() is None
            assert conn.exec_driver_sql("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).first() is not None
            assert conn.exec_driver_sql("SELECT 1 FROM pg_database WHERE datname = %s", (env.get("POSTGRES_DB", "eaop"),)).first() is not None
        corrupt = tmp_path / "corrupt.dump"
        corrupt.write_bytes(dump.read_bytes()[:-50])
        (tmp_path / "corrupt.dump.manifest.json").write_text((Path(str(dump) + ".manifest.json")).read_text(encoding="utf-8"), encoding="utf-8")
        bad = demo.restore_check(env, corrupt)
        assert bad["ok"] is False and bad["restore_db_state"] == "not created"  # truncated backup: detected by the checksum before any restore
    finally:
        demo.drop_database(env, name)


def test_playwright_results_are_summarised_with_navigation_retries_counted(tmp_path):
    data = {"suites": [{"title": "demo-smoke.spec.ts", "specs": [], "suites": [{"title": "x", "specs": [
        {"title": "apex", "tests": [{"status": "expected", "results": [{"duration": 5000}], "annotations": [{"type": "navigation-retry", "description": "attempt 1 of 3 aborted: net::ERR_ABORTED | requestfailed: none reported"}]}]},
        {"title": "meridian", "tests": [{"status": "unexpected", "results": [{"duration": 2500}], "annotations": []}]}]}]}]}
    summary = demo_smoke.summarize_playwright(data, tmp_path)
    assert summary["passed"] == 1 and summary["failed"] == 1 and summary["navigation_retries"] == 1
    assert "ERR_ABORTED" in summary["navigation_retry_details"][0] and [t["seconds"] for t in summary["tests"]] == [5.0, 2.5]
