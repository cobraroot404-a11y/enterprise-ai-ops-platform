"""Integrity validation and hashing for eval-v2 (no model calls).

    python evaluation/phase8/validate_dataset.py            # validate, write validation_report.json and MANIFEST.sha256
    python evaluation/phase8/validate_dataset.py --verify   # verify the frozen hashes only (exit 1 on any mismatch)

Checks: references resolve to current passages of the query's own tenant; evidence spans exist verbatim in the files as the application's
own parsers read them; required facts occur in evidence; forbidden facts do not; ids unique; every scenario group lives in exactly one split;
no duplicate or near-duplicate (token Jaccard >= 0.9) queries across splits; counts and overlaps; file hashes.
"""
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.ingestion.parsers import parse  # noqa: E402

DS = ROOT / "evaluation" / "datasets" / "eval-v2"
MAPS = json.loads((ROOT / "onboarding" / "meridian.json").read_text(encoding="utf-8"))["profile"]["field_maps"]
KIND_MAPS = {"fleet_register": "fleet_register", "service_history": "service_history", "telematics_alerts": "telematics_alerts"}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def load(name):
    return [json.loads(line) for line in (DS / name).read_text(encoding="utf-8").splitlines() if line.strip()]


def file_hashes() -> dict:
    out = {}
    for p in sorted(DS.rglob("*")):
        if p.is_file() and p.name not in ("MANIFEST.sha256", "validation_report.json", "FROZEN.md"):
            out[p.relative_to(DS).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def parsed_passages(tenant: str, passages) -> dict:
    """(file, unit, current) -> normalised text as the application's parsers produce it."""
    out = {}
    for fname in sorted({(p["file"], p["current"], p["kind"]) for p in passages if p["tenant"] == tenant}):
        file, current, kind = fname
        path = DS / "corpus" / tenant / (file if current else f"superseded/{file}")
        mapping = MAPS.get(kind) if tenant == "meridian" else None
        parsed, _media = parse(file, path.read_bytes(), field_map=mapping["columns"] if mapping else None, id_field=mapping["id_field"] if mapping else None)
        by = defaultdict(list)
        for seg in parsed.segments:
            unit = seg.page_number if seg.page_number is not None else seg.record_id
            by[unit].append(seg.text)
        for unit, texts in by.items():
            out[(file, unit, current)] = norm(" ".join(texts))
    return out


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def validate() -> dict:
    passages, queries, cases = load("passages.jsonl"), load("queries.jsonl"), load("incidents.jsonl")
    problems: list[str] = []
    key = lambda p: (p["tenant"], p["file"], p["unit"], p["current"])  # noqa: E731
    index = {key(p): p for p in passages}
    if len(index) != len(passages):
        problems.append("duplicate passage keys")
    parsed = {t: parsed_passages(t, passages) for t in ("apex", "meridian")}
    # passage text as stored must equal what the parser reads (generator and parser agree on the ground truth)
    mismatched = 0
    for p in passages:
        got = parsed[p["tenant"]].get((p["file"], p["unit"], p["current"]))
        if got is None:
            problems.append(f"passage not found by parser: {p['file']}#{p['unit']}")
        elif norm(p["text"]) not in got and got not in norm(p["text"]):
            mismatched += 1
    if mismatched:
        problems.append(f"{mismatched} passages whose stored text differs from parsed text")
    ids = [q["id"] for q in queries] + [c["id"] for c in cases]
    if len(ids) != len(set(ids)):
        problems.append("duplicate ids")
    spans_ok = 0
    for q in queries:
        t = q["tenant"]
        for r in q["relevant"]:
            if (t, r["file"], r["unit"], True) not in index:
                problems.append(f"{q['id']}: relevant passage missing or not current: {r['file']}#{r['unit']}")
        spans_text = []
        for s in q["evidence_spans"]:
            got = parsed[t].get((s["file"], s["unit"], True), "")
            if norm(s["text"]) in got:
                spans_ok += 1
            else:
                problems.append(f"{q['id']}: evidence span not found verbatim in {s['file']}#{s['unit']}")
            spans_text.append(norm(s["text"]))
        joined = " ".join(spans_text)
        if q["answerable"]:
            for f in q["required_facts"]:
                if norm(f) not in joined:
                    problems.append(f"{q['id']}: required fact {f!r} not in evidence spans")
        for f in q["forbidden_facts"]:
            if re.search(rf"(?<![\w.]){re.escape(norm(f))}(?![\w])", joined):
                problems.append(f"{q['id']}: forbidden fact {f!r} appears in evidence")
        if q.get("answerable") and not q["relevant"]:
            problems.append(f"{q['id']}: answerable query without relevant passages")
        if not q["answerable"] and q["expected_refusal"] and q["relevant"]:
            problems.append(f"{q['id']}: unanswerable query lists relevant passages")
        for h in q["hard_negatives"]:
            if not any((t, h["file"], h["unit"], c) in index for c in (True, False)):
                problems.append(f"{q['id']}: hard negative missing: {h['file']}#{h['unit']}")
    # groups never span splits
    for name, items in (("query", queries), ("case", cases)):
        spans = defaultdict(set)
        for it in items:
            spans[it["group"]].add(it["split"])
        for g, s in spans.items():
            if len(s) > 1:
                problems.append(f"{name} group {g} spans splits {sorted(s)}")
        if {it["split"] for it in items} - {"dev", "test", "challenge"}:
            problems.append(f"{name}: invalid split value")
    # duplicates and near-duplicates across splits
    toks = [(q["id"], q["split"], set(re.findall(r"[a-z0-9\-/\.]+", q["query"].lower()))) for q in queries]
    exact = Counter((q["tenant"], norm(q["query"])) for q in queries)  # identical wording across tenants is a deliberate isolation test
    dups = [k for k, v in exact.items() if v > 1]
    if dups:
        problems.append(f"{len(dups)} exact duplicate queries")
    max_cross, worst = 0.0, None
    for i in range(len(toks)):
        for j in range(i + 1, len(toks)):
            if toks[i][1] != toks[j][1]:
                s = jaccard(toks[i][2], toks[j][2])
                if s > max_cross:
                    max_cross, worst = s, (toks[i][0], toks[j][0])
    if max_cross >= 0.9:
        problems.append(f"near-duplicate queries across splits (Jaccard {max_cross:.2f}): {worst}")
    # case checks
    for c in cases:
        if c["expected_outcome"] == "incident" and c["asset_id"] and "unregistered_asset" not in c["tags"]:
            if (c["tenant"], f"{c['tenant']}_register.csv", c["asset_id"], True) not in index:
                problems.append(f"{c['id']}: asset {c['asset_id']} not in register")
        if "unregistered_asset" in c["tags"] and (c["tenant"], f"{c['tenant']}_register.csv", c["asset_id"], True) in index:
            problems.append(f"{c['id']}: 'unregistered' asset exists in the register")
    cat = Counter(q["category"] for q in queries)
    tag = Counter(t for q in queries for t in q["tags"])
    split_tenant = Counter((q["split"], q["tenant"]) for q in queries)
    per_tenant_passages = {t: {"total": sum(1 for p in passages if p["tenant"] == t), "current": sum(1 for p in passages if p["tenant"] == t and p["current"])}
                           for t in ("apex", "meridian")}
    unans = [q for q in queries if not q["answerable"]]
    report = {
        "problems": problems, "ok": not problems, "passages": per_tenant_passages,
        "queries": {"total": len(queries), "by_category": dict(cat), "by_tag": dict(tag),
                    "answerable": sum(1 for q in queries if q["answerable"]), "unanswerable_or_refusal_expected": sum(1 for q in queries if q["expected_refusal"]),
                    "unanswerable_incl_adversarial_optional": len(unans), "multi_relevant": sum(1 for q in queries if len(q["relevant"]) >= 2),
                    "hard_negative_queries": sum(1 for q in queries if q["hard_negatives"]),
                    "adversarial_or_cross_tenant": sum(1 for q in queries if "adversarial" in q["tags"] or "cross_tenant" in q["tags"]),
                    "version_conflict": cat.get("version_conflict", 0),
                    "by_split_and_tenant": {f"{s}/{t}": n for (s, t), n in sorted(split_tenant.items())},
                    "by_split": dict(Counter(q["split"] for q in queries)), "by_difficulty": dict(Counter(q["difficulty"] for q in queries))},
        "incident_cases": {"total": len(cases), "by_tenant": dict(Counter(c["tenant"] for c in cases)), "by_split": dict(Counter(c["split"] for c in cases)),
                           "by_tag": dict(Counter(t for c in cases for t in c["tags"]))},
        "leakage_checks": {"max_cross_split_query_jaccard": round(max_cross, 3), "exact_duplicate_queries": len(dups), "groups_spanning_splits": 0 if not any("spans splits" in p for p in problems) else "see problems"},
        "evidence_spans_verified": spans_ok,
    }
    return report


def split_hashes() -> dict:
    """SHA-256 of the canonical serialisation of each split's items (queries and incident cases) - the frozen-split record."""
    out = {}
    for name in ("queries.jsonl", "incidents.jsonl"):
        for item in load(name):
            out.setdefault(item["split"], {}).setdefault(name, []).append(item)
    return {split: {"counts": {n: len(v) for n, v in parts.items()},
                    "sha256": hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest(),
                    "ids": sorted(i["id"] for v in parts.values() for i in v)} for split, parts in sorted(out.items())}


def main():
    verify_only = "--verify" in sys.argv
    manifest = DS / "MANIFEST.sha256"
    if verify_only:
        recorded = dict(line.split("  ", 1)[::-1] for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip())
        actual = file_hashes()
        bad = [f for f in set(recorded) | set(actual) if recorded.get(f) != actual.get(f)]
        frozen = json.loads((DS / "frozen_splits.json").read_text(encoding="utf-8"))
        current = split_hashes()
        bad += [f"split:{k}" for k in frozen if frozen[k]["sha256"] != current.get(k, {}).get("sha256")]
        print("frozen hashes OK" if not bad else f"MISMATCH: {sorted(bad)[:10]}")
        sys.exit(1 if bad else 0)
    report = validate()
    (DS / "validation_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    (DS / "frozen_splits.json").write_text(json.dumps(split_hashes(), indent=1) + chr(10), encoding="utf-8", newline=chr(10))
    hashes = file_hashes()
    manifest.write_text("\n".join(f"{h}  {f}" for f, h in hashes.items()) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: report[k] for k in ("ok", "passages", "leakage_checks", "evidence_spans_verified")}, indent=1))
    print("problems:", len(report["problems"]))
    for p in report["problems"][:25]:
        print(" -", p)
    sys.exit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
