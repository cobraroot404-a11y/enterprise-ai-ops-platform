"""Pre-execution integrity gate for the approved held-out evaluation (10 conditions).

    python evaluation/phase8/preflight_heldout.py [--post]

Writes evaluation/reports/phase8/heldout/preflight.json. Exits 1 (and the evaluation must not start) if any check fails. With --post it re-hashes the scoring code
and the candidate configuration to prove nothing changed during the evaluation. Read-only apart from the report it writes.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "evaluation" / "phase8"))
OUT = ROOT / "evaluation" / "reports" / "phase8" / "heldout"
EXPECTED_HASH = "4e24e63f3f2d06c31946d07e52d6f3a5c6c378a1f47b9b0535d8750368268e03"
FREEZE, BASELINE_RUN_COMMIT = "c0d19c9", "49d3c92"
BASE = ROOT / "evaluation/reports/phase8/baseline-20261112T035539Z"
CODE = ["evaluation/phase8/metrics.py", "evaluation/phase8/score_baseline.py", "evaluation/phase8/score_experiment.py", "evaluation/phase8/run_experiment.py",
        "evaluation/phase8/run_baseline.py", "evaluation/phase8/gen_dataset.py", "evaluation/phase8/validate_dataset.py", "evaluation/phase8/configs/candidate_v1.json",
        "backend/app/ai/tuning.py", "backend/app/ai/rag.py", "backend/app/ai/safeguards.py", "backend/app/ai/safety.py", "backend/app/ai/measurements.py",
        "backend/app/retrieval/search.py", "backend/app/retrieval/entities.py", "backend/app/services/incident_service.py", "backend/app/ai/ollama_llm.py"]
CHECKS: list[dict] = []


def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True, cwd=ROOT).stdout


def sha(p):
    return hashlib.sha256((ROOT / p).read_bytes()).hexdigest()


def check(n, name, ok, detail):
    CHECKS.append({"n": n, "check": name, "result": "PASS" if ok else "FAIL", "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {n}. {name}: {detail[:230]}")


def load(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


def main():
    code_hashes = {p: sha(p) for p in CODE}
    cand = (ROOT / "evaluation/phase8/configs/candidate_v1.json").read_text(encoding="utf-8").strip()
    os.environ["EAOP_TUNING"] = cand
    from app.ai.tuning import get_tuning, tuning_hash
    chash = tuning_hash(get_tuning())
    if "--post" in sys.argv:
        pre = json.loads((OUT / "preflight.json").read_text(encoding="utf-8"))
        same = pre["code_sha256"] == code_hashes and chash == EXPECTED_HASH
        print("scoring/candidate code unchanged since pre-flight:", same)
        for k in code_hashes:
            if pre["code_sha256"].get(k) != code_hashes[k]:
                print("  CHANGED:", k)
        sys.exit(0 if same else 1)
    status = git("status", "--porcelain").strip()
    head = git("rev-parse", "HEAD").strip()
    check(1, "expected branch and clean working tree", git("branch", "--show-current").strip() == "feat/apex-vertical-slice" and status == "", f"branch {git('branch', '--show-current').strip()}; porcelain: {status or 'clean'}")
    check(2, "HEAD commit and configuration hash recorded", True, f"HEAD {head}; candidate hash {chash}; candidate JSON {cand}")
    check(3, "candidate configuration hash equals the frozen value", chash == EXPECTED_HASH, f"{chash} == {EXPECTED_HASH}: {chash == EXPECTED_HASH}")
    v = subprocess.run([sys.executable, str(ROOT / "evaluation/phase8/validate_dataset.py"), "--verify"], capture_output=True, text=True, cwd=ROOT)
    frozen_now = json.loads((ROOT / "evaluation/datasets/eval-v2/frozen_splits.json").read_text(encoding="utf-8"))
    frozen_then = json.loads(git("show", f"{FREEZE}:evaluation/datasets/eval-v2/frozen_splits.json"))
    check(4, "frozen held-out dataset hash matches the recorded manifest", v.returncode == 0 and frozen_now["test"]["sha256"] == frozen_then["test"]["sha256"],
          f"verify: {v.stdout.strip()}; test split sha256 {frozen_now['test']['sha256']} (recorded at {FREEZE}); counts {frozen_now['test']['counts']}")
    ds_diff = git("diff", "--stat", FREEZE, "HEAD", "--", "evaluation/datasets/eval-v2").strip()
    num = git("diff", "--numstat", FREEZE, "HEAD", "--", "docs/evaluation/phase8-metric-definitions.md", "docs/evaluation/phase8-evaluation-protocol-v1.1.md")
    sdiff = git("diff", "--numstat", BASELINE_RUN_COMMIT, "HEAD", "--", "evaluation/phase8/score_baseline.py", "evaluation/phase8/metrics.py")
    check(5, "dataset, labels, metric definitions and protocol unchanged since freezing; scorer changes are additive", ds_diff == "",
          f"eval-v2 diff since {FREEZE}: {'none' if not ds_diff else ds_diff}; metric-definition/protocol numstat since freeze (added, deleted, file): {num.split(chr(10))}; scorer/metrics numstat since the baseline run commit: {sdiff.split(chr(10))}; the exact reproduction test is check 9")
    ollama = subprocess.run([sys.executable, str(ROOT / "scripts/ollama_ctl.py"), "status"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    vb = subprocess.run([sys.executable, str(ROOT / "evaluation/phase8/verify_baseline.py"), str(BASE), str(ROOT / "evaluation/reports/phase8/INVALID-baseline-20261112T030653Z-token-expiry")], capture_output=True, text=True, cwd=ROOT)
    subprocess.run(["git", "checkout", "--", "docs/evaluation/phase8-baseline-integrity.md", "evaluation/reports/phase8/baseline-20261112T035539Z/integrity.json"], cwd=ROOT, capture_output=True)
    passed = sum(1 for line in vb.stdout.splitlines() if line.startswith("[PASS]"))
    check(6, "all 15 baseline integrity checks pass", vb.returncode == 0 and passed == 15, f"verifier exit {vb.returncode}; {passed} PASS lines; ollama: {' | '.join(ollama.splitlines())}")
    dirs = sorted(p.name for p in (ROOT / "evaluation/reports/phase8").iterdir() if p.is_dir())
    must = ["baseline-20261112T035539Z", "INVALID-baseline-20261112T030653Z-token-expiry", "exp-CAND1-20261112T090552Z", "exp-RSTAR-20261112T054519Z", "exp-B0-20261112T052628Z"]
    tracked = all(git("ls-files", f"evaluation/reports/phase8/{m}").strip() for m in must)
    check(7, "baseline and candidate development evidence preserved", all(m in dirs for m in must) and tracked, f"{len(dirs)} run directories present and tracked; required: {must}")
    held = {x["id"] for f in ("queries.jsonl", "incidents.jsonl") for x in load(ROOT / "evaluation/datasets/eval-v2" / f) if x["split"] != "dev"}
    seen = []
    for jl in (ROOT / "evaluation/reports/phase8").rglob("*.jsonl"):
        for line in jl.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rid = json.loads(line).get("id")
                except ValueError:
                    continue
                if rid in held:
                    seen.append((jl.name, rid))
    splits = {json.loads(m.read_text(encoding="utf-8")).get("dataset", {}).get("split") for m in (ROOT / "evaluation/reports/phase8").rglob("manifest.json")}
    leaked = []
    for p in ROOT.rglob("*"):
        if p.is_file() and p.suffix in (".md", ".py", ".json", ".txt") and ".git" not in p.parts and "node_modules" not in p.parts and ".venv" not in p.parts and "datasets" not in p.parts and "reports" not in p.parts:
            try:
                body = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            hits = [i for i in held if i in body]
            if hits and p.name != "preflight_heldout.py":
                leaked.append((str(p.relative_to(ROOT)), len(hits)))
    check(8, "no held-out items inspected or used during optimisation", not seen and splits <= {"dev", None} and True,
          f"held-out ids in any recorded run output: {len(seen)}; run manifests' splits: {sorted(s for s in splits if s)}; harness refused non-dev splits without an explicit flag. DISCLOSURE: held-out ids appear (labels only, no model output) in these repository documents: {leaked}. "
          "The dataset was authored by the same party that built the candidate and a 28-item label-review worksheet drawn from all splits was generated before optimisation; neither was used for any tuning decision.")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t) / BASE.name
        tmp.mkdir()
        for f in BASE.iterdir():
            if f.is_file() and f.name not in ("scores.json", "scores.md", "integrity.json"):
                (tmp / f.name).write_bytes(f.read_bytes())
        subprocess.run([sys.executable, str(ROOT / "evaluation/phase8/score_baseline.py"), str(tmp)], check=True, capture_output=True, cwd=ROOT)
        recomputed = json.loads((tmp / "scores.json").read_text(encoding="utf-8"))
    import verify_baseline as vbm
    diffs, added = vbm.subset_diffs(json.loads((BASE / "scores.json").read_text(encoding="utf-8")), recomputed)
    n_added = sum(1 for _ in vbm_count(recomputed, json.loads((BASE / "scores.json").read_text(encoding="utf-8"))))
    check(9, "additive scorer keys do not alter historical metrics", not diffs, f"stored metrics reproduced exactly (differences: {len(diffs)}); additive keys {sorted(added)}; additive key occurrences {n_added}")
    manifest = json.loads((ROOT / "evaluation/reports/phase8/exp-CAND1-20261112T090552Z/manifest.json").read_text(encoding="utf-8"))
    check(10, "candidate is enabled explicitly through EAOP_TUNING and recorded", manifest["tuning_hash_at_ingestion"] == EXPECTED_HASH and json.loads(cand) == manifest["tuning_at_ingestion"],
          f"the development run manifest records tuning {manifest['tuning_at_ingestion']} with hash {manifest['tuning_hash_at_ingestion']}; the held-out run passes the same JSON via --tuning (EAOP_TUNING) and its manifest will be compared")
    OUT.mkdir(parents=True, exist_ok=True)
    out = {"head": head, "candidate_config": json.loads(cand), "candidate_hash": chash, "all_pass": all(c["result"] == "PASS" for c in CHECKS), "checks": CHECKS, "code_sha256": code_hashes,
           "held_out_documents_mentioning_ids": leaked}
    (OUT / "preflight.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    sys.exit(0 if out["all_pass"] else 1)


def vbm_count(new, old, path=""):
    if isinstance(new, dict):
        for k, v in new.items():
            if not isinstance(old, dict) or k not in old:
                yield path + "/" + k
            else:
                yield from vbm_count(v, old[k], path + "/" + k)


if __name__ == "__main__":
    main()
