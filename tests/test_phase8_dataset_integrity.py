"""Phase 8 dataset integrity: references, evidence, leakage controls, frozen hashes, deterministic regeneration."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "evaluation" / "phase8"))
import validate_dataset as vd  # noqa: E402

DS = ROOT / "evaluation" / "datasets" / "eval-v2"


def test_dataset_validates_with_no_problems():
    report = vd.validate()
    assert report["problems"] == [], report["problems"][:5]
    q = report["queries"]
    assert q["total"] >= 180 and q["unanswerable_or_refusal_expected"] >= 45 and q["multi_relevant"] >= 30
    assert q["adversarial_or_cross_tenant"] + report["incident_cases"]["by_tag"].get("adversarial", 0) >= 30
    assert report["incident_cases"]["total"] >= 50 and report["leakage_checks"]["max_cross_split_query_jaccard"] < 0.9
    assert min(p["current"] for p in report["passages"].values()) >= 650


def test_frozen_hashes_match_the_files():
    recorded = dict(line.split("  ", 1)[::-1] for line in (DS / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines() if line.strip())
    assert recorded == vd.file_hashes()
    frozen = json.loads((DS / "frozen_splits.json").read_text(encoding="utf-8"))
    current = vd.split_hashes()
    assert {k: v["sha256"] for k, v in frozen.items()} == {k: v["sha256"] for k, v in current.items()}
    assert set(frozen) == {"dev", "test", "challenge"}
    ids = [set(v["ids"]) for v in frozen.values()]
    assert not (ids[0] & ids[1]) and not (ids[0] & ids[2]) and not (ids[1] & ids[2])  # no item in two splits


def test_regeneration_is_byte_identical(tmp_path):
    env = {**os.environ, "EVAL_V2_OUT": str(tmp_path / "eval-v2")}
    subprocess.run([sys.executable, str(ROOT / "evaluation" / "phase8" / "gen_dataset.py")], check=True, env=env, capture_output=True)
    regenerated = {p.relative_to(tmp_path / "eval-v2").as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted((tmp_path / "eval-v2").rglob("*")) if p.is_file()}
    committed = {k: v for k, v in vd.file_hashes().items() if k in regenerated}
    assert regenerated == committed and len(committed) > 50


def test_labels_do_not_reference_model_outputs_and_ids_are_stable_format():
    import re
    for item in vd.load("queries.jsonl") + vd.load("incidents.jsonl"):
        assert re.fullmatch(r"E2-[AM]-X?\d{3,4}", item["id"]) and item["dataset_version"] == "eval-v2.0"
        assert not {"model_output", "prediction", "predicted"} & set(item)
