"""Generate THIRD_PARTY_NOTICES.md and docs/security/third-party-license-inventory.json from locally installed metadata (offline).

Sources: the Python lock file plus importlib.metadata of the active environment; frontend/package.json plus frontend/node_modules/*/package.json.
Licence strings are what each package declares about itself. This is an inventory with declared licences, NOT a legal review: the project licence itself states it has
not been legally reviewed, and models, runtimes and container base images are listed with the licence their publisher states, which was not re-fetched here.
Run: python scripts/generate_third_party_notices.py   (--check exits 1 when the committed files are out of date)"""
import json
import sys
from collections import Counter
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"
INVENTORY = ROOT / "docs" / "security" / "third-party-license-inventory.json"

EXTERNAL = [  # (component, role, declared licence, note)
    ("PostgreSQL 16 (image pgvector/pgvector:pg16)", "Database container image", "PostgreSQL License (PostgreSQL); pgvector: PostgreSQL License; Debian base packages carry their own licences", "pulled, not redistributed"),
    ("python:3.12-slim", "Backend container base image", "Python Software Foundation License; Debian packages carry their own licences", "pulled, not redistributed; used by infrastructure/docker/Dockerfile.backend"),
    ("nginx:alpine", "UI container base image", "BSD-2-Clause (nginx); Alpine packages carry their own licences", "pulled, not redistributed; used by infrastructure/docker/Dockerfile.frontend"),
    ("Ollama runtime v0.40.16", "Local LLM server", "MIT (as published by the project)", "installed separately by the user"),
    ("qwen2.5:1.5b (Q4_K_M, Qwen team, via Ollama)", "Language model", "Apache-2.0 (as stated on the Ollama library page)", "downloaded by the user; not redistributed; data/ is git-ignored"),
    ("sentence-transformers/all-MiniLM-L6-v2 (revision 1110a243...)", "Embedding model", "Apache-2.0 (as stated on the model card)", "downloaded by the user; not redistributed"),
    ("Terraform CLI v1.17.2", "Infrastructure-as-code tooling (formatting check only)", "Business Source License 1.1 (licensor IBM, per the LICENSE.txt shipped in the downloaded archive); used unmodified as a local tool, not redistributed and not part of the product", "installed outside the repository; OpenTofu (MPL-2.0) is a drop-in alternative"),
    ("Datasets under evaluation/datasets", "Evaluation data", "Authored for this project (synthetic and fictional); no third-party data", "project licence applies"),
    ("Sample documents, images and PDFs under data/ and onboarding/", "Demonstration content", "Authored for this project (fictional customers); sample PDFs generated with ReportLab (BSD-3-Clause)", "project licence applies"),
]


def py_license(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    expr = meta.get("License-Expression")
    if expr:
        return expr
    text = (meta.get("License") or "").strip()
    if text and len(text) < 80 and "\n" not in text:
        return text
    classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    if classifiers:
        return "; ".join(sorted(set(classifiers)))
    return "UNDECLARED"


def python_packages() -> list[dict]:
    rows = []
    for line in (ROOT / "backend" / "requirements.lock.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, version = line.partition("==")
        try:
            dist = metadata.distribution(name)
            rows.append({"name": name, "version": version or dist.version, "license": py_license(dist), "installed": dist.version})
        except metadata.PackageNotFoundError:
            rows.append({"name": name, "version": version, "license": "NOT INSTALLED HERE", "installed": None})
    return sorted(rows, key=lambda r: r["name"].lower())


def node_packages() -> tuple[list[dict], list[dict]]:
    pkg = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    direct = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    prod = set(pkg.get("dependencies", {}))
    all_rows, direct_rows = [], []
    base = ROOT / "frontend" / "node_modules"
    for manifest in sorted(base.glob("**/package.json")):
        rel = manifest.relative_to(base).parts
        if "node_modules" in rel[:-2] or len(rel) > 3 or (len(rel) == 3 and not rel[0].startswith("@")):
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        name = data.get("name")
        if not name or manifest.parent.name != name.split("/")[-1]:
            continue
        lic = data.get("license") or data.get("licenses") or "UNDECLARED"
        if isinstance(lic, dict):
            lic = lic.get("type", "UNDECLARED")
        if isinstance(lic, list):
            lic = " OR ".join(str(x.get("type", x)) if isinstance(x, dict) else str(x) for x in lic)
        row = {"name": name, "version": data.get("version", "?"), "license": str(lic)}
        all_rows.append(row)
        if name in direct:
            direct_rows.append({**row, "role": "runtime" if name in prod else "development"})
    seen, unique = set(), []
    for r in all_rows:
        if (r["name"], r["version"]) not in seen:
            seen.add((r["name"], r["version"]))
            unique.append(r)
    return sorted(direct_rows, key=lambda r: r["name"]), sorted(unique, key=lambda r: r["name"])


def render(py: list[dict], node_direct: list[dict], node_all: list[dict]) -> tuple[str, dict]:
    hist = Counter(r["license"] for r in node_all)
    lines = [
        "# Third-Party Notices", "",
        "This project depends on third-party software that remains under its own licence. This file is generated by `python scripts/generate_third_party_notices.py` from locally",
        "installed package metadata (offline). Licence strings are what each package **declares about itself**; this is an inventory, not a legal review (the project licence itself says",
        "it has not been legally reviewed). Models, runtimes and container images are listed with the licence their publisher states, which was not re-fetched here. Nothing below is",
        "redistributed in this repository: dependencies, models and images are installed or pulled by the user from their official sources.", "",
        "Full machine-readable inventory (every Python and Node package with version and declared licence): `docs/security/third-party-license-inventory.json`.", "",
        "## Runtimes, models, container images, tools and data", "", "| Component | Role | Declared licence | Note |", "|---|---|---|---|",
    ]
    lines += [f"| {c} | {r} | {lic} | {n} |" for c, r, lic, n in EXTERNAL]
    lines += ["", f"## Python packages ({len(py)}, from `backend/requirements.lock.txt`)", "", "| Package | Version | Declared licence |", "|---|---|---|"]
    lines += [f"| {r['name']} | {r['version']} | {r['license']} |" for r in py]
    lines += ["", f"## Frontend packages directly declared in `frontend/package.json` ({len(node_direct)})", "", "| Package | Version | Role | Declared licence |", "|---|---|---|---|"]
    lines += [f"| {r['name']} | {r['version']} | {r['role']} | {r['license']} |" for r in node_direct]
    lines += ["", f"## Frontend packages installed in total ({len(node_all)}): declared licences", "", "| Declared licence | Packages |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in sorted(hist.items(), key=lambda kv: (-kv[1], kv[0]))]
    lines += ["", "Notes: psycopg (LGPL-3.0) is used as an unmodified, dynamically installed dependency; the bundled `psycopg-binary` wheel ships libpq (PostgreSQL License) and OpenSSL (Apache-2.0).",
              "Where a package declares `UNDECLARED` above, its licence was not found in installed metadata and must be checked by hand before any redistribution.", ""]
    inventory = {"generated_by": "scripts/generate_third_party_notices.py", "python": py, "node_direct": node_direct, "node_all": node_all, "external": [dict(zip(("component", "role", "license", "note"), e, strict=True)) for e in EXTERNAL]}
    return "\n".join(lines), inventory


def main() -> int:
    text, inventory = render(python_packages(), *node_packages())
    rendered = json.dumps(inventory, indent=1) + "\n"
    if "--check" in sys.argv:
        ok = NOTICES.read_text(encoding="utf-8") == text and INVENTORY.read_text(encoding="utf-8") == rendered
        print("up to date" if ok else "OUT OF DATE")
        return 0 if ok else 1
    NOTICES.write_text(text, encoding="utf-8", newline="\n")
    INVENTORY.parent.mkdir(parents=True, exist_ok=True)
    INVENTORY.write_text(rendered, encoding="utf-8", newline="\n")
    undeclared = [r["name"] for r in inventory["python"] if r["license"] in ("UNDECLARED", "NOT INSTALLED HERE")] + [r["name"] for r in inventory["node_all"] if r["license"] == "UNDECLARED"]
    print(f"python {len(inventory['python'])}, node direct {len(inventory['node_direct'])}, node total {len(inventory['node_all'])}; undeclared: {undeclared}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
