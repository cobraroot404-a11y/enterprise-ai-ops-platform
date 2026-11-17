"""Cross-platform task runner mirroring the Makefile (for machines without make).

Usage: python scripts/dev.py <task>
Tasks: up down db-check hardware lint test migrate seed seed-uitest onboard-meridian api ticketing inventory
       fleet crm servicedesk records worker stack
"""
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
DB_QUERY = "select extname from pg_extension order by 1"

PROCESSES = {
    "api": [PY, "-m", "uvicorn", "app.main:create_app", "--factory", "--app-dir", "backend", "--port", "8000"],
    "ticketing": [PY, "-m", "uvicorn", "ticketing_app:app", "--app-dir", "mock-services/ticketing",
                  "--port", "8101"],
    "inventory": [PY, "-m", "uvicorn", "inventory_app:app", "--app-dir", "mock-services/inventory",
                  "--port", "8102"],
    "fleet": [PY, "-m", "uvicorn", "fleet_app:app", "--app-dir", "mock-services/fleet", "--port", "8103"],
    "crm": [PY, "-m", "uvicorn", "crm_app:app", "--app-dir", "mock-services/crm", "--port", "8104"],
    "servicedesk": [PY, "-m", "uvicorn", "servicedesk_app:app", "--app-dir", "mock-services/servicedesk",
                    "--port", "8105"],
    "records": [PY, "-m", "uvicorn", "records_app:app", "--app-dir", "mock-services/records", "--port", "8106"],
    "worker": [PY, "workers/run_worker.py"],
}

TASKS = {
    "up": [["docker", "compose", "up", "-d", "--wait"]],
    "down": [["docker", "compose", "down"]],
    "db-check": [[
        "docker", "compose", "exec", "-T", "postgres", "sh", "-c",
        'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "' + DB_QUERY + '"',
    ]],
    "hardware": [[PY, "scripts/capture_hardware.py"]],
    "lint": [[PY, "-m", "ruff", "check", "scripts", "tests", "backend", "workers", "mock-services"]],
    "test": [[PY, "-m", "pytest", "-q"]],
    "migrate": [[PY, "scripts/migrate.py"]],
    "seed": [[PY, "scripts/seed_apex.py"]],
    "seed-uitest": [[PY, "scripts/seed_uitest.py"]],  # development-only fixture; needs UITEST_PASSWORD
    # Onboards the fictional Meridian customer through the public API (the stack must be running).
    # Needs ONBOARD_PASSWORD and PLATFORM_ADMIN_EMAIL / PLATFORM_ADMIN_PASSWORD in the environment.
    "onboard-meridian": [[PY, "scripts/onboard_tenant.py", "onboarding/meridian.json"]],
    "ollama-start": [[PY, "scripts/ollama_ctl.py", "start"]],
    "ollama-stop": [[PY, "scripts/ollama_ctl.py", "stop"]],
}


def load_env() -> None:
    path = ROOT / ".env"
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            if raw.strip() and not raw.startswith("#") and "=" in raw:
                key, _, value = raw.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


def stack() -> int:
    """Start API, worker and both mock services; stop them all on Ctrl-C."""
    procs = {name: subprocess.Popen(cmd, cwd=ROOT) for name, cmd in PROCESSES.items()}
    print("Stack running: API http://127.0.0.1:8000/docs, ticketing :8101, inventory :8102, fleet :8103, "
          "crm :8104, service desk :8105, records :8106. Ctrl-C to stop.")
    try:
        while all(p.poll() is None for p in procs.values()):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs.values():
            p.terminate()
    return 0


def main(argv: list[str]) -> int:
    load_env()
    task = argv[1] if len(argv) == 2 else None
    if task == "stack":
        return stack()
    if task in PROCESSES:
        return subprocess.run(PROCESSES[task], cwd=ROOT, check=False).returncode
    if task not in TASKS:
        print(__doc__)
        return 2
    for cmd in TASKS[task]:
        rc = subprocess.run(cmd, cwd=ROOT, check=False).returncode
        if rc:
            return rc
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
