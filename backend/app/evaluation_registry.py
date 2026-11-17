"""Registry of evaluation runs (migration 0014): indexes the manifests under evaluation/ with a tamper check. The files stay the evidence; this is only an index."""
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import text


@dataclass
class IndexResult:
    inserted: list = field(default_factory=list)
    unchanged: list = field(default_factory=list)
    changed: list = field(default_factory=list)  # registered earlier, manifest bytes differ now: reported, NEVER overwritten
    skipped: list = field(default_factory=list)  # not a run manifest (no run_id) or unreadable


def _ts(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _str(value):
    return value if isinstance(value, str) else None


def index_manifests(conn, root: Path) -> IndexResult:
    """Register every `manifest.json` below `root` that describes a run (has a run_id). `conn` is a database owner connection (the application roles cannot write)."""
    result = IndexResult()
    for path in sorted(root.rglob("manifest.json")):
        rel = path.relative_to(root.parent).as_posix()
        raw = path.read_bytes()
        try:
            data = json.loads(raw)
        except ValueError:
            result.skipped.append(rel)
            continue
        if not isinstance(data, dict) or not data.get("run_id"):
            result.skipped.append(rel)
            continue
        digest = hashlib.sha256(raw).hexdigest()
        existing = conn.execute(text("SELECT manifest_sha256 FROM evaluation_runs WHERE manifest_path = :p"), {"p": rel}).scalar()
        if existing is not None:
            (result.unchanged if existing == digest else result.changed).append(rel)
            continue
        backends = data.get("backends") if isinstance(data.get("backends"), (dict, list)) else None
        duration = data.get("duration_s")
        conn.execute(text(
            "INSERT INTO evaluation_runs (run_id, suite, label, command, dataset, started_at, finished_at, duration_s, git_commit, backends, manifest_path, manifest_sha256) "
            "VALUES (:run_id, :suite, :label, :command, :dataset, :started, :finished, :duration, :commit, CAST(:backends AS jsonb), :path, :sha)"),
            {"run_id": str(data["run_id"]), "suite": path.parent.parent.name if path.parent.parent != root else path.parent.name,
             "label": _str(data.get("label")) or _str(data.get("experiment")), "command": _str(data.get("command")), "dataset": _str(data.get("dataset")),
             "started": _ts(data.get("started_utc")), "finished": _ts(data.get("finished_utc")),
             "duration": duration if isinstance(duration, (int, float)) else None, "commit": _str(data.get("git_commit")),
             "backends": json.dumps(backends) if backends is not None else None, "path": rel, "sha": digest})
        result.inserted.append(rel)
    return result
