#!/usr/bin/env python
"""Gate B preparation: rebuild and run the platform from a CLEAN CHECKOUT with a CLEAN Python environment and CLEAN Node install, none of the author's local files.

    python scripts/clean_environment_check.py [--skip-containers]

What is clean: a `git clone --local` of the COMMITTED state (so no `.env`, no `.venv`, no `node_modules`, no `data/`, no uncommitted change; a dirty working tree is refused), a new virtual
environment populated from `backend/requirements-dev.txt`, `npm ci` from the lock file, a `.env` generated from `.env.example` with fresh random secrets, and the containerised stack built and
run from the clone with its own database volume (`scripts/container_smoke.py`).
What is NOT clean, stated in every report: it is the SAME machine, operating system user, Docker daemon, image cache and network as the author's, so this is NOT a fresh-machine reproduction and
does not replace an independent reviewer (Gate C). On Windows, run it with Python 3.10 or later and host pip 24.2 or later to download a pinned pip wheel using system certificate trust.
The check downloads dependencies from public registries and does not download a model.
The report goes to evaluation/clean-environment/<run id>/; the temporary clone is removed afterwards (only the directory this script created)."""
import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS_PIP = "26.2.1"


def run(cmd, cwd, timeout=3600, **kw):
    started = time.time()
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, **kw)
    return proc, round(time.time() - started, 1)


def folder_mb(path: Path) -> float:
    return round(sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1e6, 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-containers", action="store_true", help="skip the container build and smoke run (the slowest step)")
    ap.add_argument("--skip-lockfile", action="store_true", help="skip the separate exact installation of backend/requirements.lock.txt (a large download: it includes torch)")
    ap.add_argument("--skip-live", action="store_true", help="skip the host-process live checkpoint (own PostgreSQL container, API, worker, UI, REST, CSV, webhooks, recovery, backup, browser)")
    ap.add_argument("--ollama", action="store_true", help="run the container stack with the host's already running Ollama as the language model (nothing is downloaded)")
    ap.add_argument("--report-root", type=Path, default=ROOT / "evaluation" / "clean-environment",
                    help="directory for new run reports")
    args = ap.parse_args()
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    if dirty:
        print("refused: the working tree has uncommitted changes; a clean checkout would not contain them. Commit first.", file=sys.stderr)
        return 2
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir = args.report_root.resolve() / run_id
    outdir.mkdir(parents=True)
    work = Path(tempfile.mkdtemp(prefix="eaop-clean-"))
    clone, report = work / "repo", {"run_id": run_id, "head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
                                   "scope": "same machine, user, Docker daemon, image cache and network as the author: NOT a fresh-machine reproduction", "steps": [], "ok": False}
    python = None
    env = os.environ.copy()
    env.pop("SSLKEYLOGFILE", None)
    env["npm_config_cache"] = str(work / "npm-cache")
    env["npm_config_strict_ssl"] = "true"
    pip_options = ["--isolated", "--disable-pip-version-check", "--no-cache-dir"]
    if sys.platform == "win32":
        env["NODE_USE_SYSTEM_CA"] = "1"
    report["containers_requested"] = not args.skip_containers
    report["options"] = {"lockfile": not args.skip_lockfile, "live": not args.skip_live, "containers": not args.skip_containers, "ollama": args.ollama}

    def step(name, fn):
        started = time.time()
        try:
            detail = fn()
            report["steps"].append({"step": name, "ok": True, "seconds": round(time.time() - started, 1), "detail": detail or ""})
            print(f"ok   {name}", flush=True)
            return detail
        except Exception as exc:  # noqa: BLE001 - recorded; the run stops after cleanup
            report["steps"].append({"step": name, "ok": False, "seconds": round(time.time() - started, 1), "detail": str(exc)[:900]})
            print(f"FAIL {name}: {str(exc)[:300]}", flush=True)
            raise

    def need(proc, what):
        if proc.returncode != 0:
            raise RuntimeError(f"{what} exited {proc.returncode}: {(proc.stdout + proc.stderr)[-700:]}")
        return proc

    try:
        step("clone the committed state", lambda: need(run(["git", "clone", "--local", "--no-hardlinks", "--quiet", str(ROOT), str(clone)], work)[0], "git clone") and
             f"{sum(1 for _ in clone.rglob('*') if _.is_file() and '.git' not in _.parts)} files; .env present: {(clone / '.env').exists()}; node_modules present: {(clone / 'frontend' / 'node_modules').exists()}")
        assert not (clone / ".env").exists() and not (clone / ".venv").exists()
        venv = work / "venv"
        python = str(venv / ("Scripts" if sys.platform == "win32" else "bin") / "python")
        step("create a new virtual environment", lambda: need(run([sys.executable, "-m", "venv", str(venv)], work)[0], "venv") and sys.version.split()[0])
        if sys.platform == "win32":
            def bootstrap_pip(target=None):
                host = [sys.executable, "-m", "pip", *pip_options]
                version = need(run([*host, "--version"], work, env=env)[0], "host pip version").stdout
                match = re.match(r"pip (\d+)\.(\d+)", version)
                if sys.version_info < (3, 10) or not match or tuple(map(int, match.groups())) < (24, 2):
                    raise RuntimeError("Windows system trust bootstrap requires host Python 3.10+ and pip 24.2+")
                wheel_dir = work / "wheels"
                need(run([*host, "download", "--index-url", "https://pypi.org/simple", "--no-deps",
                          "--only-binary", ":all:", "--dest", str(wheel_dir), f"pip=={WINDOWS_PIP}"],
                         work, env=env)[0], "download pip wheel over HTTPS")
                wheel = wheel_dir / f"pip-{WINDOWS_PIP}-py3-none-any.whl"
                need(run([target or python, "-m", "pip", *pip_options, "install", "--no-index", "--no-deps", str(wheel)],
                         work, env=env)[0], "install pip wheel offline")
                return f"pip {WINDOWS_PIP} installed offline after download with {version.split(' from ')[0]}"

            step("bootstrap pip with Windows system trust", bootstrap_pip)
        step("install backend/requirements-dev.txt constrained by the lock file", lambda: need(run([python, "-m", "pip", *pip_options, "install", "--quiet",
                                                                      "--index-url", "https://pypi.org/simple", "-r", "backend/requirements-dev.txt", "-c", "backend/requirements.lock.txt"],
                                                                     clone, env=env)[0], "pip install") and f"venv size {folder_mb(venv)} MB")
        step("pip check", lambda: need(run([python, "-m", "pip", "check"], clone)[0], "pip check").stdout.strip())

        def pin_drift():
            frozen = {m.group(1).lower(): m.group(2) for m in re.finditer(r"^([A-Za-z0-9_.-]+)==(\S+)$", run([python, "-m", "pip", "freeze"], clone)[0].stdout, re.MULTILINE)}
            locked = {m.group(1).lower(): m.group(2) for m in re.finditer(r"^([A-Za-z0-9_.-]+)==(\S+)$", (clone / "backend" / "requirements.lock.txt").read_text(encoding="utf-8"), re.MULTILINE)}
            common = sorted(set(frozen) & set(locked))
            drift = {n: (frozen[n], locked[n]) for n in common if frozen[n] != locked[n]}
            report["pin_drift"] = drift
            report["dev_install_versions"] = {n: frozen[n] for n in common}
            if drift:
                raise RuntimeError(f"the constrained install differs from the lock file (installed, locked): {drift}")
            return f"{len(common)} packages are in both the clean install and the lock file; {len(drift)} resolved to a different version than the lock file (installed, locked): {dict(list(drift.items())[:8])}"
        step("compare the clean install with the lock file (version pinning)", pin_drift)
        if not args.skip_lockfile:
            lock_venv = work / "lock-venv"
            lock_python = str(lock_venv / ("Scripts" if sys.platform == "win32" else "bin") / "python")
            step("exact lock file: create a second virtual environment", lambda: need(run([sys.executable, "-m", "venv", str(lock_venv)], work)[0], "venv") and sys.version.split()[0])
            if sys.platform == "win32":
                step("exact lock file: bootstrap pip with Windows system trust", lambda: bootstrap_pip(lock_python))
            step("exact lock file: install backend/requirements.lock.txt", lambda: need(run([lock_python, "-m", "pip", *pip_options, "install", "--quiet", "--index-url", "https://pypi.org/simple",
                                                                                              "-r", "backend/requirements.lock.txt"], clone, timeout=3000, env=env)[0], "pip install (lock file)")
                 and f"venv size {folder_mb(lock_venv)} MB")
            step("exact lock file: pip check", lambda: need(run([lock_python, "-m", "pip", "check"], clone)[0], "pip check").stdout.strip())

            def exact():
                norm = lambda n: re.sub(r"[-_.]+", "-", n).lower()  # noqa: E731
                frozen = {norm(m.group(1)): m.group(2) for m in re.finditer(r"^([A-Za-z0-9_.-]+)==(\S+)$", run([lock_python, "-m", "pip", "freeze", "--all"], clone)[0].stdout, re.MULTILINE)}
                locked = {norm(m.group(1)): m.group(2) for m in re.finditer(r"^([A-Za-z0-9_.-]+)==(\S+)$", (clone / "backend" / "requirements.lock.txt").read_text(encoding="utf-8"), re.MULTILINE)}
                wrong = {n: (frozen.get(n), v) for n, v in locked.items() if frozen.get(n, "").split("+")[0] != v}
                extra = sorted(set(frozen) - set(locked) - {"pip", "setuptools", "wheel"})
                report["lockfile_exact"] = {"locked": len(locked), "mismatched": wrong, "installed_but_not_locked": extra, "versions": {n: frozen.get(n) for n in sorted(locked)}}
                if wrong:
                    raise RuntimeError(f"installed versions differ from the lock file (installed, locked): {wrong}")
                return f"all {len(locked)} locked packages installed at exactly the locked version; installed but not in the lock file: {extra or 'none'}"
            step("exact lock file: installed versions equal the lock file", exact)
            step("exact lock file: the application imports under the locked versions", lambda: need(run([lock_python, "-c", "import sys; sys.path.insert(0, 'backend'); import app.main, fastapi, psycopg, torch, sentence_transformers; print(fastapi.__version__, psycopg.__version__, torch.__version__)"], clone, timeout=600)[0], "import check").stdout.strip())
        env_text = (clone / ".env.example").read_text(encoding="utf-8")
        placeholders = set(re.findall(r"^\w+=(change-me[^\r\n]*)$", env_text, re.MULTILINE))
        replacements = {placeholder: secrets.token_urlsafe(24) for placeholder in placeholders}
        generated = re.sub(r"^(\w+)=(change-me[^\r\n]*)$",
                           lambda match: f"{match[1]}={replacements[match[2]]}", env_text, flags=re.MULTILINE)
        generated = re.sub(r"^POSTGRES_PORT=.*$", "POSTGRES_PORT=15432", generated, flags=re.MULTILINE)  # the live checkpoint's own PostgreSQL container, beside the author's on 5432
        step("generate .env from .env.example with fresh random secrets", lambda: (clone / ".env").write_text(generated, encoding="utf-8") and None)
        step("secret scan", lambda: need(run([python, "scripts/secret_scan.py"], clone)[0], "secret scan").stdout.strip().splitlines()[-1])
        step("documentation and structure tests from the clean checkout", lambda: need(run([python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_readme_results.py", "tests/test_ci_workflow.py", "tests/test_no_paid_services.py",
                                                                                           "tests/test_repository_structure.py", "tests/test_infrastructure_examples.py", "tests/test_review_package.py"], clone)[0], "pytest").stdout.strip().splitlines()[-1])
        step("npm ci from the lock file", lambda: need(run("npm ci --no-audit --no-fund", clone / "frontend", shell=True, env=env)[0], "npm ci") and f"node_modules {folder_mb(clone / 'frontend' / 'node_modules')} MB")
        step("frontend typecheck, lint and unit tests", lambda: need(run("npm run typecheck && npm run lint && npm test", clone / "frontend", shell=True, env=env)[0], "frontend checks").stdout.strip().splitlines()[-4:])
        if not args.skip_live:
            live_env = dict(env, COMPOSE_PROJECT_NAME=work.name + "-dev")

            def live():
                need(run(["docker", "compose", "up", "-d", "--wait"], clone, timeout=600, env=live_env)[0], "start the checkpoint's own PostgreSQL container")
                try:
                    proc = run([python, "scripts/demo.py", "smoke", "--ingestion", "--rest", "--compare", "--backup"], clone, timeout=1800, env=live_env)[0]
                    for produced in sorted((clone / "evaluation" / "demo-runs").glob("*/report.*"), key=lambda f: f.stat().st_mtime)[-2:]:
                        if produced.stat().st_mtime > started_at:
                            shutil.copy2(produced, outdir / f"live-demo-{produced.name}")
                    need(proc, "live demonstration checkpoint")
                    return (proc.stdout + proc.stderr).strip().splitlines()[-1]
                finally:
                    down = run(["docker", "compose", "down", "-v", "--remove-orphans"], clone, timeout=300, env=live_env)[0]
                    report["live_teardown"] = {"compose_down_exit": down.returncode, "project": live_env["COMPOSE_PROJECT_NAME"], "scope": "its own container, network and volume only"}
                    if down.returncode:
                        raise RuntimeError("the checkpoint's PostgreSQL project could not be removed: " + down.stderr[-300:])
            started_at = time.time()
            report["live_checkpoint"] = step("host processes from the clone on an isolated PostgreSQL container: both customers, ingestion with a simulated outage, REST, CSV, signed webhooks, "
                                             "recovery, comparison, backup and restore, browser", live)
        if not args.skip_containers:
            smoke_dir = clone / "evaluation" / "container-smoke"
            existing = set(smoke_dir.glob("*/report.json"))
            env["COMPOSE_PROJECT_NAME"] = work.name
            env["EAOP_APP_IMAGE_TAG"] = work.name
            env["EAOP_APP_API_PORT"] = "18000"
            env["EAOP_APP_UI_PORT"] = "18080"
            try:
                report["container_smoke"] = step(
                    "containerised stack built and run from the clone (own database volume, fresh secrets)",
                    lambda: need(run([python, "scripts/container_smoke.py", *(["--ollama"] if args.ollama else [])], clone, timeout=3000, env=env)[0],
                                 "container smoke").stdout.strip().splitlines()[-3:])
            finally:
                for produced in sorted(set(smoke_dir.glob("*/report.json")) - existing):
                    shutil.copy2(produced, outdir / "container-smoke-report.json")
                removed = run(["docker", "rmi", f"eaop-app-backend:{work.name}", f"eaop-app-ui:{work.name}"], work)[0]  # only this run's own uniquely tagged images
                report["container_images_removed"] = {"tags": [f"eaop-app-backend:{work.name}", f"eaop-app-ui:{work.name}"], "exit": removed.returncode}
        report["ok"] = True
    except Exception:  # noqa: BLE001
        report["ok"] = False
    finally:
        shutil.rmtree(work, ignore_errors=True)
        report["cleanup"] = f"{'could not remove' if work.exists() else 'removed'} {work.name} (the temporary directory this script created)"
        (outdir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8", newline="\n")
        lines = [f"# Clean-environment check {run_id}: {'PASSED' if report['ok'] else 'FAILED'}", "", f"Commit: `{report['head']}`. **Scope: {report['scope']}.**", "",
                 "| Step | Result | Seconds | Detail |", "|---|---|---|---|"]
        lines += [f"| {s['step']} | {'ok' if s['ok'] else 'FAILED'} | {s['seconds']} | {str(s['detail']).replace(chr(10), ' ')[:220]} |" for s in report["steps"]]
        lines += ["", f"Cleanup: {report['cleanup']}", ""]
        (outdir / "report.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
        print(f"report: {outdir / 'report.md'}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
