"""Start, stop or check the local Ollama server without touching PATH or installed models.

Usage: python scripts/ollama_ctl.py <start|stop|status>
  start   launch `ollama serve` (detached) if it is not already answering, wait until ready
  stop    stop the Ollama tray app, server and model runner processes (does not uninstall anything)
  status  print server version, loaded model and memory use
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").replace("localhost", "127.0.0.1")


def find_exe() -> str | None:
    candidates = [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"]
    for c in candidates:
        if c.exists():
            return str(c)
    return shutil.which("ollama")


def get(path: str, timeout: float = 3.0):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as resp:  # noqa: S310 - local URL
        return json.loads(resp.read())


def is_up() -> bool:
    try:
        get("/api/version")
        return True
    except (OSError, ValueError):
        return False


def start(timeout: float = 60.0) -> bool:
    if is_up():
        return True
    exe = find_exe()
    if not exe:
        print("Ollama is not installed (see docs/operations/real-ai-setup-windows.md)")
        return False
    flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     stdin=subprocess.DEVNULL, creationflags=flags, close_fds=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_up():
            return True
        time.sleep(0.5)
    return False


def stop() -> None:
    if os.name == "nt":
        for name in ("ollama app.exe", "ollama.exe", "llama-server.exe"):
            subprocess.run(["taskkill", "/F", "/IM", name], capture_output=True, check=False)
    else:
        subprocess.run(["pkill", "-f", "ollama"], capture_output=True, check=False)
    time.sleep(1)


def status() -> None:
    if not is_up():
        print("Ollama: not running")
        return
    print("Ollama:", get("/api/version").get("version"))
    for m in get("/api/ps").get("models", []):
        print(f"  loaded: {m['name']} ({m.get('size', 0) / 1e6:.0f} MB, expires {m.get('expires_at')})")


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in ("start", "stop", "status"):
        print(__doc__)
        return 2
    if argv[1] == "start":
        ok = start()
        print("Ollama ready" if ok else "Ollama did not become ready")
        return 0 if ok else 1
    if argv[1] == "stop":
        stop()
        print("Ollama stopped" if not is_up() else "Ollama still answering")
        return 0 if not is_up() else 1
    status()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
