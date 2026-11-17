"""V41-01.02, the final objective and V41-26.01: the lifecycle capabilities and the sixteen kinds of test are each mapped to artifacts that exist, with a stated limit, in the
specification's own order and wording."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = (ROOT / "docs" / "customer-delivery" / "fde-capability-map.md").read_text(encoding="utf-8")
SPEC = (ROOT / "docs" / "specification" / "ORIGINAL_MASTER_SPECIFICATION_V4.1.txt").read_text(encoding="utf-8").splitlines()


def rows(heading: str) -> list[list[str]]:
    block = DOC.split(heading, 1)[1].split("\n## ", 1)[0]
    return [[c.strip() for c in line.strip().strip("|").split("|")] for line in block.splitlines() if line.startswith("|")][2:]


def test_the_fifteen_capabilities_are_listed_in_the_specifications_order_and_wording():
    start = next(i for i, line in enumerate(SPEC) if "complete lifecycle of Forward Deployed Engineering:" in line)
    specified = [re.sub(r"^\d+\.\s*", "", line).rstrip(".") for line in SPEC[start:start + 20] if re.match(r"^\d+\. ", line)]
    table = rows("## Lifecycle capabilities")
    assert len(specified) == 15 and [r[1] for r in table] == specified


def test_the_sixteen_kinds_of_test_are_listed_in_the_specifications_order():
    start = next(i for i, line in enumerate(SPEC) if line.startswith("PART 26"))
    specified = [line[2:].strip() for line in SPEC[start:start + 25] if line.startswith("* ")][:16]
    table = rows("## The sixteen kinds of test (Part 26)")
    assert len(table) == 16
    for row, wording in zip(table, specified, strict=True):
        assert wording.lower().removesuffix(" tests").removesuffix(" test") .startswith(row[0].lower().split(" ")[0]), (row[0], wording)


def test_every_cited_artifact_exists_and_every_row_states_a_limit_or_a_runner():
    for heading in ("## Lifecycle capabilities", "## The sixteen kinds of test (Part 26)"):
        for row in rows(heading):
            paths = re.findall(r"`([^`]+)`", " ".join(row))
            assert paths, row
            for path in paths:
                if "/" in path or path.endswith(".md"):
                    assert (ROOT / path.rstrip("/")).exists(), path
            assert row[-1], row


def test_the_page_does_not_overclaim():
    for phrase in ("fictional", "does not mean a real customer", "quality targets not met", "no independent reproduction", "no productivity claim", "nothing deployed"):
        assert phrase in DOC, phrase
