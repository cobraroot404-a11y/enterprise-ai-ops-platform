#!/usr/bin/env python
"""Git provenance check (specification Part 2 and Part 33): authorship, AI co-author trailers and assistant branding in commit messages, remotes.

    python scripts/provenance_check.py                  # report; exit 1 if a commit violates the rules and is NOT in the recorded exception list
    python scripts/provenance_check.py --write-baseline # record today's violations as known exceptions (it does not fix them; it only stops known ones from hiding new ones, and the owner decides what to do about them)

Rules checked for every commit reachable from HEAD: the author and committer name is the owner's (`Gautham`); the message has no co-author trailer and names no AI assistant or tool.
Known violations are listed in docs/planning/provenance-exceptions.json (defect PROV-01). They can only be removed by rewriting history, which the specification forbids without the
owner's decision and which would also move the protected tag, so this script never rewrites anything. A new violation fails the check and the test suite."""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "docs" / "planning" / "provenance-exceptions.json"
OWNER = "Gautham"
# the agent-configuration FILE names themselves (CLAUDE.md, the .claude/ directory) are not branding; every other mention still is
FILENAMES = re.compile(r"CLAUDE\.md|\.claude/", re.IGNORECASE)
BRANDING = re.compile(r"co-authored-by|generated with|\b(claude|anthropic|codex|chatgpt|openai|copilot|gemini)\b", re.IGNORECASE)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout


def violations() -> list[dict]:
    out = []
    for record in git("log", "--format=%H%x1f%an%x1f%cn%x1f%B%x1e").split("\x1e"):
        if not record.strip():
            continue
        sha, author, committer, body = record.strip("\n").split("\x1f")
        reasons = []
        if author != OWNER or committer != OWNER:
            reasons.append(f"author or committer is not {OWNER} ({author} / {committer})")
        hits = sorted({m.group(0).lower() for m in BRANDING.finditer(FILENAMES.sub("", body))})
        if hits:
            reasons.append("message contains: " + ", ".join(hits))
        if reasons:
            out.append({"commit": sha, "reasons": reasons})
    return out


def state() -> dict:
    found = violations()
    known = {e["commit"] for e in json.loads(BASELINE.read_text(encoding="utf-8"))["exceptions"]} if BASELINE.exists() else set()
    return {"commits": int(git("rev-list", "--count", "HEAD").strip()), "violations": found, "new": [v for v in found if v["commit"] not in known],
            "known": len([v for v in found if v["commit"] in known]), "remotes": [line for line in git("remote", "-v").splitlines() if line.strip()]}


def main() -> int:
    if "--write-baseline" in sys.argv:
        found = violations()
        BASELINE.write_text(json.dumps({"defect": "PROV-01", "note": "Known provenance violations in existing history. Recording them fixes nothing; removal needs the owner's decision "
                                                                      "(history rewrite, which also moves the protected tag).", "exceptions": found}, indent=1) + "\n", encoding="utf-8", newline="\n")
        print(f"recorded {len(found)} known violation(s)")
        return 0
    s = state()
    print(f"{s['commits']} commits; {len(s['violations'])} violate the provenance rules ({s['known']} recorded as PROV-01, {len(s['new'])} new); remotes: {len(s['remotes'])}")
    for v in s["new"]:
        print("NEW", v["commit"][:10], "; ".join(v["reasons"]))
    return 1 if s["new"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
