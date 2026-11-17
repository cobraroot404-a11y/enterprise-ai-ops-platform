"""Checkpoint A (Batch 10): controlled storage of original document content.

Persistence, integrity, tenant isolation and interruption recovery of `app.ingestion.sources`, on the isolated `eaop_test` database. Higher-level behaviour (upload, retry, reprocessing,
deletion) is in test_source_ingestion.py."""
import hashlib
import uuid

import pytest
from app.ingestion import sources
from sqlalchemy import text
from support import make_tenant

DATA = b"Original pump manual text. Torque the cover bolts to 35 Nm. Marker source-9001."
SHA = hashlib.sha256(DATA).hexdigest()


class Crash(BaseException):
    """A process dying mid-transaction."""


def count(owner_engine, tenant=None):
    with owner_engine.connect() as c:
        return c.execute(text("SELECT count(*) FROM document_sources" + (" WHERE tenant_id = :t" if tenant else "")), {"t": tenant}).scalar()


def put(app_db, tenant, data=DATA, options=None):
    with app_db.session(tenant_id=tenant) as s:
        sid = sources.store(s, tenant_id=tenant, filename="manual.txt", kind="other", media_type="text/plain", data=data, content_hash=hashlib.sha256(data).hexdigest(), parse_options=options)
        s.commit()
    return sid


def test_content_persists_with_its_checksum_and_parse_options_and_reads_back_identically(app_db, worker_db, apex, owner_engine):
    sid = put(app_db, apex.id, options={"id_field": "asset"})
    with app_db.session(tenant_id=apex.id) as s:
        src = sources.load(s, tenant_id=apex.id, source_id=sid)
    assert src.data == DATA and src.content_hash == SHA and src.size_bytes == len(DATA) and src.parse_options == {"id_field": "asset"} and src.media_type == "text/plain"
    with worker_db.session(tenant_id=apex.id) as s:  # the worker reads the same bytes in its own tenant context
        assert sources.load(s, tenant_id=apex.id, source_id=sid).data == DATA


def test_a_caller_cannot_store_content_under_another_contents_checksum(app_db, apex, owner_engine):
    before = count(owner_engine, apex.id)
    with app_db.session(tenant_id=apex.id) as s, pytest.raises(sources.SourceCorrupted):
        sources.store(s, tenant_id=apex.id, filename="x.txt", kind="other", media_type="text/plain", data=b"different", content_hash=SHA)
    assert count(owner_engine, apex.id) == before


def test_corrupted_stored_bytes_are_detected_on_every_read(app_db, apex, owner_engine):
    sid = put(app_db, apex.id)
    with owner_engine.begin() as c:  # only the database owner can alter bytes (the application roles have no UPDATE on them): a simulated storage corruption
        c.execute(text("UPDATE document_sources SET content = :c, size_bytes = :n WHERE id = :i"), {"c": DATA.replace(b"35", b"99"), "n": len(DATA), "i": sid})
    with app_db.session(tenant_id=apex.id) as s, pytest.raises(sources.SourceCorrupted):
        sources.load(s, tenant_id=apex.id, source_id=sid)


def test_another_tenant_and_forged_identifiers_find_nothing(app_db, worker_db, apex, owner_engine):
    other = make_tenant(owner_engine, "srcother")
    sid = put(app_db, apex.id)
    for db in (app_db, worker_db):
        with db.session(tenant_id=other.id) as s:
            with pytest.raises(sources.SourceMissing):
                sources.load(s, tenant_id=other.id, source_id=sid)  # RLS hides the row from the other tenant's context
            with pytest.raises(sources.SourceMissing):
                sources.load(s, tenant_id=apex.id, source_id=sid)  # asking for the right tenant's id inside the wrong context still finds nothing
            with pytest.raises(sources.SourceMissing):
                sources.load(s, tenant_id=other.id, source_id=uuid.uuid4())  # a forged identifier
    with app_db.session(tenant_id=other.id) as s:
        assert sources.release(s, tenant_id=other.id, source_id=sid) == 0 and sources.purge_document(s, tenant_id=other.id, document_id=uuid.uuid4()) == 0
        s.commit()
    with app_db.session(tenant_id=apex.id) as s:
        assert sources.load(s, tenant_id=apex.id, source_id=sid).data == DATA  # untouched


def test_an_interrupted_write_leaves_no_source_behind(app_db, apex, owner_engine):
    before = count(owner_engine, apex.id)
    with app_db.session(tenant_id=apex.id) as s:  # the transaction is rolled back (an error after the source was staged)
        sources.store(s, tenant_id=apex.id, filename="x.txt", kind="other", media_type="text/plain", data=DATA, content_hash=SHA)
        s.rollback()
    assert count(owner_engine, apex.id) == before
    with pytest.raises(Crash):  # the process dies before commit: the connection is dropped, PostgreSQL rolls back
        with app_db.session(tenant_id=apex.id) as s:
            sources.store(s, tenant_id=apex.id, filename="x.txt", kind="other", media_type="text/plain", data=DATA, content_hash=SHA)
            raise Crash()
    assert count(owner_engine, apex.id) == before


def test_release_removes_only_unlinked_sources_and_purge_removes_every_source_of_a_document(app_db, worker_db, apex, owner_engine):
    with owner_engine.begin() as c:
        doc = c.execute(text("INSERT INTO documents (tenant_id, source_key, filename, kind) VALUES (:t, :k, :k, 'other') RETURNING id"), {"t": apex.id, "k": f"src-{uuid.uuid4().hex[:6]}.txt"}).scalar()
    a, b, loose = put(app_db, apex.id, b"first version"), put(app_db, apex.id, b"second version"), put(app_db, apex.id, b"unlinked")
    with app_db.session(tenant_id=apex.id) as s:
        sources.link(s, tenant_id=apex.id, source_id=a, document_id=doc, version=1)
        sources.link(s, tenant_id=apex.id, source_id=b, document_id=doc, version=2)
        assert sources.release(s, tenant_id=apex.id, source_id=a) == 0  # a linked source is never released as "unused"
        assert sources.release(s, tenant_id=apex.id, source_id=loose) == 1
        s.commit()
    with worker_db.session(tenant_id=apex.id) as s:
        assert sources.remaining(s, tenant_id=apex.id, document_id=doc) == 2
        assert sources.purge_document(s, tenant_id=apex.id, document_id=doc) == 2
        s.commit()
        assert sources.remaining(s, tenant_id=apex.id, document_id=doc) == 0
