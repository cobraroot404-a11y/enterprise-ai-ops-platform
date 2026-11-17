import pytest
from app.ai.embeddings import DeterministicEmbedder
from app.ingestion.service import ingest
from app.retrieval.profiles import IncompatibleEmbeddingModel
from app.retrieval.reindex import reindex_tenant
from app.retrieval.search import search
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from support import SAMPLE_KINDS, SAMPLES, make_tenant

V1, V2 = DeterministicEmbedder("1"), DeterministicEmbedder("2")


def _user(owner_engine, tenant) -> str:
    with owner_engine.connect() as conn:
        return str(conn.execute(text("SELECT id FROM users WHERE email = :e"),
                                {"e": tenant.users["support_engineer"]}).scalar())


def _load(app_db, owner_engine, tenant, embedder=V1):
    uid = _user(owner_engine, tenant)
    with app_db.session(tenant.id, uid) as s:
        for name, kind in SAMPLE_KINDS.items():
            ingest(s, tenant_id=tenant.id, user_id=uid, filename=name, data=(SAMPLES / name).read_bytes(),
                   kind=kind, embedder=embedder)
        s.commit()
    return uid


@pytest.fixture()
def pair(owner_engine):
    return make_tenant(owner_engine, "epa"), make_tenant(owner_engine, "epb")


def _snapshot(app_db, tenant):
    with app_db.session(tenant.id) as s:
        rows = s.execute(text("SELECT document_id, chunk_index, page_number, record_id, text, version "
                              "FROM document_chunks ORDER BY document_id, version, chunk_index")).all()
        profiles = s.execute(text("SELECT provider, revision, active FROM embedding_profiles")).all()
        return [tuple(r) for r in rows], [tuple(p) for p in profiles]


def test_first_ingest_creates_active_profile_and_tags_chunks(app_db, owner_engine, pair):
    a, _ = pair
    _load(app_db, owner_engine, a)
    with app_db.session(a.id) as s:
        active = s.execute(text("SELECT provider, model, revision, dim FROM embedding_profiles WHERE active")).all()
        assert active == [("deterministic", "hashed-bow-test-only", "1", 384)]
        assert s.execute(text("SELECT count(*) FROM document_chunks c JOIN embedding_profiles p "
                              "ON p.id = c.embedding_profile_id AND p.active")).scalar() == \
            s.execute(text("SELECT count(*) FROM document_chunks")).scalar() > 0


def test_models_cannot_be_mixed_or_queried_with_incompatible_embedder(app_db, owner_engine, pair):
    a, _ = pair
    uid = _load(app_db, owner_engine, a)
    with app_db.session(a.id, uid) as s:
        with pytest.raises(IncompatibleEmbeddingModel):
            ingest(s, tenant_id=a.id, user_id=uid, filename="extra.txt", data=b"another note about pumps",
                   kind="other", embedder=V2)
        s.rollback()
    with app_db.session(a.id, uid) as s, pytest.raises(IncompatibleEmbeddingModel) as err:
        search(s, a.id, "pump vibration", V2)
    assert err.value.code == "embedding_model_mismatch" and err.value.status_code == 409
    with app_db.session(a.id, uid) as s:  # the matching embedder still works
        assert search(s, a.id, "pump vibration", V1)


def test_reindex_migrates_everything_and_preserves_provenance(app_db, owner_engine, pair):
    a, b = pair
    uid = _load(app_db, owner_engine, a)
    _load(app_db, owner_engine, b)
    chunks_before, _ = _snapshot(app_db, a)
    b_before = _snapshot(app_db, b)
    with app_db.session(a.id, uid) as s:
        before_hits = [h.chunk_id for h in search(s, a.id, "drive-end bearing vibration 7.1 mm/s", V1, k=3)]
        report = reindex_tenant(s, a.id, V2, actor_id=uid)
        s.commit()
    assert report["status"] == "reindexed"
    assert report["before"]["chunks"] == report["after"]["chunks"] == len(chunks_before)
    assert report["before"]["documents"] == report["after"]["documents"]
    assert report["after"]["dim384"] == report["after"]["chunks"]

    chunks_after, profiles = _snapshot(app_db, a)
    assert chunks_after == chunks_before  # text, pages, record ids, versions untouched
    assert sorted(profiles) == [("deterministic", "1", False), ("deterministic", "2", True)]
    with app_db.session(a.id, uid) as s:
        assert s.execute(text("SELECT count(*) FROM document_chunks c JOIN embedding_profiles p "
                              "ON p.id = c.embedding_profile_id WHERE NOT p.active")).scalar() == 0  # no mixing
        with pytest.raises(IncompatibleEmbeddingModel):
            search(s, a.id, "pump vibration", V1)
        after_hits = search(s, a.id, "drive-end bearing vibration 7.1 mm/s", V2, k=3)
        assert after_hits and after_hits[0].page_number == 2
        assert [h.chunk_id for h in after_hits[:1]] == before_hits[:1]
        assert s.execute(text("SELECT count(*) FROM audit_events WHERE action = 'embeddings.reindexed'")).scalar() == 1
        assert reindex_tenant(s, a.id, V2)["status"] == "already_active"  # repeatable / idempotent
    assert _snapshot(app_db, b) == b_before  # other tenant untouched (still on revision 1)


def test_reindex_is_atomic_when_embedding_fails(app_db, owner_engine, pair):
    a, _ = pair
    uid = _load(app_db, owner_engine, a)
    before = _snapshot(app_db, a)

    class Flaky(DeterministicEmbedder):
        calls = 0

        def embed(self, texts):
            Flaky.calls += 1
            if Flaky.calls == 2:
                raise RuntimeError("model crashed mid-migration")
            return super().embed(texts)

    original_batch = reindex_tenant.__globals__["BATCH"]
    reindex_tenant.__globals__["BATCH"] = 4  # force several batches so the failure lands mid-way
    try:
        with app_db.session(a.id, uid) as s, pytest.raises(RuntimeError):
            reindex_tenant(s, a.id, Flaky("3"))
            s.commit()
    finally:
        reindex_tenant.__globals__["BATCH"] = original_batch
    assert _snapshot(app_db, a) == before  # old profile still the only one, still active
    with app_db.session(a.id, uid) as s:
        assert search(s, a.id, "pump vibration", V1)


def test_database_allows_only_one_active_profile_and_384_dims(owner_engine, pair):
    a, _ = pair
    with owner_engine.begin() as conn:
        conn.execute(text("INSERT INTO embedding_profiles (tenant_id, provider, model, revision, dim, active) "
                          "VALUES (:t, 'p', 'm', '1', 384, true)"), {"t": a.id})
    with pytest.raises(IntegrityError), owner_engine.begin() as conn:
        conn.execute(text("INSERT INTO embedding_profiles (tenant_id, provider, model, revision, dim, active) "
                          "VALUES (:t, 'p', 'm', '2', 384, true)"), {"t": a.id})
    with pytest.raises(IntegrityError), owner_engine.begin() as conn:
        conn.execute(text("INSERT INTO embedding_profiles (tenant_id, provider, model, revision, dim) "
                          "VALUES (:t, 'p', 'm', '3', 768)"), {"t": a.id})


def test_profiles_are_tenant_isolated_by_rls(app_db, owner_engine, pair):
    a, b = pair
    _load(app_db, owner_engine, a)
    with app_db.session(b.id) as s:
        assert s.execute(text("SELECT count(*) FROM embedding_profiles")).scalar() == 0
    with app_db.session() as s:
        assert s.execute(text("SELECT count(*) FROM embedding_profiles")).scalar() == 0
