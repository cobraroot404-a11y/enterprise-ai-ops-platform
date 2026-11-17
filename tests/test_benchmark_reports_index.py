"""P4L241 / P34L1347: the benchmark index names only artifacts and scripts that exist, and cites every Priority 3 item."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "docs" / "performance" / "benchmark-reports-index.md"


def test_index_covers_all_six_priority_3_items_and_every_cited_path_exists():
    text = INDEX.read_text(encoding="utf-8")
    for item in ("Automated tests", "Customer acceptance tests", "Retrieval evaluation", "Workflow benchmarks", "Failure recovery reports", "Reproducible results"):
        assert f"| {item} |" in text
    paths = {p for p in re.findall(r"`([A-Za-z0-9_./-]+\.(?:json|md|py))`", text) if "/" in p}
    paths |= {p for p in re.findall(r"`([A-Za-z0-9_./-]+/)`", text)}
    assert len(paths) >= 8
    missing = [p for p in sorted(paths) if not (ROOT / p).exists()]
    assert missing == []
    assert "same-author" in text and "NOT MET" in text
