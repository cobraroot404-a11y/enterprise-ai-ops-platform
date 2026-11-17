"""Repository and test-artifact secret scan (free, no dependencies, never prints a secret value).

  python scripts/secret_scan.py [--root DIR] [--env-file .env]

Checks every tracked or untracked-but-not-ignored file, plus test artifacts and reports even if git-ignored:
  1. KNOWN VALUES: the real secret values in the local .env (any key containing PASSWORD, SECRET, KEY or TOKEN) must not
     appear in any scanned file, including logs, screenshots (raw bytes), JSON reports and junit files.
  2. PATTERNS: private-key blocks, cloud and VCS tokens, JWT-shaped strings, and long literal credentials assigned in code.
Known test-only constants and obvious placeholders are allowed. Findings are reported as `path: rule`; values are never shown.
Exit status 1 when anything is found.
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SENSITIVE_KEY = re.compile(r"(PASSWORD|SECRET|KEY|TOKEN)", re.IGNORECASE)
PLACEHOLDER = re.compile(r"(change-?me|example|placeholder|your[-_ ]|xxxx|<.*>)", re.IGNORECASE)
TEST_CONSTANTS = {"E2e-Test-Passw0rd!", "Test-Passw0rd!", "e2e-ticketing-key", "e2e-servicedesk-key", "test-ticketing-key",
                  "test-servicedesk-key", "test-secret-not-for-production-0123456789"}
ARTIFACT_DIRS = ["frontend/test-results", "frontend/playwright-report", "evaluation", "docs"]
SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", "dist", ".pytest_cache", ".ruff_cache"}
MAX_BYTES = 8 * 1024 * 1024
TEST_FIXTURE_PATHS = ("backend/tests/", "tests/", "frontend/e2e/", "frontend/src/test/")
PATTERNS = {
    "private key block": re.compile(rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"),
    "AWS access key id": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "Slack token": re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    "JWT-shaped token": re.compile(rb"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "literal credential assignment": re.compile(
        rb"""(?i)\b(?:api[_-]?key|secret|passw(?:or)?d|token)["']?\s*[:=]\s*["']([^"'\s]{16,})["']"""),
}


def env_secrets(env_file: Path) -> dict[str, bytes]:
    found: dict[str, bytes] = {}
    if not env_file.exists():
        return found
    for raw in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if SENSITIVE_KEY.search(key) and len(value) >= 8 and not PLACEHOLDER.search(value) and value not in TEST_CONSTANTS:
            found[key] = value.encode()
    return found


def candidate_files(root: Path) -> list[Path]:
    files: set[Path] = set()
    if (root / ".git").exists():
        for args in (["ls-files"], ["ls-files", "-o", "--exclude-standard"]):
            out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False).stdout
            files.update(root / line for line in out.splitlines() if line)
    else:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            files.update(Path(dirpath) / f for f in filenames)
    for rel in ARTIFACT_DIRS:  # artifacts are scanned even when git-ignored
        base = root / rel
        if base.is_dir():
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
                files.update(Path(dirpath) / f for f in filenames)
    return sorted(f for f in files if f.is_file() and not any(part in SKIP_DIRS for part in f.parts))


def allowed_literal(match: re.Match) -> bool:
    value = match.group(1).decode(errors="ignore")
    return value in TEST_CONSTANTS or bool(PLACEHOLDER.search(value)) or value.startswith(("os.environ", "settings.", "env."))


def scan(root: Path, env_file: Path | None = None) -> list[tuple[str, str]]:
    secrets = env_secrets(env_file if env_file is not None else root / ".env")
    findings: list[tuple[str, str]] = []
    for path in candidate_files(root):
        if path.name == ".env" or path.stat().st_size > MAX_BYTES:
            continue
        data = path.read_bytes()
        rel = path.relative_to(root).as_posix()
        for key, value in secrets.items():
            if value in data:
                findings.append((rel, f"contains the value of {key} from .env"))
        if rel.endswith((".png", ".jpg", ".zip", ".woff2")):
            continue
        for rule, pattern in PATTERNS.items():
            for m in pattern.finditer(data):
                if rule == "literal credential assignment" and (allowed_literal(m) or rel.startswith(TEST_FIXTURE_PATHS)):
                    continue  # synthetic passwords in test fixtures are allowed; real .env values are checked separately above
                if rule == "JWT-shaped token" and rel.startswith(("frontend/src/", "backend/tests/")):
                    continue  # unit tests build synthetic tokens
                findings.append((rel, rule))
                break
    return findings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--env-file", default=None)
    args = ap.parse_args()
    root = Path(args.root).resolve()
    findings = scan(root, Path(args.env_file) if args.env_file else None)
    for rel, rule in findings:
        print(f"{rel}: {rule}")
    print(f"secret scan: {len(findings)} finding(s) in {len(candidate_files(root))} files")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
