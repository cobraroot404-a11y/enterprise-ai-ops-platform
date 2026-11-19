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
    "docs/images/eaop-apex-connectors.png": "35a4280cdce18ddeb527de3421e5af264ca15c811c38a17e0b0440b7f64f30e3",
    "docs/images/eaop-apex-overview.png": "876d470f7ac729582ba5303f79b7f07d4f667fa95e584468df747facf894c42c",
    "docs/images/eaop-grounded-maintenance-answer.png": "6699e2a666a6346efd30b785911cad7ca09bb11321fb23d17282ce8921aa06a9",
    "docs/images/eaop-integration-health.png": "a11301bae5b3c631308f7be07c94633f400cc059eae56159325fcf98a5eab807",
    "docs/images/eaop-supervisor-approval-queue.png": "224d67db6328b712c572488c0ed5c3c6e10b520deee2358a8417e28367069974",
    "docs/images/eaop-ticket-audit-trail.png": "1f888a3e8f152bbf2db29bf837a59f45b64adebb1f676c978072712267078a4b",
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
