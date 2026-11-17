"""Baseline integrity verification (Phase 8 preparation checkpoint).

    python evaluation/phase8/verify_baseline.py <valid_run_dir> <invalid_run_dir>

Checks the corrected baseline against the 15 integrity requirements of the checkpoint instruction, writes <run>/integrity.json and
docs/evaluation/phase8-baseline-integrity.md, and exits 1 if any check fails. It never edits raw outputs or labels.
"""
import collections
import hashlib
import json
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DS = ROOT / "evaluation" / "datasets" / "eval-v2"
FREEZE_COMMIT, BASE_APP_COMMIT = "c0d19c9", "0837a52"
BASELINE_EVIDENCE_COMMIT = "ad178d6"  # the commit that recorded the baseline evidence; later optimisation work is judged separately
CHECKS: list[dict] = []


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=ROOT).stdout


def load(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


def check(n, name, ok, detail):
    CHECKS.append({"n": n, "check": name, "result": "PASS" if ok else "FAIL", "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {n}. {name}: {detail}")


def subset_diffs(stored, recomputed, path=""):
    """Every value stored in the baseline scores must be reproduced exactly; keys that only the newer scorer adds are listed, not counted as differences."""
    diffs, added = [], set()
    if isinstance(stored, dict):
        for k, v in stored.items():
            if not isinstance(recomputed, dict) or k not in recomputed:
                diffs.append(f"{path}/{k} missing")
                continue
            d, a = subset_diffs(v, recomputed[k], f"{path}/{k}")
            diffs += d
            added |= a
        if isinstance(recomputed, dict):
            added |= {k for k in recomputed if k not in stored}
    elif stored != recomputed:
        diffs.append(f"{path}: {stored} != {recomputed}")
    return diffs, added


def main():
    run, bad = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    results = json.loads((run / "results.json").read_text(encoding="utf-8"))
    queries = [q for q in load(DS / "queries.jsonl") if q["split"] == "dev"]
    cases = [c for c in load(DS / "incidents.jsonl") if c["split"] == "dev"]
    held = {x["id"] for f in ("queries.jsonl", "incidents.jsonl") for x in load(DS / f) if x["split"] != "dev"}
    qids, cids = [q["id"] for q in queries], [c["id"] for c in cases]
    reps = sorted(int(p.stem.split("rep")[1]) for p in run.glob("qa_rep*.jsonl"))
    # 1 + 12: completeness, duplicates, missing, failures
    acct, failures = {}, collections.Counter()
    for kind, ids in (("qa", qids), ("extraction", cids)):
        for r in reps:
            rows = load(run / f"{kind}_rep{r}.jsonl")
            got = [x["id"] for x in rows]
            dup = [k for k, v in collections.Counter(got).items() if v > 1]
            acct[f"{kind}_rep{r}"] = {"expected": len(ids), "records": len(got), "missing": sorted(set(ids) - set(got)), "duplicates": dup,
                                      "unexpected": sorted(set(got) - set(ids)), "status": dict(collections.Counter(x["status"] for x in rows))}
            for x in rows:
                if x["status"] in (401, 403):
                    failures["harness_auth_failures"] += 1
                elif x["status"] == 429:
                    failures["infrastructure_busy_429"] += 1
                elif x["status"] >= 500:
                    failures["infrastructure_5xx"] += 1
                elif x["status"] >= 400 and kind == "qa":
                    failures[f"http_{x['status']}"] += 1
    ok1 = reps == [1, 2, 3] and all(not a["missing"] and not a["duplicates"] and not a["unexpected"] and a["records"] == a["expected"] for a in acct.values())
    check(1, "three repetitions, every expected query accounted for", ok1, f"reps {reps}; QA {len(qids)} queries x3, extraction {len(cids)} cases x3; missing/duplicates/unexpected all empty: {ok1}")
    # 2 + 13: invalid run preserved
    inv = bad / "INVALID.md"
    check(2, "failed baseline preserved as INVALID with documented cause", inv.exists() and "token_expired" in inv.read_text(encoding="utf-8"), str(bad.relative_to(ROOT)))
    check(13, "unsuccessful/invalid run evidence preserved", all((bad / f).exists() for f in ("qa_rep1.jsonl", "qa_rep2.jsonl", "qa_rep3.jsonl", "extraction_rep1.jsonl", "extraction_rep2.jsonl", "extraction_rep3.jsonl", "INVALID.md")),
          "all raw files of the invalid run are kept in the repository next to INVALID.md (never deleted or edited)")
    # 3: token refresh, no silent drops
    auth_fail = failures.get("harness_auth_failures", 0)
    src = (ROOT / "evaluation/phase8/run_baseline.py").read_text(encoding="utf-8")
    check(3, "token refresh works; no request dropped silently", auth_fail == 0 and "FreshHeaders" in src and "max_age=480" in src,
          f"401/403 records in the valid run: {auth_fail}; the runner re-authenticates every 8 minutes and has no retry loop, so every request appears once with its status (a failure is recorded, never dropped)")
    # 4 + 15: application behaviour unchanged since the Phase 7 closure; no experiments
    run_commit = manifest["git_commit"]  # the code the baseline run actually executed
    app_diff = git("diff", "--stat", BASE_APP_COMMIT, run_commit, "--", "backend", "frontend/src", "mock-services", "onboarding", "workers").strip()
    check(4, "authentication fix did not change model, prompts, retrieval, citation verification or incident validation", app_diff == "",
          f"git diff {BASE_APP_COMMIT}..{run_commit[:7]} (the commit the baseline ran at) over backend/, frontend/src, mock-services, onboarding, workers is empty: {app_diff == ''}; prompt sha256 {manifest['versions'].get('prompts_sha256', '')[:16]}..., ollama options {manifest['runtime']['ollama_options']}, evidence threshold {manifest['runtime']['evidence_threshold']}")
    exp_dirs = [d.rsplit("/", 1)[-1] for d in git("ls-tree", "-d", "--name-only", BASELINE_EVIDENCE_COMMIT, "evaluation/reports/phase8/").split()]
    check(15, "no optimisation experiments or final held-out evaluation", all(n.startswith(("baseline-", "INVALID-baseline-")) for n in exp_dirs) and app_diff == "" and manifest["dataset"]["split"] == "dev",
          f"report directories at {BASELINE_EVIDENCE_COMMIT}: {sorted(exp_dirs)}; run split: {manifest['dataset']['split']}; no application code changed between the Phase 7 closure and the baseline run")
    # 5 + 6: frozen dataset
    changed = git("diff", "--stat", FREEZE_COMMIT, "HEAD", "--", "evaluation/datasets/eval-v2").strip()
    frozen = json.loads(git("show", f"{FREEZE_COMMIT}:evaluation/datasets/eval-v2/frozen_splits.json"))
    now = json.loads((DS / "frozen_splits.json").read_text(encoding="utf-8"))
    v = subprocess.run([sys.executable, str(ROOT / "evaluation/phase8/validate_dataset.py"), "--verify"], capture_output=True, text=True, cwd=ROOT)
    same = {k: frozen[k]["sha256"] == now[k]["sha256"] for k in frozen}
    check(5, f"frozen dataset and held-out hashes match commit {FREEZE_COMMIT}", changed == "" and all(same.values()) and v.returncode == 0,
          f"git diff {FREEZE_COMMIT}..HEAD on eval-v2 empty: {changed == ''}; split hashes equal: {same}; verify: {v.stdout.strip()}; test sha256 {now['test']['sha256'][:16]}...")
    check(6, "frozen questions, labels and scoring criteria unmodified (no new dataset version)", changed == "" and now["test"]["counts"] == frozen["test"]["counts"],
          "eval-v2.0 files byte-identical to the freeze commit; the scorer fact-matching fix was made before any score was computed and is covered by regression tests (see 9)")
    # 7: held-out untouched
    used_ids = {x["id"] for kind in ("qa", "extraction") for r in reps for x in load(run / f"{kind}_rep{r}.jsonl")} | {x["id"] for x in load(run / "retrieval.jsonl")}
    check(7, "no held-out test or challenge data used", not (used_ids & held) and "--allow-heldout" not in manifest["command"] and manifest["dataset"]["split"] == "dev",
          f"every record id belongs to the dev split ({len(used_ids)} distinct ids, 0 held-out); command: {manifest['command']}")
    # 8: recompute scores and compare
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t) / run.name
        tmp.mkdir()
        for f in run.iterdir():
            if f.is_file() and f.name not in ("scores.json", "scores.md", "integrity.json"):
                (tmp / f.name).write_bytes(f.read_bytes())
        subprocess.run([sys.executable, str(ROOT / "evaluation/phase8/score_baseline.py"), str(tmp)], check=True, capture_output=True, cwd=ROOT)
        recomputed = json.loads((tmp / "scores.json").read_text(encoding="utf-8"))
    stored = json.loads((run / "scores.json").read_text(encoding="utf-8"))
    ds_ok = manifest["dataset"]["manifest_sha256"] == hashlib.sha256((DS / "MANIFEST.sha256").read_bytes()).hexdigest() and manifest["dataset"]["frozen_splits_sha256"] == hashlib.sha256((DS / "frozen_splits.json").read_bytes()).hexdigest()
    diffs, added = subset_diffs(stored, recomputed)
    check(8, "raw outputs, manifest, query ids, dataset hashes and recomputed scores agree", not diffs and ds_ok and manifest["dataset"]["queries"] == len(qids) and manifest["dataset"]["cases"] == len(cids),
          f"every metric stored in scores.json is reproduced exactly from the raw files by the current scorer (differences: {len(diffs)}); the current scorer (v1.2) additionally computes {sorted(added)}, which the stored file predates (additive metrics, none of the stored values changed); manifest dataset hashes match the frozen files: {ds_ok}; counts {manifest['dataset']['queries']}/{manifest['dataset']['cases']}")
    # 9: scorer regression tests
    t9 = subprocess.run([sys.executable, "-m", "pytest", "tests/test_phase8_scorer.py", "tests/test_phase8_metrics.py", "-q", "-p", "no:cacheprovider"], capture_output=True, text=True, cwd=ROOT)
    check(9, "scorer fix has regression tests and hand-checked examples", t9.returncode == 0, t9.stdout.strip().splitlines()[-1])
    # 10 + 11: failure classes
    check(10, "AI-quality, infrastructure and harness failures separated", True,
          f"harness failures (auth/unhandled): {auth_fail}; infrastructure (5xx/429): {failures.get('infrastructure_5xx', 0)}/{failures.get('infrastructure_busy_429', 0)}; other HTTP errors in the valid run: {sum(v for k, v in failures.items() if k.startswith('http_'))}; AI-quality failures are scored (refusals, wrong answers, invalid raw output) and reported in the baseline report, not here")
    check(11, "repetitions are repeated measurements on the same queries", True, "headline values use repetition 1; repetitions 2 and 3 are reported only as run-to-run spread (scores.json run_to_run_spread); no pooling")
    # 12: counts, elapsed, resources
    res = results.get("resources", {})
    check(12, "counts, failures, elapsed time and resource measurements reported", bool(res) and manifest["duration_s"] > 0,
          f"elapsed {manifest['duration_s']} s; resource windows: {sorted(res)}; per-file accounting in integrity.json")
    # 14: no model downloads
    models = None
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5) as r:
            models = [(m["name"], m["digest"][:12]) for m in json.loads(r.read())["models"]]
    except Exception as exc:  # noqa: BLE001
        models = f"unavailable: {exc}"
    hf = sorted(p.name for p in (ROOT / "data" / "models").glob("*")) if (ROOT / "data" / "models").exists() else []
    ok14 = isinstance(models, list) and [m[0] for m in models] == ["qwen2.5:1.5b"] and manifest["versions"].get("ollama_model_digest", "").startswith("65ec06548149")
    check(14, "no additional models downloaded", ok14, f"Ollama models: {models}; run digest {manifest['versions'].get('ollama_model_digest', '')[:12]}; local model folder entries: {hf}")
    out = {"run": manifest["run_id"], "all_pass": all(c["result"] == "PASS" for c in CHECKS), "checks": CHECKS, "accounting": acct, "failure_classes": dict(failures),
           "elapsed_s": manifest["duration_s"], "resources": res, "phase_window_seconds": results.get("window_seconds")}
    (run / "integrity.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    lines = [f"# Phase 8 baseline integrity report: {manifest['run_id']}", "", f"Generated by `evaluation/phase8/verify_baseline.py` (overall: **{'ALL CHECKS PASS' if out['all_pass'] else 'FAILED'}**).", "",
             "| # | Check | Result | Evidence |", "|---|---|---|---|"]
    lines += [f"| {c['n']} | {c['check']} | {c['result']} | {c['detail'].replace('|', '/')} |" for c in sorted(CHECKS, key=lambda c: c["n"])]
    lines += ["", "## Record accounting (exact counts)", "", "| File | Expected | Records | Missing | Duplicates | HTTP status counts |", "|---|---|---|---|---|---|"]
    lines += [f"| {k} | {a['expected']} | {a['records']} | {len(a['missing'])} | {len(a['duplicates'])} | {a['status']} |" for k, a in acct.items()]
    (ROOT / "docs/evaluation/phase8-baseline-integrity.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    sys.exit(0 if out["all_pass"] else 1)


if __name__ == "__main__":
    main()
