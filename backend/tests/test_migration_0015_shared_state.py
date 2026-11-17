"""Migration 0015 (shared rate limits and durable metrics): upgrade, privileges, function behaviour, downgrade guard and re-apply, in a DISPOSABLE database."""
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from support import ROOT


def _cfg(url):
    cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend" / "migrations"))
    cfg.attributes["url"] = url
    return cfg


@pytest.fixture(scope="module")
def scratch(settings):
    name = f"eaop_mig15_{uuid.uuid4().hex[:8]}"
    admin = create_engine(settings.url("owner").rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE DATABASE {name}"))
    url = settings.url("owner").rsplit("/", 1)[0] + "/" + name
    engine = create_engine(url)
    yield {"cfg": _cfg(url), "engine": engine, "name": name}
    engine.dispose()
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
    admin.dispose()


def test_upgrade_creates_the_tables_and_functions_with_the_right_privileges(scratch):
    command.upgrade(scratch["cfg"], "0014")
    command.upgrade(scratch["cfg"], "0015")
    with scratch["engine"].connect() as c:
        tables = {r[0] for r in c.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))}
        assert {"rate_limit_state", "metric_series"} <= tables
        for table in ("rate_limit_state", "metric_series"):
            for role in ("eaop_app", "eaop_worker"):
                assert c.execute(text("SELECT has_table_privilege(:r, :t, 'SELECT') OR has_table_privilege(:r, :t, 'UPDATE') OR has_table_privilege(:r, :t, 'INSERT')"), {"r": role, "t": table}).scalar() is False
        names = [r[0] for r in c.execute(text("SELECT proname FROM pg_proc WHERE proname LIKE 'rate_limit_%' OR proname LIKE 'metric_%' ORDER BY 1"))]
        assert len(names) == 8
        assert c.execute(text("SELECT count(*) FROM pg_proc WHERE (proname LIKE 'rate_limit_%' OR proname LIKE 'metric_%') AND prosecdef AND proconfig::text LIKE '%search_path%'")).scalar() == 8
        for role in ("eaop_app", "eaop_worker"):
            assert c.execute(text("SELECT has_function_privilege(:r, 'rate_limit_take(text, double precision, integer, double precision)', 'EXECUTE')"), {"r": role}).scalar() is True
        assert c.execute(text("SELECT has_function_privilege('public', 'rate_limit_take(text, double precision, integer, double precision)', 'EXECUTE')")).scalar() is False


def test_the_functions_behave_as_specified(scratch):
    with scratch["engine"].begin() as c:
        grants = [c.execute(text("SELECT rate_limit_take('k', 0.001, 3)")).scalar() for _ in range(5)]
        assert grants[:3] == [0, 0, 0] and all(g > 100 for g in grants[3:])  # the fourth caller must wait about 1000 s
        c.execute(text("SELECT rate_limit_pause('p', 5)"))
        assert 0 < c.execute(text("SELECT rate_limit_take('p', 100, 10)")).scalar() <= 5
        assert [c.execute(text("SELECT rate_limit_window_add('w', 60)")).scalar() for _ in range(3)] == [1, 2, 3]
        assert c.execute(text("SELECT rate_limit_window_wait('w', 60, 3)")).scalar() > 0 and c.execute(text("SELECT rate_limit_window_wait('w', 60, 4)")).scalar() == 0
        c.execute(text("SELECT rate_limit_window_clear('w')"))
        assert c.execute(text("SELECT rate_limit_window_wait('w', 60, 3)")).scalar() == 0
        c.execute(text("SELECT metric_add(:k, 'unit_total', '{}'::jsonb, NULL, 2)"), {"k": "a" * 64})
        c.execute(text("SELECT metric_add(:k, 'unit_total', '{}'::jsonb, NULL, 3)"), {"k": "a" * 64})
        assert c.execute(text("SELECT value FROM metric_series WHERE name = 'unit_total'")).scalar() == 5


def test_downgrade_refuses_while_durable_metrics_exist_then_works_and_reapplies(scratch):
    with pytest.raises(RuntimeError, match="refusing to downgrade 0015"):
        command.downgrade(scratch["cfg"], "0014")
    with scratch["engine"].begin() as c:
        c.execute(text("DELETE FROM metric_series"))
    command.downgrade(scratch["cfg"], "0014")
    with scratch["engine"].connect() as c:
        assert c.execute(text("SELECT count(*) FROM pg_tables WHERE tablename IN ('rate_limit_state', 'metric_series')")).scalar() == 0
        assert c.execute(text("SELECT count(*) FROM pg_proc WHERE proname LIKE 'rate_limit_%' OR proname LIKE 'metric_%'")).scalar() == 0
    command.upgrade(scratch["cfg"], "head")
    with scratch["engine"].connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0017"
