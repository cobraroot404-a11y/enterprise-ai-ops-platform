"""Offline owner-session handoff for the deterministic Gate C checks on Windows."""

import argparse
import json
import os
import platform
import re
import secrets
import shutil
import socket
import stat
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime
from pathlib import Path

from gate_c_rls import CATALOG_SQL, evaluate_catalog


BRANCH = "feat/apex-vertical-slice"
TAG = "refs/tags/v4.1.0-local-rc1"
TAG_OBJECT = "454c28574aef1ae34231dab466a7ad916ff9055b"
DOCKER_PIPE = "npipe:////./pipe/dockerDesktopLinuxEngine"
IMAGE = "pgvector/pgvector:pg16"
DB_PORT = 15432
DEMO_PORTS = (5173, 8000, *range(8101, 8107))
E2E_PORTS = (*range(8210, 8216), 8220)
TRACK_2 = (
    "test_numeric_boundary_v7.py", "test_measurement_trust_v8.py",
    "test_provenance_closure_v8.py", "test_numeric_evidence.py", "test_numeric_safety.py",
)
NUMERIC_CRITERIA = {
    "Free-text and model-proposed numbers excluded from numeric priority": (
        "test_free_text_and_llm_values_are_unverified_candidates_and_never_drive_priority",
        "test_v5_v7_instruction_and_clean_text_alike_cannot_reach_numeric_priority",
    ),
    "Observation applicability and quarantine, including asset and time": (
        "test_the_v6_notation_case_and_wrong_asset_never_become_eligible",
        "test_forged_or_invalid_structured_records_are_quarantined",
        "test_structured_record_converts_units_and_marks_missing_timestamp_explicitly",
        "test_api_rejects_a_tenant_field_and_foreign_asset_records",
    ),
    "Simulation signature, scope and labelling": (
        "test_forged_or_unsigned_simulator_provenance_is_rejected",
        "test_valid_signed_simulation_is_eligible_labelled_and_audited",
        "test_signature_is_bound_to_tenant_and_observation",
    ),
    "Authorization and verification state transitions": (
        "test_unauthorized_roles_and_separation_of_duties",
        "test_cross_tenant_reviewer_cannot_touch_another_tenants_incident",
        "test_stale_wrong_and_duplicate_transitions",
        "test_concurrent_verification_has_exactly_one_winner",
    ),
    "Eligible observation and audited priority decision": (
        "test_no_eligible_observation_means_numeric_rules_do_not_execute_and_that_is_audited",
        "test_reviewer_approval_makes_the_observation_eligible_and_recomputes_priority",
        "test_priority_is_never_lowered_by_verification_and_ticket_flow_stays_gated",
    ),
    "Complete priority-decision provenance, including SAF8-A-040": (
        "test_saf8_a_040_missing_provenance_path_is_closed",
        "test_priority_decision_audit_is_complete_on_every_numeric_decision_path",
    ),
    "Preserved server-built origin and unavailable source, anti-forgery": (
        "test_absent_source_is_explicit_and_never_fabricated",
        "test_approval_preserves_the_original_envelope_and_records_reviewer_separately",
        "test_client_supplied_provenance_or_verification_fields_are_rejected_with_422",
        "test_llm_supplied_provenance_is_ignored",
    ),
}


def child_environment():
    # Inherit Windows and tool discovery settings. Do not inherit database,
    # Docker endpoint, inference, pytest, or evaluation overrides.
    names = {
        "APPDATA", "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)", "COMPUTERNAME",
        "COMSPEC", "DRIVERDATA", "LOCALAPPDATA", "NUMBER_OF_PROCESSORS", "OS", "PATH",
        "PATHEXT", "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER", "PROGRAMDATA",
        "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "SYSTEMDRIVE", "SYSTEMROOT",
        "TEMP", "TMP", "USERNAME", "USERPROFILE", "WINDIR",
    }
    env = {key: value for key, value in os.environ.items() if key.upper() in names}
    env.update(
        DOCKER_CONTEXT="desktop-linux", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
        GIT_TERMINAL_PROMPT="0", PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1",
        PIP_NO_INDEX="1", PIP_DISABLE_PIP_VERSION_CHECK="1", NPM_CONFIG_OFFLINE="true",
        NPM_CONFIG_AUDIT="false", NPM_CONFIG_FUND="false", PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD="1",
        HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", NO_PROXY="127.0.0.1,localhost",
    )
    return env


def run(args, cwd, env, timeout=600):
    # Child logs may contain credentials. Keep raw output out of the result
    # file and terminal. A temporary file also avoids pipe waits on descendants.
    with tempfile.TemporaryFile() as captured:
        try:
            result = subprocess.run(
                list(map(str, args)), cwd=cwd, env=env, stdout=captured,
                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, timeout=timeout,
            )
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = 124
        except OSError:
            code = 125
        captured.seek(0)
        return code, captured.read(8_000_000).decode("utf-8", errors="replace")


EXPECTED_SERVICES = frozenset({"ticketing", "inventory", "fleet", "crm", "servicedesk", "worker", "api", "ui"})
OPTIONAL_SERVICES = frozenset({"records"})  # Used by smoke --rest, not by demo up.
STATUS_PREFIX = re.compile(r"^\[demo [0-9]{2}:[0-9]{2}:[0-9]{2}\][ \t]+")
SERVICE_ROW = re.compile(r"([a-z0-9-]+)\s+pid\s+[1-9][0-9]*\s+(running|not running)")
HEALTH_ROW = re.compile(r"api health:\s*([0-9]{3}|None)\s+ui:\s*([0-9]{3}|None)")


def parse_demo_status(stdout, exit_code):
    services = {}
    http = {}
    errors = []
    no_demo = False
    for number, line in enumerate(stdout.splitlines(), 1):
        row = STATUS_PREFIX.sub("", line, count=1).strip()
        if not row:
            continue
        service = SERVICE_ROW.fullmatch(row)
        health = HEALTH_ROW.fullmatch(row)
        if service:
            name, state = service.groups()
            if name not in EXPECTED_SERVICES | OPTIONAL_SERVICES or name in services:
                errors.append(f"line {number}: unexpected or duplicate service identifier")
            else:
                services[name] = state
        elif health and not http:
            http = {name: None if code == "None" else int(code) for name, code in zip(("api", "ui"), health.groups(), strict=True)}
        elif row == "no demo run is recorded" and not no_demo:
            no_demo = True
        elif not row.startswith("run "):
            errors.append(f"line {number}: unrecognized or duplicate status row")

    missing = sorted(EXPECTED_SERVICES - services.keys())
    unhealthy = sorted(name for name, state in services.items() if state != "running")
    if no_demo and (services or http):
        errors.append("no-demo marker conflicts with service or HTTP rows")
    if not no_demo and not http:
        errors.append("missing API/UI health row")
    if exit_code != 0:
        disposition = "COMMAND_FAILED"
    elif errors:
        disposition = "PARSE_ERROR"
    elif no_demo:
        disposition = "NO_DEMO"
    elif missing or unhealthy or http != {"api": 200, "ui": 200}:
        disposition = "UNHEALTHY"
    else:
        disposition = "HEALTHY"
    return {
        "result": "PASS" if disposition == "HEALTHY" else "FAIL",
        "health_disposition": disposition,
        "services": services,
        "expected_services": sorted(EXPECTED_SERVICES),
        "missing_services": missing,
        "unhealthy_services": unhealthy,
        "http_health": http,
        "parse_errors": errors,
    }


def capture_demo_status(command, cwd, env, evidence, checkpoint, timeout=600):
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command, cwd=cwd, env={**env, "PYTHONIOENCODING": "utf-8"},
            capture_output=True, stdin=subprocess.DEVNULL, timeout=timeout, check=False,
        )
        stdout, stderr, code, error = completed.stdout, completed.stderr, completed.returncode, None
    except subprocess.TimeoutExpired as exc:
        stdout, stderr, code, error = exc.stdout or b"", exc.stderr or b"", None, "timeout"
    except OSError as exc:
        stdout, stderr, code, error = b"", b"", None, f"could not launch ({type(exc).__name__})"
    evidence.update(
        result="FAIL", health_disposition="NOT_PARSED",
        stdout=stdout.decode("utf-8", errors="backslashreplace"),
        stderr=stderr.decode("utf-8", errors="backslashreplace"),
        exit=code, capture_error=error, seconds=round(time.monotonic() - started, 1),
    )
    checkpoint()  # Keep the raw evidence even if parsing or a later step aborts.
    evidence.update(parse_demo_status(evidence["stdout"], evidence["exit"]))
    return evidence["result"] == "PASS"


def busy_ports(ports):
    busy = []
    for port in ports:
        with socket.socket() as probe:
            if os.name == "nt":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                busy.append(port)
    return busy


def write_configuration(root, project):
    stable = {"POSTGRES_DB": project, "POSTGRES_PORT": str(DB_PORT), "POSTGRES_USER": "gate_c_owner"}
    template = (root / ".env.example").read_text(encoding="utf-8")
    placeholders = set(re.findall(r"^\w+=(change-me[^\r\n]*)$", template, re.M))
    replacements = {key: secrets.token_hex(24) for key in placeholders}
    values = {}
    for line in template.splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = replacements.get(value, value)
    values.update(stable)
    values["MIGRATION_DATABASE_URL"] = (
        f"postgresql+psycopg://{stable['POSTGRES_USER']}:{values['POSTGRES_PASSWORD']}"
        f"@127.0.0.1:{DB_PORT}/{project}"
    )
    (root / ".env").write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
    return values


def junit(path):
    cases = []
    if path.is_file():
        for case in ET.parse(path).iter("testcase"):
            name = re.match(r"[A-Za-z0-9_]+", case.get("name", ""))
            if name:
                outcome = next((tag for tag in ("failure", "error", "skipped") if case.find(tag) is not None), "passed")
                cases.append((name.group(), outcome))
    return cases


def criteria(cases):
    results = {}
    for criterion, tests in NUMERIC_CRITERIA.items():
        observed = {name: [outcome for test, outcome in cases if test == name] for name in tests}
        if any(outcome in {"failure", "error"} for outcomes in observed.values() for outcome in outcomes):
            state = "FAIL"
        elif all(outcomes and set(outcomes) == {"passed"} for outcomes in observed.values()):
            state = "PASS"
        else:
            state = "NOT RUN"
        results[criterion] = {"result": state, "tests": {name: dict(Counter(items)) for name, items in observed.items()}}
    results["Answer-level citation, entity/model, absence, source conflict and component scope"] = {"result": "N/A", "reason": "No separate Track 2 acceptance case. These are addressed by broader grounding and AI-quality review."}
    return results


class Blocked(Exception):
    """A known stop reason containing only safe, fixed text."""


def retry_readonly_removal(remove, path, error):
    if os.name != "nt" or not isinstance(error[1], PermissionError):
        raise error[1]
    mode = os.lstat(path).st_mode
    if not stat.S_ISREG(mode) or mode & stat.S_IWRITE:
        raise error[1]
    os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    remove(path)


def review(report, scratch, env, source, dependency_source, checkpoint, *, rls_continuation=False):
    candidate = report["candidate"]
    steps = report["checks"]
    root = scratch / "checkout"
    project = "gatec_" + secrets.token_hex(6)
    env["COMPOSE_PROJECT_NAME"] = project
    compose = ["docker", "compose", "-p", project, "-f", "docker-compose.yml"]
    report["compose_project"] = project
    report["database_port"] = DB_PORT
    started = False
    e2e_busy = list(E2E_PORTS)

    def step(label, args, cwd=root, timeout=600):
        print(label, flush=True)
        start = time.monotonic()
        code, out = run(args, cwd, env, timeout)
        display_args = [str(arg).replace(str(scratch), "<scratch>").replace(str(source), "<local project>") for arg in args]
        steps[label] = {"result": "PASS" if code == 0 else "FAIL", "command": display_args, "exit": code, "seconds": round(time.monotonic() - start, 1)}
        return code, out

    def require(label, args, reason, cwd=root):
        code, out = step(label, args, cwd)
        if code:
            raise Blocked(reason)
        return out.strip()

    def pytest(label, args):
        xml = scratch / f"{label}.xml"
        code, _ = step(label, [python, "-m", "pytest", *args, "-q", f"--junitxml={xml}"], timeout=7200)
        cases = junit(xml)
        steps[label].update(counts=dict(Counter(outcome for _, outcome in cases)), failed_tests=[name for name, outcome in cases if outcome in {"failure", "error"}])
        if code == 0 and not any(outcome == "passed" for _, outcome in cases):
            steps[label]["result"] = "NOT RUN"
        return cases

    def psql(database, sql):
        return [*compose, "exec", "-T", "postgres", "psql", "-XAt", "-v", "ON_ERROR_STOP=1", "-U", "gate_c_owner", "-d", database, "-c", sql]

    try:
        if os.name != "nt" or not source.is_dir() or not dependency_source.is_dir():
            raise Blocked("Run on the Windows owner session with the local project checkout available.")
        endpoint = require("Docker Desktop local endpoint", ["docker", "context", "inspect", "desktop-linux", "--format", "{{.Endpoints.docker.Host}}"], "Docker Desktop desktop-linux context is unavailable.", scratch)
        if endpoint != DOCKER_PIPE:
            raise Blocked("Docker desktop-linux does not target the expected local named pipe.")
        server = require("Docker engine", ["docker", "info", "--format", "{{.ServerVersion}}"], "The owner session cannot access the Docker Desktop Linux engine.", scratch)
        image = require("Cached PostgreSQL 16 pgvector image", ["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"], f"Local image {IMAGE} is absent or inaccessible. The runner will not pull it.", scratch)
        report["docker_engine_version"] = server if re.fullmatch(r"[\w.+-]{1,40}", server) else None
        report["postgres_image_id"] = image if re.fullmatch(r"sha256:[a-f0-9]{64}", image) else None
        if busy := busy_ports((*DEMO_PORTS, DB_PORT)):
            report["unavailable_loopback_ports"] = busy
            raise Blocked("One or more required loopback ports are in use or unavailable.")

        python_source = dependency_source / ".venv"
        node_source = dependency_source / "frontend" / "node_modules"
        required_paths = [python_source / "Scripts/python.exe", node_source / ".package-lock.json", node_source / ".bin/playwright.cmd", node_source / ".bin/vite.cmd"]
        missing = [str(path.relative_to(dependency_source)) for path in required_paths if not path.is_file()]
        if missing:
            report["missing_local_artifacts"] = missing
            raise Blocked("Installed Python or lockfile-based Node artifacts are missing. No packages were installed.")
        browser_roots = [Path(os.environ.get(key, fallback)) for key, fallback in (("ProgramFiles(x86)", r"C:\Program Files (x86)"), ("ProgramFiles", r"C:\Program Files"), ("LOCALAPPDATA", r"C:\Windows\Temp"))]
        if not any((base / "Microsoft/Edge/Application/msedge.exe").is_file() for base in browser_roots):
            raise Blocked("Installed Microsoft Edge channel is missing.")
        chrome = any((base / "Google/Chrome/Application/chrome.exe").is_file() for base in browser_roots)
        npm = shutil.which("npm.cmd", path=env["PATH"])
        if not npm or not shutil.which("npx.cmd", path=env["PATH"]):
            raise Blocked("Installed Node 20+ with npm and npx is required.")
        node_version = require("Node runtime", ["node", "--version"], "Node is unavailable.", scratch)
        if not re.fullmatch(r"v\d+\.\d+\.\d+", node_version) or int(node_version.split(".")[0][1:]) < 20:
            raise Blocked("Node 20 or later is required.")
        report["node_version"] = node_version

        bundle = scratch / "candidate.bundle"
        require("Create a local bundle of candidate history", ["git", "bundle", "create", bundle, f"refs/heads/{BRANCH}", TAG], "Could not read candidate history or the protected tag from the local checkout.", source)
        require("Local scratch Git init", ["git", "init", "--quiet", "--template=", root], "Could not initialize the disposable checkout.", scratch)
        require("Import candidate history and protected tag into scratch", ["git", "fetch", "--no-tags", "--no-recurse-submodules", bundle, f"refs/heads/{BRANCH}", f"{TAG}:{TAG}"], "Could not read the local bundle. No remote was configured.")
        require("Exact candidate checkout", ["git", "-c", "core.longpaths=true", "checkout", "--quiet", "-b", BRANCH, candidate], "Could not check out the exact candidate.")
        for args, expected in ((["rev-parse", "HEAD"], candidate), (["rev-parse", TAG], TAG_OBJECT), (["branch", "--show-current"], BRANCH), (["remote"], ""), (["status", "--porcelain", "-uall"], "")):
            code, value = run(["git", *args], root, env)
            if code or value.strip() != expected:
                raise Blocked("Candidate, branch, tag, remotes or initial clean-tree verification failed.")
        steps["Candidate identity and initial clean tree"] = {"result": "PASS"}

        inputs = ("backend/requirements.txt", "backend/requirements-dev.txt", "backend/requirements.lock.txt", "frontend/package.json", "frontend/package-lock.json")
        for item in inputs:
            source_bytes = (dependency_source / item).read_bytes().replace(b"\r\n", b"\n")
            if source_bytes != (root / item).read_bytes().replace(b"\r\n", b"\n"):
                raise Blocked(f"Installed dependency source differs from the candidate's {item}.")
        hidden_lock = json.loads((node_source / ".package-lock.json").read_text(encoding="utf-8"))["packages"]
        candidate_lock = json.loads((root / "frontend/package-lock.json").read_text(encoding="utf-8"))["packages"]
        if any(key not in candidate_lock or entry.get("version") != candidate_lock[key].get("version") for key, entry in hidden_lock.items()):
            raise Blocked("Installed Node dependency metadata does not match frontend/package-lock.json.")
        print("Copying already-installed Python and Node dependencies locally", flush=True)
        # Copy both dependency trees so test caches and frontend builds cannot
        # write through a junction into the source checkout.
        shutil.copytree(python_source, root / ".venv", symlinks=True)
        shutil.copytree(node_source, root / "frontend/node_modules", symlinks=True)
        python = root / ".venv/Scripts/python.exe"
        env["PATH"] = str(python.parent) + os.pathsep + env["PATH"]
        env["E2E_PYTHON"] = str(python)
        env["NPM_CONFIG_CACHE"] = str(scratch / "npm-cache")
        process_temp = scratch / "process-temp"
        process_temp.mkdir()
        env.update(TEMP=str(process_temp), TMP=str(process_temp))
        for kind in ("user", "global"):
            config_path = scratch / f"npm-{kind}.ini"
            config_path.touch()
            env[f"NPM_CONFIG_{kind.upper()}CONFIG"] = str(config_path)
        python_version = require("Copied Windows Python", [python, "--version"], "The copied Python interpreter cannot start.")
        if not re.fullmatch(r"Python 3\.\d+\.\d+", python_version) or int(python_version.split(".")[1]) < 10:
            raise Blocked("Python 3.10 or later is required.")
        report["python_version"] = python_version
        require("Copied Python dependency consistency", [python, "-m", "pip", "check"], "The copied Python dependency set is inconsistent.")
        require("Copied frontend dependency consistency", [npm, "ls", "--depth=0", "--offline"], "The copied frontend dependency set is incomplete or inconsistent.", root / "frontend")
        require("Ignored configuration path", ["git", "check-ignore", ".env"], "The candidate does not ignore .env.")
        configuration = write_configuration(root, project)
        env.update(configuration)

        # Mark ownership only after verifying that the randomly chosen project
        # has no resources. Every potentially mutating Docker call uses it.
        def project_empty():
            label = f"label=com.docker.compose.project={project}"
            calls = (["ps", "-aq"], ["volume", "ls", "-q"], ["network", "ls", "-q"])
            checks = [run(["docker", *args, "--filter", label], root, env) for args in calls]
            return all(code == 0 and not out.strip() for code, out in checks)

        if not project_empty():
            raise Blocked("The unique Compose project could not be verified empty before startup.")
        started = True
        require("Start isolated PostgreSQL (cached image only)", [*compose, "up", "-d", "--wait", "--pull", "never", "postgres"], "The isolated PostgreSQL service did not become healthy.")
        ready = require("Verify PostgreSQL, pgvector and no shared eaop database", psql(project, "SELECT current_database(), extversion, NOT EXISTS (SELECT FROM pg_database WHERE datname='eaop') FROM pg_extension WHERE extname='vector'"), "PostgreSQL or pgvector verification failed.")
        match = re.fullmatch(re.escape(project) + r"\|([0-9.]+)\|t", ready)
        if not match:
            steps["Verify PostgreSQL, pgvector and no shared eaop database"]["result"] = "FAIL"
            raise Blocked("Database identity, installed pgvector or absence of shared eaop failed verification.")
        report["pgvector_version"] = match[1]
        report["shared_eaop_absent_from_review_cluster"] = True

        demo = [python, "scripts/demo.py"]
        code, out = step("Documented demo preflight", [*demo, "preflight"])
        steps["Documented demo preflight"]["checks"] = {
            name: "PASS" if status == "ok" else "FAIL"
            for status, name in re.findall(r"^\s*(ok|FAIL)\s+([A-Za-z0-9 _-]+):", out, re.M)
        }
        if code:
            raise Blocked("Documented demo preflight did not pass. No acceptance tracks were started.")

        if not rls_continuation:
            targeted = pytest("Track 2 numeric trust and corrective provenance", [f"backend/tests/{name}" for name in TRACK_2])
            report["v41_14_02"]["current_candidate"] = criteria(targeted)

        label = "Restricted-role and tenant authorization regression"
        cases = pytest(label, [
            "backend/tests/test_identity_security.py",
            "backend/tests/test_migration_0013_webhooks_and_csv.py",
            "backend/tests/test_security.py",
            "backend/tests/test_connector_egress.py",
            "backend/tests/test_webhooks.py",
        ])
        authorization_ok = steps[label]["result"] == "PASS" and bool(cases) and all(state == "passed" for _, state in cases)
        steps[label]["result"] = "PASS" if authorization_ok else "FAIL"
        checkpoint()
        if not authorization_ok:
            raise Blocked("Restricted-role authorization failed. The RLS gate and smoke were withheld.")

        code, _ = step("Interactive launcher startup readiness", [*demo, "up"])
        startup_ok = code == 0
        rls_ok = False
        if startup_ok:
            label = "Demo status and all recorded processes"
            print(label, flush=True)
            evidence = steps[label] = {"command": ["<scratch>/checkout/.venv/Scripts/python.exe", "scripts/demo.py", "status"]}
            startup_ok = capture_demo_status([*demo, "status"], root, env, evidence, checkpoint)
            if startup_ok:
                state = json.loads((root / ".demo/state.json").read_text(encoding="utf-8"))
                database = state.get("db_name", "")
                if not state.get("db_created") or not re.fullmatch(r"eaop_demo_[a-z0-9_]+", database):
                    raise Blocked("The launcher did not identify a task-owned demo database.")
                label = "RLS catalog and restricted app and worker roles"
                code, out = step(label, psql(database, CATALOG_SQL))
                steps[label].update(result="NOT RUN", disposition="NOT_PARSED", raw_catalog=out)
                checkpoint()
                match = evaluate_catalog(out, code)
                steps[label].update(match)
                rls_ok = match["result"] == "PASS"
                checkpoint()
        down, _ = step("Documented demo down after startup", [*demo, "down"])
        if down or (root / ".demo/state.json").exists():
            raise Blocked("Interactive launcher cleanup did not complete. Other runtime paths were stopped.")

        if startup_ok and rls_ok:
            step("Gate C live smoke", [*demo, "smoke", "--ingestion", "--rest", "--compare", "--backup"], timeout=1800)
            reports = list((root / "evaluation/demo-runs").glob("*/report.json"))
            if reports:
                raw = json.loads(max(reports, key=lambda path: path.stat().st_mtime_ns).read_text(encoding="utf-8"))
                if raw.get("git_head") == candidate and raw.get("mode") == "smoke":
                    steps["Gate C live smoke"]["completed_subreports"] = {
                        name: "PASS" if name in raw else "NOT RUN"
                        for name in ("workflows", "ingestion", "rest", "integrations", "comparison", "browser", "backup")
                    }
                    steps["Gate C live smoke"]["smoke_success"] = raw.get("success") is True
                    backup = raw.get("backup", {})
                    steps["Gate C live smoke"]["restore_check_counts"] = dict(Counter("PASS" if check.get("ok") is True else "FAIL" for check in backup.get("checks", [])))
            if (root / ".demo/state.json").exists():
                raise Blocked("Smoke left owned state behind. Further runtime paths were stopped for cleanup.")
        else:
            steps["Gate C live smoke"] = {"result": "NOT RUN", "reason": "Startup, RLS catalog, or restricted-role authorization did not pass."}

        if rls_continuation:
            return

        apex = "backend/tests/test_apex_compat.py"
        code, collected = step("Apex compatibility collection", [python, "-m", "pytest", "--collect-only", "-q", apex])
        count = re.search(r"^4 tests collected\b", collected, re.M)
        steps["Apex compatibility collection"].update(
            result="PASS" if code == 0 and count else "FAIL",
            collected=4 if count else None,
        )
        pytest("Apex compatibility tests", [apex])
        pytest("Gate C status parser tests", ["tests/test_gate_c_owner_runner.py"])
        pytest("Backend regression", ["backend/tests"])
        pytest("Root regression (disruptive opt-in unset)", ["tests"])
        for args in (["run", "typecheck"], ["run", "lint"], ["test"]):
            code, _ = step("Frontend npm " + " ".join(args), [npm, *args], root / "frontend")
            if code:
                break
        e2e_busy = busy_ports(E2E_PORTS)
        for channel in ("msedge", "chrome"):
            if e2e_busy:
                steps[f"Automated accessibility {channel}"] = {"result": "NOT RUN", "reason": "Required Playwright ports unavailable.", "ports": e2e_busy}
                continue
            if channel == "chrome" and not chrome:
                steps["Automated accessibility chrome"] = {"result": "NOT RUN", "reason": "Installed Chrome channel unavailable."}
                break
            env["E2E_BROWSER_CHANNEL"] = channel
            code, _ = step(f"Automated accessibility {channel}", [root / "frontend/node_modules/.bin/playwright.cmd", "test", "e2e/accessibility.spec.ts"], root / "frontend", timeout=1800)
            if code:
                break
        env.pop("E2E_BROWSER_CHANNEL", None)

        for label, script, pattern in (
            ("Secret scan", "scripts/secret_scan.py", r"secret scan: \d+ finding\(s\) in \d+ files"),
            ("Git provenance scan", "scripts/provenance_check.py", r"\d+ commits; \d+ violate the provenance rules \(\d+ recorded as PROV-01, \d+ new\); remotes: \d+"),
        ):
            _, out = step(label, [python, script])
            match = re.search(pattern, out)
            if match:
                steps[label]["summary"] = match[0]
        step("Frozen evidence unchanged", ["git", "diff", "--exit-code", "HEAD", "--", "evaluation/datasets", "evaluation/reports/safety", "evaluation/safety"])
    finally:
        if started:
            state_file = root / ".demo/state.json"
            if state_file.exists():
                step("Documented demo down during cleanup", [python, "scripts/demo.py", "down"])
            code, remaining = step("Check review cluster for leftover demo databases", psql("postgres", "SELECT count(*) FROM pg_database WHERE datname LIKE 'eaop_demo_%'"))
            steps["Check review cluster for leftover demo databases"]["result"] = "PASS" if code == 0 and remaining.strip() == "0" else "FAIL"
            down, _ = step("Remove only the review Compose project and volume", [*compose, "down", "-v", "--remove-orphans"])
            residual_ports = []
            observed_ports = (*DEMO_PORTS, DB_PORT, *(port for port in E2E_PORTS if port not in e2e_busy))
            for port in observed_ports:
                with socket.socket() as client:
                    client.settimeout(0.25)
                    if client.connect_ex(("127.0.0.1", port)) == 0:
                        residual_ports.append(port)
            report["cleanup"] = {
                "project_removed": down == 0 and project_empty(),
                "demo_state_removed": not state_file.exists(),
                "ports_still_listening": residual_ports,
            }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, help="Exact 40-character commit SHA on the candidate branch")
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1], help="Local candidate Git repository")
    parser.add_argument("--dependency-source", type=Path, help="Local checkout with installed dependencies (defaults to --source)")
    parser.add_argument("--output", type=Path, required=True, help="New JSON evidence file for this run")
    parser.add_argument("--rls-continuation", action="store_true", help="Revalidate startup, RLS and authorization before live smoke, without repeating the completed suites")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[0-9a-f]{40}", args.candidate):
        parser.error("--candidate must be a full lowercase commit SHA")
    source = args.source.resolve()
    dependency_source = (args.dependency_source or source).resolve()
    output = args.output.resolve()
    try:
        with output.open("x", encoding="utf-8") as reserved:
            json.dump({"candidate": args.candidate, "owner_handoff_state": "STARTING"}, reserved)
    except OSError as exc:
        parser.error(f"could not reserve a new evidence file: {exc}")

    def checkpoint():
        temporary = output.with_suffix(f".{secrets.token_hex(4)}.tmp")
        try:
            temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)

    report = {
        "review_type": "OWNER-CONDUCTED CLEAN-ROOM GATE C REVIEW",
        "candidate": args.candidate, "branch": BRANCH, "host_os": platform.release(),
        "started_local": datetime.now().astimezone().isoformat(timespec="seconds"),
        "scope": "Installed dependencies copied locally. No downloads, real inference, or shared database access.",
        "checks": {},
        "v41_14_02": {"frozen": "FAIL, complete provenance 63/64, SAF8-A-040", "current_candidate": criteria([])},
        "not_run_by_runner": {
            "Container smoke": "The documented command unconditionally rebuilds python:3.12-slim and nginx:alpine derivatives and may fetch their layers or requirements.txt packages constrained by requirements.lock.txt.",
            "Manual scenarios, manual refusals and keyboard/screen-reader review": "These are reviewer observations. Automated smoke and suite results have their own entries.",
            "Track 3": "Fresh independent labels and owner-authorized inference are required.",
        },
        "cleanup": {"project_created": False},
    }
    scratch = Path(tempfile.mkdtemp(prefix="eaop-gc-"))
    try:
        report["rls_continuation"] = args.rls_continuation
        review(report, scratch, child_environment(), source, dependency_source, checkpoint,
               rls_continuation=args.rls_continuation)
    except Blocked as exc:
        report["stopped"] = str(exc)
    except (Exception, KeyboardInterrupt) as exc:
        report["stopped"] = f"Runner stopped ({type(exc).__name__}). Check the last recorded stage. See the status evidence when available."
    finally:
        try:
            resolved = scratch.resolve(strict=True)
            if resolved.parent != Path(tempfile.gettempdir()).resolve() or not resolved.name.startswith("eaop-gc-"):
                raise OSError("Unexpected scratch path")
            # Remove credentials even when a locked build artifact prevents full cleanup.
            (resolved / "checkout/.env").unlink(missing_ok=True)
            shutil.rmtree(resolved, onerror=retry_readonly_removal)
            report["cleanup"]["scratch_removed"] = True
        except OSError:
            report["cleanup"]["scratch_removed"] = False
            report["cleanup"]["scratch_directory_name"] = scratch.name
    report["owner_handoff_state"] = "RESULTS FOR REVIEW" if "stopped" not in report else "STOPPED"
    report["finished_local"] = datetime.now().astimezone().isoformat(timespec="seconds")
    checkpoint()
    print(f"Result file: {output}", flush=True)
    cleanup = report["cleanup"]
    clean = cleanup["scratch_removed"] and cleanup.get("project_removed", True) and cleanup.get("demo_state_removed", True) and not cleanup.get("ports_still_listening")
    return 0 if clean and "stopped" not in report and all(check["result"] != "FAIL" for check in report["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
