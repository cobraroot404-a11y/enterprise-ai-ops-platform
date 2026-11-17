"""V41-17.04 entity "Evaluation runs": the registry indexes manifests with a tamper check, is read-only for the application roles, and the migration is reversible only when empty.
Runs on the isolated test database for the index logic and on a disposable database for the migration."""
import json
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.evaluation_registry import index_manifests
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from support import ROOT


def manifest(root: Path, name: str, **fields):
    d = root / "evaluation" / "reports" / name
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps(fields), encoding="utf-8")


@pytest.fixture()
def clean_registry(owner_engine):
    with owner_engine.begin() as c:
        c.execute(text("DELETE FROM evaluation_runs WHERE manifest_path LIKE 'tmp-%' OR manifest_path LIKE '%/reg-test-%'"))
    yield
    with owner_engine.begin() as c:
        c.execute(text("DELETE FROM evaluation_runs WHERE manifest_path LIKE '%/reg-test-%'"))


def test_manifests_are_registered_once_and_a_changed_manifest_is_reported_not_overwritten(owner_engine, tmp_path, clean_registry):
    root = tmp_path / "evaluation"
    manifest(tmp_path, "reg-test-a", run_id="run-a", command="python x.py", dataset="dev-set", started_utc="2026-01-01T10:00:00Z", finished_utc="2026-01-01T10:05:00Z", duration_s=300.5,
             git_commit="abc123", backends={"llm": "deterministic"})
    manifest(tmp_path, "reg-test-b", note="not a run manifest: no run_id")
    (root / "reports" / "reg-test-c").mkdir()
    (root / "reports" / "reg-test-c" / "manifest.json").write_text("{not json", encoding="utf-8")
    with owner_engine.begin() as c:
        first = index_manifests(c, root)
    assert len(first.inserted) == 1 and len(first.skipped) == 2 and not first.changed
    with owner_engine.begin() as c:
        again = index_manifests(c, root)
    assert not again.inserted and len(again.unchanged) == 1
    row = None
    with owner_engine.connect() as c:
        row = c.execute(text("SELECT run_id, suite, command, dataset, duration_s, git_commit, backends, manifest_sha256 FROM evaluation_runs WHERE run_id = 'run-a'")).one()
    assert row[:6] == ("run-a", "reports", "python x.py", "dev-set", 300.5, "abc123") and row[6] == {"llm": "deterministic"} and len(row[7]) == 64
    (root / "reports" / "reg-test-a" / "manifest.json").write_text(json.dumps({"run_id": "run-a", "command": "tampered"}), encoding="utf-8")
    with owner_engine.begin() as c:
        tampered = index_manifests(c, root)
    assert len(tampered.changed) == 1 and not tampered.inserted
    with owner_engine.connect() as c:
        assert c.execute(text("SELECT command FROM evaluation_runs WHERE run_id = 'run-a'")).scalar() == "python x.py"  # the registered record was NOT overwritten


def test_the_real_repository_manifests_are_indexable(owner_engine, clean_registry):
    with owner_engine.begin() as c:
        result = index_manifests(c, ROOT / "evaluation")
        total = len(result.inserted) + len(result.unchanged)
        assert total >= 30 and not result.changed  # the frozen evaluation manifests register and none differs from an earlier registration
        for rel in result.inserted:  # leave the shared test database as it was
            c.execute(text("DELETE FROM evaluation_runs WHERE manifest_path = :p"), {"p": rel})


def test_the_application_and_worker_roles_can_read_but_never_write_the_registry(app_db, worker_db):
    for db in (app_db, worker_db):
        with db.session() as s:
            s.execute(text("SELECT count(*) FROM evaluation_runs")).scalar()
        for statement in ("INSERT INTO evaluation_runs (run_id, suite, manifest_path, manifest_sha256) VALUES ('x', 'x', 'p', repeat('a', 64))", "UPDATE evaluation_runs SET label = 'x'", "DELETE FROM evaluation_runs"):
            with db.session() as s, pytest.raises(DBAPIError):
                s.execute(text(statement))
                s.commit()


def test_the_migration_refuses_to_drop_a_populated_registry_and_reapplies(settings):
    name = f"eaop_mig14_{uuid.uuid4().hex[:8]}"
    admin = create_engine(settings.url("owner").rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE DATABASE {name}"))
    url = settings.url("owner").rsplit("/", 1)[0] + "/" + name
    cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend" / "migrations"))
    cfg.attributes["url"] = url
    engine = create_engine(url)
    try:
        command.upgrade(cfg, "0014")
        with engine.begin() as c:
            c.execute(text("INSERT INTO evaluation_runs (run_id, suite, manifest_path, manifest_sha256) VALUES ('r', 's', 'evaluation/x/manifest.json', repeat('b', 64))"))
        with pytest.raises(RuntimeError, match="refusing to downgrade 0014"):
            command.downgrade(cfg, "0013")
        with pytest.raises(DBAPIError), engine.begin() as c:  # a malformed checksum and a duplicate path are both refused by constraints
            c.execute(text("INSERT INTO evaluation_runs (run_id, suite, manifest_path, manifest_sha256) VALUES ('r2', 's', 'evaluation/y/manifest.json', 'nothash')"))
        with pytest.raises(DBAPIError), engine.begin() as c:
            c.execute(text("INSERT INTO evaluation_runs (run_id, suite, manifest_path, manifest_sha256) VALUES ('r3', 's', 'evaluation/x/manifest.json', repeat('c', 64))"))
        with engine.begin() as c:
            c.execute(text("DELETE FROM evaluation_runs"))
        command.downgrade(cfg, "0013")
        with engine.connect() as c:
            assert c.execute(text("SELECT to_regclass('evaluation_runs')")).scalar() is None
        command.upgrade(cfg, "head")
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
        admin.dispose()


def test_exposed_registry_fields_of_every_committed_manifest_carry_no_personal_or_tenant_identifiers():
    """GET /evaluation/registry is platform-wide evidence (same artifacts /evaluation/reports already serves to every tenant role with metrics:read). The columns it returns must stay free of emails, UUIDs (tenant/user ids) and absolute local paths."""
    import re
    bad = re.compile(r"[\w.+-]+@[\w-]+\.\w+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[A-Za-z]:[\/]|/(?:home|Users)/", re.I)
    checked = 0
    for p in (ROOT / "evaluation").rglob("manifest.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if not isinstance(d, dict) or not d.get("run_id"):
            continue
        checked += 1
        for k in ("run_id", "label", "experiment", "command", "git_commit"):
            assert not bad.search(str(d.get(k) or "")), (p, k)
        assert not bad.search(str(d["dataset"] if isinstance(d.get("dataset"), str) else "")), p
        assert not bad.search(p.relative_to(ROOT).as_posix()), p
    assert checked >= 30
