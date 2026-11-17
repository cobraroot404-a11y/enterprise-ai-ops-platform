#!/usr/bin/env python
"""Capture EXPLAIN (ANALYZE, BUFFERS) evidence for representative tenant-scoped queries before and after migration 0008 (V41-17.03-IDX).

    python scripts/index_query_plans.py [--tenants 10] [--incidents-per-tenant 20000]

Builds a DISPOSABLE database, migrates to 0007, loads a synthetic multi-tenant dataset, records plans, upgrades to 0008, records plans again, writes
evaluation/api-quality/index-query-plans.json and drops the database. Queries run as the owner role with an explicit tenant predicate (the shape the application
issues; row-level security adds a tenant predicate on top and is exercised by the migration tests, not here). Performance numbers are measurements of THIS machine and
dataset; they are kept separate from schema correctness and are not production claims."""
import argparse
import json
import statistics
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.config import get_settings  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

OUT = ROOT / "evaluation" / "api-quality" / "index-query-plans.json"
QUERIES = {
    "Q1 incidents: newest 50 for a tenant": "SELECT * FROM incidents WHERE tenant_id = :t ORDER BY created_at DESC LIMIT 50",
    "Q2 incidents: newest 50 needing review": "SELECT * FROM incidents WHERE tenant_id = :t AND review_status = 'needs_review' ORDER BY created_at DESC LIMIT 50",
    "Q3 incidents: tenant count": "SELECT count(*) FROM incidents WHERE tenant_id = :t",
    "Q4 approvals: newest 50 decisions for a tenant": "SELECT * FROM approvals WHERE tenant_id = :t ORDER BY decided_at DESC LIMIT 50",
    "Q5 outbox: newest 50 events for a tenant": "SELECT * FROM outbox_events WHERE tenant_id = :t ORDER BY id DESC LIMIT 50",
    "Q6 outbox: newest 50 dead letters for a tenant": "SELECT * FROM outbox_events WHERE tenant_id = :t AND status = 'dead' ORDER BY id DESC LIMIT 50",
}


def walk(node, acc):
    acc.append({"node": node.get("Node Type"), "relation": node.get("Relation Name"), "index": node.get("Index Name")})
    for child in node.get("Plans", []):
        walk(child, acc)


def load(engine, tenants, per_tenant):
    with engine.begin() as c:
        c.execute(text("INSERT INTO users (id, email, full_name, password_hash) VALUES (gen_random_uuid(), 'bench@example.test', 'Bench', 'x')"))
        # a SMALL tenant whose rows are the oldest in every table: its "newest" rows sit far from the end of the primary key and of created_at order
        c.execute(text("INSERT INTO tenants (slug, name) VALUES ('small-1', 'Small tenant')"))
        c.execute(text("INSERT INTO incidents (tenant_id, asset_id, category, symptoms, priority, review_status, recommended_action, report_text, extraction_backend, created_by, created_at) "
                       "SELECT (SELECT id FROM tenants WHERE slug = 'small-1'), 'P-1', 'mechanical_vibration', '[]', 'P3', CASE WHEN g % 10 = 0 THEN 'needs_review' ELSE 'pending_review' END, 'check', 'report', 'bench', "
                       "(SELECT id FROM users LIMIT 1), now() - interval '400 days' + (g || ' minutes')::interval FROM generate_series(1, 40) g"))
        c.execute(text("INSERT INTO outbox_events (tenant_id, topic, aggregate_id, status) SELECT (SELECT id FROM tenants WHERE slug = 'small-1'), 'ticket.submit', gen_random_uuid(), "
                       "CASE WHEN g % 25 = 0 THEN 'dead' ELSE 'done' END FROM generate_series(1, 50) g"))
        c.execute(text("INSERT INTO tenants (slug, name) SELECT 'bench-' || g, 'Bench ' || g FROM generate_series(1, :n) g"), {"n": tenants})
        c.execute(text("INSERT INTO incidents (tenant_id, asset_id, category, symptoms, priority, review_status, recommended_action, report_text, extraction_backend, created_by, created_at) "
                       "SELECT t.id, 'P-' || (g % 50), 'mechanical_vibration', '[]', 'P3', CASE WHEN g % 10 = 0 THEN 'needs_review' ELSE 'pending_review' END, 'check', 'report', 'bench', "
                       "(SELECT id FROM users LIMIT 1), now() - (g || ' minutes')::interval FROM tenants t, generate_series(1, :n) g WHERE t.slug LIKE 'bench-%'"), {"n": per_tenant})
        c.execute(text("INSERT INTO tickets (tenant_id, incident_id, title, description, priority, state, created_by) "
                       "SELECT tenant_id, id, 'x', 'y', 'P3', 'APPROVED', created_by FROM (SELECT *, row_number() OVER (PARTITION BY tenant_id ORDER BY created_at) rn FROM incidents) i WHERE rn <= :k"),
                  {"k": per_tenant // 4})
        c.execute(text("INSERT INTO approvals (tenant_id, ticket_id, decision, decided_by, decided_at) SELECT t.tenant_id, t.id, 'approved', t.created_by, i.created_at + interval '1 hour' FROM tickets t JOIN incidents i ON i.id = t.incident_id"))
        c.execute(text("INSERT INTO outbox_events (tenant_id, topic, aggregate_id, status) SELECT t.id, 'ticket.submit', gen_random_uuid(), CASE WHEN g % 400 = 0 THEN 'dead' ELSE 'done' END "
                       "FROM tenants t, generate_series(1, :n) g WHERE t.slug LIKE 'bench-%'"), {"n": per_tenant // 2})
    raw = engine.raw_connection()
    raw.autocommit = True
    cur = raw.cursor()
    cur.execute("VACUUM ANALYZE")
    raw.close()


def measure(engine, tenant_id):
    results = {}
    with engine.connect() as c:
        for name, sql in QUERIES.items():
            times, plan_json, buffers = [], None, None
            for _ in range(7):
                plan_json = c.execute(text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql), {"t": tenant_id}).scalar()
                root = plan_json[0]
                times.append(root["Execution Time"])
                buffers = {k: root["Plan"].get(k) for k in ("Shared Hit Blocks", "Shared Read Blocks")}
            nodes = []
            walk(plan_json[0]["Plan"], nodes)
            results[name] = {"median_execution_ms": round(statistics.median(times), 3), "min_ms": round(min(times), 3), "max_ms": round(max(times), 3), "planning_ms": round(plan_json[0]["Planning Time"], 3),
                             "buffers": buffers, "plan_nodes": nodes, "uses_new_index": any((n["index"] or "").endswith(("tenant_created_idx", "tenant_decided_idx", "tenant_id_idx")) for n in nodes),
                             "scan_summary": " > ".join(f"{n['node']}{'(' + n['index'] + ')' if n['index'] else ('(' + n['relation'] + ')' if n['relation'] else '')}" for n in nodes)}
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenants", type=int, default=10)
    ap.add_argument("--incidents-per-tenant", type=int, default=20000)
    args = ap.parse_args()
    settings = get_settings()
    base = settings.url("owner").rsplit("/", 1)[0]
    name = f"eaop_plans_{uuid.uuid4().hex[:8]}"
    admin = create_engine(base + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE DATABASE {name}"))
    cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend" / "migrations"))
    cfg.attributes["url"] = base + "/" + name
    engine = create_engine(base + "/" + name, isolation_level="AUTOCOMMIT")
    try:
        command.upgrade(cfg, "0007")
        load(engine, args.tenants, args.incidents_per_tenant)
        with engine.connect() as c:
            tenant = str(c.execute(text("SELECT id FROM tenants WHERE slug = 'bench-1'")).scalar())
            sizes = {t: c.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in ("incidents", "approvals", "outbox_events", "tickets", "tenants")}
            version = c.execute(text("SHOW server_version")).scalar()
            settings_used = {k: c.execute(text(f"SHOW {k}")).scalar() for k in ("shared_buffers", "work_mem", "random_page_cost")}
        with engine.connect() as c:
            small = str(c.execute(text("SELECT id FROM tenants WHERE slug = 'small-1'")).scalar())
        before = {"large": measure(engine, tenant), "small": measure(engine, small)}
        command.upgrade(cfg, "0008")
        raw = engine.raw_connection()
        raw.autocommit = True
        raw.cursor().execute("VACUUM ANALYZE")
        raw.close()
        after = {"large": measure(engine, tenant), "small": measure(engine, small)}
        with engine.connect() as c:
            index_sizes = {r[0]: r[1] for r in c.execute(text("SELECT indexrelname, pg_size_pretty(pg_relation_size(indexrelid)) FROM pg_stat_user_indexes WHERE indexrelname IN "
                                                              "('incidents_tenant_created_idx', 'approvals_tenant_decided_idx', 'outbox_events_tenant_id_idx')"))}
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
    comparison = {}
    for kind in ("large", "small"):
        comparison[kind] = {q: {"before_ms": before[kind][q]["median_execution_ms"], "after_ms": after[kind][q]["median_execution_ms"], "before_scan": before[kind][q]["scan_summary"],
                                "after_scan": after[kind][q]["scan_summary"], "after_uses_new_index": after[kind][q]["uses_new_index"], "before_buffers": before[kind][q]["buffers"],
                                "after_buffers": after[kind][q]["buffers"]} for q in QUERIES}
    evidence = {"requirement": "V41-17.03 (index defect V41-17.03-IDX)", "generated_at": datetime.now(timezone(timedelta(hours=-5))).isoformat(timespec="seconds") + " (EST)", "postgres_version": version,
                "settings": settings_used, "dataset_rows": sizes, "tenants": args.tenants, "queried_tenant_rows": {"large": args.incidents_per_tenant, "small": 40}, "new_index_sizes": index_sizes, "runs_per_query": 7,
                "queries": comparison,
                "notes": ["Disposable database, synthetic data, owner role with an explicit tenant predicate; row-level security is verified separately by the migration tests.",
                          "Medians of 7 runs on one laptop (warm cache); numbers are not production claims and no improvement is asserted beyond what is shown.",
                          "'large' is a tenant with the full per-tenant row count interleaved with the others; 'small' has 40 incidents and 50 outbox events that are the OLDEST rows in their tables, the case where a tenant-leading index matters most.",
                          "The worker's cross-tenant claim query is not tenant-scoped and is not covered by these indexes.",
                          "PostgreSQL may choose a sequential or bitmap scan on small data; this dataset is large enough (200k incident rows by default) to make the choice meaningful but is still synthetic."]}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(evidence, indent=1) + "\n", encoding="utf-8", newline="\n")
    for kind, qs in comparison.items():
        for q, v in qs.items():
            print(f"[{kind}] {q}: {v['before_ms']} ms -> {v['after_ms']} ms | after: {v['after_scan']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
