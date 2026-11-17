"""Batch 11B: the CSV connector (V41-11.01 CSV part, V41-12.01 CSV record ingestion): a CSV file fetched over HTTP from the connector's own base URL, one document per data row, through the
same durable sync job, retained originals, idempotency and tombstones as REST. Real HTTP to the local records mock; all failures are controlled injections."""
import json
import uuid

import pytest
from app.connectors.http import HttpConnector
from app.connectors.rest_records import CsvSource, PageState, SourceError, parse_csv_config, parse_csv_records
from app.core.errors import Invalid
from app.workflows import worker
from support import RECORDS_KEY
from test_ingestion_jobs import FAST, db_clean, hits, job_list, make_due, sql, world  # noqa: F401
from test_rest_sync import docs, fresh_mock, inject, start  # noqa: F401

TENANT = str(uuid.uuid4())
ENV = "CSV_TEST_KEY"


def cfg(**over):
    base = {"csv": {"path": "/v1/apex/csv", "id_field": "id", "required_fields": ["title", "body"], "rate": {"requests_per_second": 50, "burst": 20}}}
    base["csv"].update(over)
    return base


def csv_source(records_server, config, key=RECORDS_KEY, timeout=3.0):
    return CsvSource(HttpConnector(records_server.url, api_key=key, timeout=timeout, tenant_slug="*", tenant_id=TENANT), parse_csv_config(config), tenant_id=TENANT, connector_id=uuid.uuid4())


def csv_connector(client, world, records_server, name=None, dataset="apex", **over):
    config = cfg(**over)
    config["csv"]["path"] = f"/v1/{dataset}/csv"
    r = client.post("/api/v1/connectors", headers=world["adm"], json={"kind": "csv", "name": name or f"csv-{uuid.uuid4().hex[:6]}", "base_url": records_server.url, "secret_ref": ENV, "config": config})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv(ENV, RECORDS_KEY)


def finish(client, world, worker_db, job_id):
    worker.drain(worker_db, FAST)
    return client.get(f"/api/v1/ingestion/jobs/{job_id}", headers=world["eng"]).json()


# ----------------------------------------------------------------------------------------------------------------------- parsing rules (no network)
def parse(raw: bytes, **over):
    return parse_csv_records(raw, parse_csv_config(cfg(**over)))


def test_parsing_is_deterministic_bounded_and_never_interprets_cells():
    records, stats = parse(b"\xef\xbb\xbfid,title,body\nA-1,=SUM(A1:A9),+cmd|' /C calc'!A0\nA-2,@HYPERLINK(\"x\"),-2+3\n")
    assert [(n, r["id"]) for n, r in records] == [(1, "A-1"), (2, "A-2")] and stats == {"malformed": 0, "blank": 0, "truncated": False}
    assert records[0][1]["title"] == "=SUM(A1:A9)" and records[1][1]["body"] == "-2+3"  # formula-looking text is data and stays text; the platform never writes CSV or spreadsheets from it
    records, stats = parse(b"id,title,body\nA-1,ok,fine\nA-2,short\n\nA-3,long,fine,extra\nA-4,\"quoted, comma\",fine\n")
    assert [r["id"] for _, r in records] == ["A-1", "A-4"] and stats["malformed"] == 2 and stats["blank"] == 1  # wrong cell counts are rejected and counted, blank lines skipped
    assert records[1][0] == 5 and records[1][1]["title"] == "quoted, comma"  # row number = position in the file (header is row 0)
    records, stats = parse(b"id,title,body\n" + b"".join(f"R-{i},t,b\n".encode() for i in range(12)), max_rows=5)
    assert len(records) == 5 and stats["truncated"] is True
    big = b"id,title,body\nA-1,t," + b"x" * 9000 + b"\nA-2,t,ok\n"
    records, stats = parse(big, max_cell_bytes=8192)
    assert [r["id"] for _, r in records] == ["A-2"] and stats["malformed"] == 1  # an oversize cell is a malformed row, not a memory problem
    assert parse(b"id;title;body\nA-1;t;b\n", delimiter=";")[0][0][1]["title"] == "t"


@pytest.mark.parametrize("raw", [b"", b"\xff\xfeid,title\n", b"id,title,body\x00\nA,b,c\n", b"id,id,body\nA,B,C\n", b"title,body\nt,b\n", b"id,ti tle\x01,body\nA,b,c\n", b"id,\"unterminated\nA,b,c\n"])
def test_unusable_files_fail_with_a_fixed_schema_code(raw):
    with pytest.raises(SourceError) as err:
        parse(raw)
    assert err.value.code == "source_schema_invalid" and not err.value.transient


@pytest.mark.parametrize("bad", [{"path": "http://evil.example/x.csv"}, {"path": "//evil/x"}, {"path": "/a/../b"}, {"id_field": "bad;field"}, {"max_rows": 0}, {"max_rows": 99999}, {"max_bytes": 10 ** 9},
                                  {"delimiter": "|"}, {"reject_policy": "x"}, {"unknown": 1}])
def test_invalid_csv_configuration_is_rejected_without_echoing_values(bad):
    with pytest.raises(Invalid) as err:
        parse_csv_config(cfg(**bad))
    assert err.value.code == "invalid_connector_config" and "evil" not in str(err.value)
    with pytest.raises(Invalid):
        parse_csv_config({})


# ----------------------------------------------------------------------------------------------------------------------- the source over real HTTP
def test_the_csv_file_is_fetched_over_http_with_the_key_and_parsed(records_server):
    page = csv_source(records_server, cfg()).fetch_page(PageState())
    assert [r["id"] for r in page.records] == [f"APX-N-{i:03d}" for i in range(1, 8)] and page.row_numbers == list(range(1, 8)) and page.state.done and page.malformed == 0
    seen = records_server.state.requests
    assert len(seen) == 1 and seen[0]["mode"] == "csv" and seen[0]["key_ok"] is True


def test_csv_source_failures_are_classified_like_rest(records_server):
    with pytest.raises(SourceError) as err:
        csv_source(records_server, cfg(), key="wrong").fetch_page(PageState())
    assert err.value.code == "source_unauthorized" and not err.value.transient
    for mode, code, transient in (("503", "source_unavailable", True), ("redirect", "source_rejected", False), ("bad_encoding", "source_schema_invalid", False), ("no_id_column", "source_schema_invalid", False)):
        inject(records_server, mode, count=5 if mode == "503" else 1)
        with pytest.raises(SourceError) as err:
            csv_source(records_server, cfg()).fetch_page(PageState())
        assert err.value.code == code and err.value.transient is transient, mode
        with records_server.state.lock:
            records_server.state.failures.clear()
    with records_server.state.lock:
        records_server.state.datasets["apex"] = [{"id": "BIG", "title": "t", "body": "x" * 4000}] * 400  # larger than the configured byte bound
    with pytest.raises(SourceError) as err:
        csv_source(records_server, cfg(max_bytes=65536)).fetch_page(PageState())
    assert err.value.code == "source_schema_invalid"


def test_the_csv_probe_reads_only_a_bounded_head_and_checks_the_header(records_server):
    assert csv_source(records_server, cfg()).probe()["status"] == "ok"
    assert csv_source(records_server, cfg(id_field="missing_column")).probe()["status"] == "schema"
    assert csv_source(records_server, cfg(), key="wrong").probe()["status"] == "authentication"


# ----------------------------------------------------------------------------------------------------------------------- durable CSV synchronisation
def test_a_csv_sync_ingests_every_row_with_row_provenance_and_is_idempotent(client, world, records_server, owner_engine, worker_db):
    cid = csv_connector(client, world, records_server)
    job = start(client, world, cid)
    assert job["job_type"] == "sync" and job["status"] == "QUEUED"
    done = finish(client, world, worker_db, job["id"])
    assert done["status"] == "COMPLETED" and done["outcome"] == "synced" and done["sync"]["created"] == 7 and done["sync"]["seen"] == 7
    assert sorted(d[0][:4] for d in docs_csv(owner_engine, world)) == ["csv-"] * 7
    rows = sql(owner_engine, "SELECT source_record_id, source_row FROM connector_sync_records WHERE tenant_id = :t ORDER BY source_row", t=world["t"].id)
    assert rows == [(f"APX-N-{i:03d}", i) for i in range(1, 8)]  # row provenance next to the record identifier
    assert sql(owner_engine, "SELECT c.record_id FROM document_chunks c JOIN documents d ON d.id = c.document_id WHERE d.tenant_id = :t AND d.filename LIKE '%APX-N-001%'", t=world["t"].id)[0][0] == "APX-N-001"
    assert any("seal" in h["text"].lower() for h in hits(client, world["eng"], "mechanical seal weeps pump P-101"))
    again = finish(client, world, worker_db, start(client, world, cid)["id"])
    assert again["sync"]["unchanged"] == 7 and again["sync"]["created"] == 0
    with records_server.state.lock:  # a row is inserted at the top: every row number shifts, but record identity (not position) decides what changed
        records_server.state.datasets["apex"].insert(0, {"id": "APX-N-000", "title": "New first row", "body": "A row that pushes every other row down."})
    shifted = finish(client, world, worker_db, start(client, world, cid)["id"])
    assert shifted["sync"]["created"] == 1 and shifted["sync"]["unchanged"] == 7 and shifted["sync"]["updated"] == 0
    assert sql(owner_engine, "SELECT source_row FROM connector_sync_records WHERE tenant_id = :t AND source_record_id = 'APX-N-007'", t=world["t"].id)[0][0] == 8  # the provenance row follows the file


def docs_csv(owner_engine, world):
    return sql(owner_engine, "SELECT filename FROM documents WHERE tenant_id = :t AND lifecycle_status = 'active' AND filename LIKE 'csv-%'", t=world["t"].id)


def test_malformed_rows_and_a_bom_are_handled_deterministically_and_reported(client, world, records_server, owner_engine, worker_db):
    inject(records_server, "bad_csv")
    cid = csv_connector(client, world, records_server)
    done = finish(client, world, worker_db, start(client, world, cid)["id"])
    assert done["status"] == "COMPLETED" and done["outcome"] == "synced_with_rejections"
    assert done["sync"]["created"] == 2 and done["sync"]["invalid"] == 2 and done["sync"]["rejections"] == {"malformed_row": 2}  # C-1 and the quoted-comma row; the short and long rows rejected
    ids = sorted(r[0] for r in sql(owner_engine, "SELECT source_record_id FROM connector_sync_records WHERE tenant_id = :t", t=world["t"].id))
    assert ids == ["C-1", "C-4"]
    strict = csv_connector(client, world, records_server, name="strict-csv", reject_policy="fail")
    inject(records_server, "bad_csv")
    failed = finish(client, world, worker_db, start(client, world, strict)["id"])
    assert failed["status"] == "FAILED" and failed["error_code"] == "source_record_invalid" and failed["attempts"] == 1


def test_unusable_files_and_upstream_failures_fail_or_retry_with_fixed_codes(client, world, records_server, owner_engine, worker_db):
    cid = csv_connector(client, world, records_server)
    for mode in ("bad_encoding", "no_id_column"):
        inject(records_server, mode)
        j = finish(client, world, worker_db, start(client, world, cid)["id"])
        assert j["status"] == "FAILED" and j["error_code"] == "source_schema_invalid" and j["attempts"] == 1, mode
    inject(records_server, "503", count=3)  # one job attempt exhausts its three page attempts, then the job retries with backoff and succeeds
    job = start(client, world, cid)
    assert worker.drain(worker_db, FAST, max_iterations=1) == ["ingestion_retry_scheduled"]
    assert client.get(f"/api/v1/ingestion/jobs/{job['id']}", headers=world["eng"]).json()["error_code"] == "source_unavailable"
    make_due(owner_engine)
    done = finish(client, world, worker_db, job["id"])
    assert done["status"] == "COMPLETED" and done["attempts"] == 2 and done["sync"]["created"] == 7


def test_the_row_limit_truncates_and_says_so(client, world, records_server, owner_engine, worker_db):
    cid = csv_connector(client, world, records_server, max_rows=4)
    done = finish(client, world, worker_db, start(client, world, cid)["id"])
    assert done["outcome"] == "synced_truncated" and done["sync"]["created"] == 4 and done["sync"]["truncated"] is True


def test_csv_deletions_are_tombstones_and_formula_text_stays_inert(client, world, records_server, owner_engine, worker_db):
    with records_server.state.lock:
        records_server.state.datasets["apex"] = [{"id": "F-1", "title": "=HYPERLINK(\"http://x\",\"y\")", "body": "+cmd|' /C calc'!A0"}, {"id": "F-2", "title": "Second", "body": "Plain row about pumps."}]
    cid = csv_connector(client, world, records_server)
    finish(client, world, worker_db, start(client, world, cid)["id"])
    stored = sql(owner_engine, "SELECT d.filename, convert_from(s.content, 'UTF8') FROM documents d JOIN document_versions v ON v.document_id = d.id JOIN document_sources s ON s.id = v.source_id WHERE d.tenant_id = :t AND d.filename LIKE '%F-1%'", t=world["t"].id)[0]
    assert "=HYPERLINK" in stored[1] and json.loads(stored[1])[0]["title"].startswith("=")  # stored verbatim as data
    doc = sql(owner_engine, "SELECT document_id::text FROM connector_sync_records WHERE tenant_id = :t AND source_record_id = 'F-2'", t=world["t"].id)[0][0]
    assert client.delete(f"/api/v1/documents/{doc}", headers=world["sup"]).status_code == 200
    worker.drain(worker_db, FAST)
    with records_server.state.lock:
        records_server.state.datasets["apex"][1]["body"] = "Changed content after the customer deleted this row."
    j = finish(client, world, worker_db, start(client, world, cid)["id"])
    assert j["sync"]["tombstoned_changed"] == 1 and j["sync"]["created"] == 0 and client.get(f"/api/v1/documents/{doc}", headers=world["eng"]).status_code == 404


def test_csv_connectors_are_validated_probed_and_isolated(client, world, records_server, owner_engine, worker_db):
    bad = client.post("/api/v1/connectors", headers=world["adm"], json={"kind": "csv", "name": "bad-csv", "base_url": records_server.url, "config": {"csv": {"path": "//x/y", "id_field": "id"}}})
    assert bad.status_code == 422 and "//x/y" not in bad.text
    assert client.post("/api/v1/connectors", headers=world["adm"], json={"kind": "rest", "name": "wrong-kind", "base_url": records_server.url, "config": cfg()}).status_code == 422
    cid = csv_connector(client, world, records_server)
    probed = {i["id"]: i for i in client.get("/api/v1/connectors/health", headers=world["adm"], params={"probe": "true"}).json()["items"]}
    assert probed[cid]["live_probe"]["status"] == "ok" and probed[cid]["status"] == "ok"
    for who in ("eng", "aud"):
        assert client.post(f"/api/v1/connectors/{cid}/sync", headers=world[who]).status_code == 403
    from support import login, make_tenant
    other = make_tenant(owner_engine, "csvother")
    assert client.post(f"/api/v1/connectors/{cid}/sync", headers=login(client, other, "tenant_admin")).status_code == 404
    blob = json.dumps(job_list(client, world["eng"])) + json.dumps(client.get("/api/v1/audit", headers=world["aud"], params={"limit": 100}).json())
    assert RECORDS_KEY not in blob
