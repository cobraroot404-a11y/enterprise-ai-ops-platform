import json
import sys

import demo
import gate_c_owner_runner as runner
import pytest

SERVICES = ("ticketing", "inventory", "fleet", "crm", "servicedesk", "worker", "api", "ui")


def status_output(*, remove=None, stopped=None, api=200, ui=200):
    rows = [
        f"[demo 09:24:{index:02}]   {name:12} pid {1000 + index:6} {'not running' if name == stopped else 'running'}"
        for index, name in enumerate(SERVICES)
        if name != remove
    ]
    return "\r\n".join([
        "[demo 09:23:59] run regression was recorded earlier (phase running; its launcher is no longer running); "
        "database eaop_demo_regression (created by this run: True)",
        *rows,
        f"[demo 09:24:59]   api health: {api}   ui: {ui}",
    ]) + "\r\n"


def test_timestamped_rows_parse_by_exact_service_identifier():
    status = runner.parse_demo_status(status_output(), 0)
    assert status["result"] == "PASS"
    assert status["health_disposition"] == "HEALTHY"
    assert status["expected_services"] == sorted(SERVICES)
    assert status["services"] == dict.fromkeys(SERVICES, "running")
    assert status["http_health"] == {"api": 200, "ui": 200}


def test_missing_service_fails_even_with_eight_running_rows():
    stdout = status_output(remove="worker") + "[demo 09:25:00] records pid 1234 running\n"
    status = runner.parse_demo_status(stdout, 0)
    assert status["health_disposition"] == "UNHEALTHY"
    assert status["missing_services"] == ["worker"]
    assert status["unhealthy_services"] == []
    assert len(status["services"]) == 8


def test_stopped_service_fails():
    status = runner.parse_demo_status(status_output(stopped="inventory"), 0)
    assert status["health_disposition"] == "UNHEALTHY"
    assert status["unhealthy_services"] == ["inventory"]
    assert status["services"]["inventory"] == "not running"


def test_failed_http_probe_fails_with_live_processes():
    status = runner.parse_demo_status(status_output(api=503, ui=None), 0)
    assert status["health_disposition"] == "UNHEALTHY"
    assert not status["unhealthy_services"]
    assert status["http_health"] == {"api": 503, "ui": None}


@pytest.mark.parametrize("stdout", [
    status_output().replace("pid   1000", "pid    NaN"),
    status_output() + "[demo 09:25:00] api pid 1234 running\n",
    "",
])
def test_invalid_status_output_is_a_parse_error(stdout):
    status = runner.parse_demo_status(stdout, 0)
    assert status["result"] == "FAIL"
    assert status["health_disposition"] == "PARSE_ERROR"
    assert status["parse_errors"]


def test_no_run_is_distinct_from_parse_error():
    status = runner.parse_demo_status("[demo 06:03:20] no demo run is recorded\n", 0)
    assert status["health_disposition"] == "NO_DEMO"
    assert status["missing_services"] == sorted(SERVICES)
    assert status["parse_errors"] == []


def test_capture_retains_both_streams_and_exit_before_parsing(tmp_path, monkeypatch):
    stdout = status_output()
    stderr = "status diagnostic\r\n"
    code = 9
    command = [
        sys.executable, "-c",
        f"import sys; sys.stdout.buffer.write({stdout.encode()!r}); "
        f"sys.stderr.buffer.write({stderr.encode()!r}); sys.exit({code})",
    ]
    evidence = {}
    checkpoint_path = tmp_path / "raw-status.json"
    parse = runner.parse_demo_status

    def checkpoint():
        checkpoint_path.write_text(json.dumps(evidence), encoding="utf-8")

    def parse_after_checkpoint(raw_stdout, exit_code):
        pending = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        assert pending["health_disposition"] == "NOT_PARSED"
        assert pending["stdout"] == raw_stdout == stdout
        assert pending["stderr"] == stderr
        assert pending["exit"] == exit_code == code
        return parse(raw_stdout, exit_code)

    monkeypatch.setattr(runner, "parse_demo_status", parse_after_checkpoint)
    assert not runner.capture_demo_status(command, tmp_path, runner.child_environment(), evidence, checkpoint)
    assert evidence["health_disposition"] == "COMMAND_FAILED"
    assert evidence["parse_errors"] == []
    assert evidence["services"] == dict.fromkeys(SERVICES, "running")


def test_actual_launcher_status_format_with_simulated_state(capsys, monkeypatch):
    state = {
        "run_id": "format-test",
        "db_name": "eaop_demo_format_test",
        "db_created": True,
        "ports": demo.PORTS,
        "processes": [
            {"name": name, "pid": pid, "created": 1}
            for pid, name in enumerate(SERVICES, 1000)
        ],
    }
    monkeypatch.setattr(demo, "load_state", lambda: state)
    monkeypatch.setattr(demo, "launcher_alive", lambda _: False)
    monkeypatch.setattr(demo, "process_info", lambda _: {"created": 1})
    monkeypatch.setattr(demo, "http_status", lambda _: 200)
    exit_code = demo.main(["status"])
    captured = capsys.readouterr()
    assert captured.err == ""
    status = runner.parse_demo_status(captured.out, exit_code)
    assert status["health_disposition"] == "HEALTHY"
    assert status["services"] == dict.fromkeys(SERVICES, "running")
