"""Check the tracked portfolio snapshot for private tooling and debug exports."""
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
INTERNAL_NAMES = {
    ".claude", ".codex", ".cursor", ".agents", ".windsurf", "claude.md",
    "agents.md", "gemini.md", "claude-code-workflow.md", "test_agent_context.py",
}
DEBUG_DIRS = {"artifacts", "playwright-report", "test-results", ".demo"}
DEBUG_SUFFIXES = {".zip", ".har", ".log", ".xml", ".webm", ".dump", ".png", ".jpg", ".jpeg", ".webp"}
MACHINE_PATH = re.compile(
    rb"(?i)[a-z]:(?:[/\\]+)Users(?:[/\\]+)[\w.-]+"
    rb"|(?:/home/|/Users/)(?!me(?:/|[\s\x22]|$))[\w.-]+(?=/)"
)


def main() -> int:
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    findings = []
    for name in tracked.decode("utf-8").split("\0"):
        if not name:
            continue
        path = PurePosixPath(name.casefold())
        if (set(path.parts) & (INTERNAL_NAMES | DEBUG_DIRS)
                or path.suffix in DEBUG_SUFFIXES
                or (path.name.startswith(".env") and path.name != ".env.example")):
            findings.append((name, "private tooling, environment or debug export"))
        if MACHINE_PATH.search((ROOT / name).read_bytes()):
            findings.append((name, "absolute local-machine path"))
    for name, reason in findings:
        print(f"{name}: {reason}")
    print(f"portfolio safety: {len(findings)} finding(s)")
    return bool(findings)


if __name__ == "__main__":
    sys.exit(main())
