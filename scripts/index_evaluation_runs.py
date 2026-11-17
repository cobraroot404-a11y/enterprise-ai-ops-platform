#!/usr/bin/env python
"""Register the evaluation runs found under evaluation/ in the `evaluation_runs` table (migration 0014). Idempotent; reports a manifest that changed after registration, never overwrites it.

    python scripts/index_evaluation_runs.py [--database <name>]

Uses the database owner role (the application roles are read-only on this table). Defaults to the database named by POSTGRES_DB in .env; pass a disposable database name for tests."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from sqlalchemy import create_engine  # noqa: E402

import dev  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.evaluation_registry import index_manifests  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--database")
    args = ap.parse_args()
    dev.load_env()
    engine = create_engine(get_settings(db_name=args.database).url("owner"))
    with engine.begin() as conn:
        result = index_manifests(conn, ROOT / "evaluation")
    print(f"registered {len(result.inserted)}, unchanged {len(result.unchanged)}, CHANGED since registration {len(result.changed)}, skipped (not run manifests) {len(result.skipped)}")
    for rel in result.changed:
        print(f"  CHANGED: {rel}")
    return 1 if result.changed else 0


if __name__ == "__main__":
    sys.exit(main())
