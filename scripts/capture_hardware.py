"""Capture hardware/software facts for benchmark manifests (stdlib only)."""
import datetime
import json
import os
import platform
import shutil
import subprocess
import sys


def _run(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)
        return (out.stdout or out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr) else None
    except (OSError, subprocess.SubprocessError):
        return None


def _ram_gb():
    try:
        if os.name == "nt":
            import ctypes

            class MemStatus(ctypes.Structure):
                _fields_ = [("l", ctypes.c_ulong), ("m", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                            ("a", ctypes.c_ulonglong), ("b", ctypes.c_ulonglong), ("c", ctypes.c_ulonglong),
                            ("d", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong), ("f", ctypes.c_ulonglong)]

            s = MemStatus()
            s.l = ctypes.sizeof(MemStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
            return round(s.total / 1024**3, 1)
        pages, size = os.sysconf("SC_PHYS_PAGES"), os.sysconf("SC_PAGE_SIZE")
        return round(pages * size / 1024**3, 1)
    except (OSError, ValueError, AttributeError):
        return None


def collect():
    return {
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "os": platform.platform(),
        "cpu": platform.processor(),
        "cpu_threads": os.cpu_count(),
        "ram_gb": _ram_gb(),
        "python": sys.version.split()[0],
        "docker": _run(["docker", "--version"]) if shutil.which("docker") else None,
        "ollama": _run(["ollama", "--version"]) if shutil.which("ollama") else None,
        "node": _run(["node", "--version"]) if shutil.which("node") else None,
    }


if __name__ == "__main__":
    print(json.dumps(collect(), indent=2))
