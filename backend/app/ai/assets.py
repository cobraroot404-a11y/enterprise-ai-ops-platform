"""Equipment ids literally written in a report.
Kept out of rules.py on purpose: that module is pinned byte-for-byte to the Phase 4 commit (tests/test_apex_compat)."""
import re

_ASSET_CANDIDATE = re.compile(r"\b[A-Za-z]{1,4}-\d{1,4}[A-Za-z]?\b")


def asset_candidates(report_text: str, pattern: str | None = None) -> list[str]:
    """Ids written in the report, upper-cased, in order of appearance, without duplicates.
    `pattern` is a tenant profile's own id pattern (its first group if it has one)."""
    regex = re.compile(pattern, re.IGNORECASE) if pattern else _ASSET_CANDIDATE
    seen: list[str] = []
    for match in regex.finditer(report_text):
        value = (match.group(1) if regex.groups else match.group(0)).upper()
        if value not in seen:
            seen.append(value)
    return seen
