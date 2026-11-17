"""Reconcile the V4.1 specification extract with the internal requirement catalogue (see docs/specification/README.md).

    python scripts/spec_reconcile.py

With no extract present the script reports specification completeness as UNVERIFIED and exits 0; it never invents requirements.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs" / "specification"
sys.path.insert(0, str(Path(__file__).parent))
from traceability_data import REQUIREMENTS  # noqa: E402


def main() -> int:
    extract, mapping = SPEC / "requirements-extract.json", SPEC / "mapping.json"
    if not extract.exists():
        print("Specification completeness: UNVERIFIED (no extracted specification requirements in docs/specification/).")
        return 0
    reqs = json.loads(extract.read_text(encoding="utf-8"))
    mapped = json.loads(mapping.read_text(encoding="utf-8")) if mapping.exists() else {}
    catalogue = {r["id"] for r in REQUIREMENTS}
    missing = [r["id"] for r in reqs if not mapped.get(r["id"])]
    unknown = sorted({c for v in mapped.values() for c in v} - catalogue)
    covered = {c for v in mapped.values() for c in v}
    unmapped_catalogue = sorted(catalogue - covered)
    dup = sorted(c for c in covered if sum(c in v for v in mapped.values()) > 1)
    lines = ["# V4.1 reconciliation report", "", f"Specification requirements extracted: {len(reqs)}", f"- without catalogue mapping (MISSING): {len(missing)}",
             f"- mapped to unknown catalogue ids (CONFLICT): {len(unknown)}", f"- catalogue ids not traced to any specification requirement: {len(unmapped_catalogue)}",
             f"- catalogue ids mapped from several specification requirements (possible duplicates): {len(dup)}", "",
             "## Missing", *[f"- {m}" for m in missing], "", "## Unknown ids", *[f"- {u}" for u in unknown], "", "## Unmapped catalogue ids", *[f"- {u}" for u in unmapped_catalogue]]
    (SPEC / "reconciliation-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"reconciliation written: missing={len(missing)} unknown={len(unknown)} unmapped={len(unmapped_catalogue)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
