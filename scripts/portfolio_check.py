"""Check the tracked portfolio snapshot for private tooling and debug exports."""
import hashlib
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
# Reviewed README screenshots of fictional demo data. Replacements require review.
README_SCREENSHOTS = {
    "docs/images/eaop-apex-connectors.png": "9a8cc5608756493e2459686273fac268610d787a92fbff1ce7a78bb76fe27261",
    "docs/images/eaop-apex-overview.png": "876d470f7ac729582ba5303f79b7f07d4f667fa95e584468df747facf894c42c",
    "docs/images/eaop-grounded-maintenance-answer.png": "a43c4bb6e91f8b5f75a7f540944f62c433509e5dd76c7eecc4f064de1422818b",
    "docs/images/eaop-integration-health.png": "6222934e2ac1a2348c869e89b5623a97f0e6e54d8896590807d5adce8106448c",
    "docs/images/eaop-supervisor-approval-queue.png": "fd8c5f14062161b7302b87911905c4e66a7ed6847fc4b551b03f7a207da1b117",
    "docs/images/eaop-ticket-audit-trail.png": "f95657778c5c5128eddaa0fba98cdd768529a9f49ee71315ca66ad2524c78d9c",
}
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
        content = (ROOT / name).read_bytes()
        expected_digest = README_SCREENSHOTS.get(name)
        reviewed = expected_digest is not None and hashlib.sha256(content).hexdigest() == expected_digest
        if (set(path.parts) & (INTERNAL_NAMES | DEBUG_DIRS)
                or (path.suffix in DEBUG_SUFFIXES and not reviewed)
                or (path.name.startswith(".env") and path.name != ".env.example")):
            findings.append((name, "private tooling, environment or debug export"))
        if MACHINE_PATH.search(content):
            findings.append((name, "absolute local-machine path"))
    for name, reason in findings:
        print(f"{name}: {reason}")
    print(f"portfolio safety: {len(findings)} finding(s)")
    return bool(findings)


if __name__ == "__main__":
    sys.exit(main())
