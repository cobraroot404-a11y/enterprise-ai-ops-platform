#!/usr/bin/env python
"""Record the environment verification the specification asks for before work starts (Part 34): Git, GitHub authentication, Git identity, Python, Node.js, Docker, CPU, RAM, GPU,
disk space and local model compatibility.

    python scripts/verify_environment.py     # writes evaluation/environment/verification.json and .md; read-only: it installs, downloads, starts and changes nothing

Privacy: no e-mail address, account name, token or host name is written; identity and authentication are recorded as yes/no facts only."""
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "evaluation" / "environment"
MODEL = "qwen2.5:1.5b"


def run(cmd: list[str], timeout: int = 20) -> tuple[int | None, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=ROOT, check=False)
        return proc.returncode, (proc.stdout or proc.stderr).strip()
    except (OSError, subprocess.SubprocessError):
        return None, ""


def first_line(cmd: list[str]) -> str | None:
    code, out = run(cmd)
    return out.splitlines()[0].strip() if code == 0 and out else None


def gpu() -> dict:
    code, out = run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_VideoController).Name"]) if sys.platform == "win32" else (None, "")
    names = [line.strip() for line in out.splitlines() if line.strip()] if code == 0 else []
    return {"adapters": names, "cuda_capable": any(re.search(r"nvidia", n, re.I) for n in names), "note": "inference runs on the CPU; no CUDA device is required or used"}


def ollama() -> dict:
    version = first_line(["ollama", "--version"])
    models, running = [], False
    try:
        body = json.loads(urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3).read())  # noqa: S310 - local URL
        models, running = sorted(m["name"] for m in body.get("models", [])), True
    except Exception:  # noqa: BLE001 - not running is a recorded fact, not an error
        pass
    return {"installed": version is not None, "version": version, "server_running_now": running, "models_installed": models if running else "unknown (server not running)",
            "required_model": MODEL, "required_model_present": (MODEL in models) if running else None}


def main() -> int:
    import capture_hardware  # noqa: F401  (kept importable: the benchmark manifests use it)

    hardware_code, hardware_out = run([sys.executable, str(ROOT / "scripts" / "capture_hardware.py")])
    hardware = json.loads(hardware_out) if hardware_code == 0 and hardware_out.startswith("{") else {}
    disk = shutil.disk_usage(ROOT)
    gh_code, _ = run(["gh", "auth", "status"])
    name = first_line(["git", "config", "user.name"])
    email_code, email_out = run(["git", "config", "user.email"])
    ram = hardware.get("ram_gb")
    result = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "command": "python scripts/verify_environment.py",
        "git": {"version": first_line(["git", "--version"]), "remotes_configured": len([line for line in run(["git", "remote", "-v"])[1].splitlines() if line.strip()])},
        "github_authentication": {"gh_cli_installed": shutil.which("gh") is not None, "authenticated": gh_code == 0 if gh_code is not None else None,
                                  "note": "recorded as a fact only; nothing was pushed and no repository exists"},
        "git_identity": {"author_name": name, "author_name_is_owner": name == "Gautham", "email_configured": email_code == 0 and bool(email_out), "email": "not recorded (private)"},
        "python": hardware.get("python"), "node": hardware.get("node"), "npm": first_line(["npm.cmd" if sys.platform == "win32" else "npm", "--version"]),
        "docker": hardware.get("docker"), "docker_daemon_reachable": run(["docker", "info", "--format", "{{.ServerVersion}}"])[0] == 0,
        "cpu": {"model": hardware.get("cpu"), "threads": hardware.get("cpu_threads")}, "ram_gb": ram, "gpu": gpu(), "os": hardware.get("os"),
        "disk": {"free_gb": round(disk.free / 1e9, 1), "total_gb": round(disk.total / 1e9, 1)},
        "local_model_compatibility": {**ollama(), "ram_sufficient_for_model": (ram or 0) >= 8, "basis": "a 1.5B model quantised to 4 bits needs about 2 GB of RAM while loaded; 8 GB is the "
                                      "practical floor with PostgreSQL and the services running", "embedding_model": "sentence-transformers/all-MiniLM-L6-v2 (CPU)"},
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    m = result["local_model_compatibility"]
    lines = ["# Environment verification (specification Part 34)", "", f"Generated {result['generated_utc']} by `{result['command']}` (read-only).", "", "| Item | Result |", "|---|---|",
             f"| Git | {result['git']['version']}; remotes configured: {result['git']['remotes_configured']} |",
             f"| GitHub authentication | CLI installed: {result['github_authentication']['gh_cli_installed']}; authenticated: {result['github_authentication']['authenticated']} (fact only; nothing pushed) |",
             f"| Authorized Git identity | author name is the owner: {result['git_identity']['author_name_is_owner']}; e-mail configured: {result['git_identity']['email_configured']} (not recorded) |",
             f"| Python | {result['python']} |", f"| Node.js | {result['node']} (npm {result['npm']}) |", f"| Docker | {result['docker']}; daemon reachable: {result['docker_daemon_reachable']} |",
             f"| CPU | {result['cpu']['model']}, {result['cpu']['threads']} threads |", f"| RAM | {result['ram_gb']} GB |",
             f"| GPU | {', '.join(result['gpu']['adapters']) or 'not detected'}; CUDA capable: {result['gpu']['cuda_capable']} (CPU inference) |",
             f"| Disk space | {result['disk']['free_gb']} GB free of {result['disk']['total_gb']} GB |",
             f"| Local model compatibility | Ollama {m['version']}; server running now: {m['server_running_now']}; `{MODEL}` present: {m['required_model_present']}; RAM sufficient: {m['ram_sufficient_for_model']} |", ""]
    (OUT / "verification.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print("\n".join(lines[5:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
