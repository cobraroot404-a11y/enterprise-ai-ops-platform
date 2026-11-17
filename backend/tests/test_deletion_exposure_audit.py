"""Batch 9 follow-up audit of the Batch 8 deletion lifecycle: what is PHYSICALLY REMOVED, what is merely made INACCESSIBLE, and what REMAINS (documented exposure).

This is a characterisation of current behaviour, kept in step with docs/architecture/document-lifecycle.md (section "Exposure register"). If a remaining item is later removed, update the
assertion and the register together: the test exists so the documentation cannot drift from reality in either direction."""
from app.workflows import worker
from support import login
from test_ingestion_jobs import FAST, NOTE, sql, upload  # noqa: F401  (shared helpers)


def test_what_deletion_removes_makes_inaccessible_and_leaves_behind(client, apex, ticketing, owner_engine, worker_db):
    eng, sup = login(client, apex, "support_engineer"), login(client, apex, "maintenance_supervisor")
    doc = upload(client, eng, name="exposure.txt", data=NOTE).json()["document_id"]
    sha = sql(owner_engine, "SELECT content_hash FROM document_versions WHERE document_id = :d", d=doc)[0][0]
    assert client.delete(f"/api/v1/documents/{doc}", headers=sup).status_code == 200
    assert worker.drain(worker_db, FAST) == ["cleanup_completed"]
    # PHYSICALLY REMOVED from the database: parsed text, chunks, embeddings, text-search vectors (generated column of the chunk row), versions
    assert sql(owner_engine, "SELECT count(*) FROM document_chunks WHERE document_id = :d", d=doc)[0][0] == 0
    assert sql(owner_engine, "SELECT count(*) FROM document_versions WHERE document_id = :d", d=doc)[0][0] == 0
    # The ONLY store of original bytes is document_sources (Batch 10); nothing else keeps a copy of the text (no file store, no raw/body/blob columns, no result cache), and its rows for the document are gone
    columns = {(r[0], r[1]) for r in sql(owner_engine, "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public' AND data_type IN ('bytea', 'text')")}
    assert [c for c in columns if c[1] in ("content", "original", "raw", "bytes", "body", "blob")] == [("document_sources", "content")]
    assert sql(owner_engine, "SELECT count(*) FROM document_sources WHERE document_id = :d OR content = :c", d=doc, c=NOTE)[0][0] == 0
    # INACCESSIBLE: no listing, no direct fetch, no search hit, no citation lookup (proved in test_document_lifecycle), and the job payload (parsed text) is gone
    assert client.get(f"/api/v1/documents/{doc}", headers=eng).status_code == 404
    assert sql(owner_engine, "SELECT count(*) FROM ingestion_jobs WHERE payload IS NOT NULL")[0][0] == 0
    # REMAINS (documented exposure register, document-lifecycle.md):
    #  EXP-01 the audit event of the original upload keeps the file name and the SHA-256 of the content (identifies the content, is not the content)
    created = sql(owner_engine, "SELECT details FROM audit_events WHERE action = 'document.created' AND entity_id = :d", d=doc)[0][0]
    assert created["sha256"] == sha and created["filename"] == "exposure.txt"
    #  EXP-02 the ingestion job keeps its idempotency reference, which embeds the same SHA-256, and the file name
    job = sql(owner_engine, "SELECT idempotency_key, filename FROM ingestion_jobs WHERE document_id = :d", d=doc)[0]
    assert job[0] == f"ingest:{sha}" and job[1] == "exposure.txt"
    #  EXP-03 the document tombstone keeps file name and kind (identification of what was deleted)
    assert sql(owner_engine, "SELECT filename, kind, lifecycle_status, cleanup_state FROM documents WHERE id = :d", d=doc)[0] == ("exposure.txt", "other", "deleted", "completed")
    #  The text itself appears in no audit event of the deletion or the cleanup
    texts = sql(owner_engine, "SELECT details::text FROM audit_events WHERE entity_id = :d", d=doc)
    assert not [t for t in texts if "zebra-quartz" in t[0] or "gasket" in t[0].lower()]
    # Not testable here and stated in the register: dead tuples remain in PostgreSQL storage until VACUUM; database backups taken earlier keep the data.
    assert sql(owner_engine, "SELECT count(*) FROM pg_stat_user_tables WHERE relname = 'document_chunks'")[0][0] == 1


def test_cleanup_removes_every_generation_of_a_reprocessed_document(client, apex, ticketing, owner_engine, worker_db):
    eng, sup = login(client, apex, "support_engineer"), login(client, apex, "maintenance_supervisor")
    doc = upload(client, eng, name="generations.txt", data=NOTE).json()["document_id"]
    client.post(f"/api/v1/documents/{doc}/reprocess", headers=sup)
    assert worker.drain(worker_db, FAST) == ["ingestion_completed"]
    assert sql(owner_engine, "SELECT count(DISTINCT generation) FROM document_chunks WHERE document_id = :d", d=doc)[0][0] == 2
    client.delete(f"/api/v1/documents/{doc}", headers=sup)
    assert worker.drain(worker_db, FAST) == ["cleanup_completed"]
    assert sql(owner_engine, "SELECT count(*) FROM document_chunks WHERE document_id = :d", d=doc)[0][0] == 0  # retired generations are removed too
