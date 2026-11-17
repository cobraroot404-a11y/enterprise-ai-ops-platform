"""Development experiment: does an explicit 'null unless an ID is written' instruction stop the model inventing asset ids? (new development cases only; see
evaluation/datasets/dev-noasset-v1/make_cases.py for why consumed held-out and challenge cases are NOT used).

    python evaluation/phase8/run_noasset_dev.py            # needs Ollama running with the configured model; writes evaluation/reports/dev-noasset-v1/<timestamp>/

For each case and prompt variant it makes ONE raw extraction call (temperature 0, fixed seed) and classifies the raw output with the same rules the application applies:
  schema_invalid   the output is not schema-conformant JSON
  invented         asset_id is a string that does not occur in the report (the application rejects this as a hallucination)
  null_correct     no id in the report and asset_id is null
  correct          the expected id was returned
  wrong            an id that occurs in the report but is not the expected one
  null_wrong       an id was in the report but the model returned null
Raw validity (the metric that was 90% on the held-out split) = every outcome except schema_invalid and invented.
Same-author development evidence: it can justify a change, it cannot confirm one."""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.ai import ollama_llm as o  # noqa: E402
from app.core.config import get_settings  # noqa: E402

SENTENCE = (" If the report does not contain an equipment ID written like P-101 or XJ-204 (letters, a hyphen, digits), asset_id MUST be null. Never invent, guess or infer an ID from a "
            "description such as 'the big pump' or 'the east building', and never reuse an example ID.")
VARIANTS = {"A_current": o.EXTRACT_SYSTEM, "B_explicit_null": o.EXTRACT_SYSTEM.replace("or null if no equipment ID is given.", "or null if no equipment ID is given." + SENTENCE)}


def classify(raw: str, text: str, expected) -> str:
    try:
        out = o._FieldsOut.model_validate_json(raw)
    except Exception:  # noqa: BLE001 - any parse failure is a schema failure
        return "schema_invalid"
    asset = out.asset_id.strip().upper() if out.asset_id else None
    if asset and asset not in text.upper():
        return "invented"
    if expected is None:
        return "null_correct" if asset is None else "wrong"
    if asset is None:
        return "null_wrong"
    return "correct" if asset == expected.upper() else "wrong"


def main() -> int:
    settings = get_settings()
    llm = o.OllamaLLM(settings.ollama_base_url, settings.ollama_model, settings.ollama_timeout)
    cases = [json.loads(line) for line in (ROOT / "evaluation" / "datasets" / "dev-noasset-v1" / "cases.jsonl").read_text(encoding="utf-8").splitlines()]
    out_dir = ROOT / "evaluation" / "reports" / "dev-noasset-v1" / datetime.now().strftime("%Y%m%dT%H%M%S")
    out_dir.mkdir(parents=True)
    results = {}
    started = time.time()
    for name, prompt in VARIANTS.items():
        rows = []
        for case in cases:
            raw = llm._chat("extract", prompt, f"Fault report:\n{case['text']}", o.FIELDS_SCHEMA)
            try:
                model_asset = o._FieldsOut.model_validate_json(raw).asset_id
            except Exception:  # noqa: BLE001
                model_asset = None
            application_asset, model_vs_candidates = o.choose_asset(case["text"], model_asset)  # what the application now does with the model's value
            rows.append({"id": case["id"], "kind": case["kind"], "expected": case["expected_asset"], "outcome": classify(raw, case["text"], case["expected_asset"]), "raw": raw,
                         "application_asset": application_asset, "application_correct": application_asset == case["expected_asset"], "model_vs_candidates": model_vs_candidates})
        results[name] = rows
        print(name, {k: sum(r["outcome"] == k for r in rows) for k in sorted({r["outcome"] for r in rows})}, flush=True)
    summary = {}
    for name, rows in results.items():
        na, wa = [r for r in rows if r["kind"] == "no_asset"], [r for r in rows if r["kind"] == "with_asset"]
        summary[name] = {"no_asset_cases": len(na), "invented": sum(r["outcome"] == "invented" for r in na), "null_correct": sum(r["outcome"] == "null_correct" for r in na),
                         "with_asset_cases": len(wa), "correct": sum(r["outcome"] == "correct" for r in wa), "null_wrong": sum(r["outcome"] == "null_wrong" for r in wa),
                         "raw_valid": sum(r["outcome"] not in ("schema_invalid", "invented") for r in rows), "total": len(rows),
                         "application_asset_correct": sum(r["application_correct"] for r in rows)}
    meta = {"model": settings.ollama_model, "options": llm.options, "dataset_sha256": (ROOT / "evaluation" / "datasets" / "dev-noasset-v1" / "MANIFEST.sha256").read_text(encoding="utf-8").split()[0],
            "elapsed_s": round(time.time() - started, 1), "note": "development evidence only; not confirmation"}
    (out_dir / "results.json").write_text(json.dumps({"meta": meta, "summary": summary, "rows": results}, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
