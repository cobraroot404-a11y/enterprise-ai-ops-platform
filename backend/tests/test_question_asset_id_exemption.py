"""Deterministic H3 tests with fixed generated answers and tenant-scoped evidence."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from app.ai import rag
from app.ai.asset_references import resolve_references
from app.ai.embeddings import DeterministicEmbedder
from app.ai.llm import CitedQuote, LLMAnswer
from app.ai.tuning import Tuning, tuning_hash
from app.ingestion.service import ingest
from app.profile.schema import TenantProfile
from app.profile.service import save_profile
from app.retrieval.search import Hit
from sqlalchemy import text
from support import ROOT, make_tenant

ASSET = "VH-3111"
QUESTION = f"What bearing re-grease interval applies to {ASSET}?"
ANSWER = f"The bearing re-grease interval for {ASSET} is every 3000 operating hours [1]."
QUOTE = "Re-grease the drive-end and non-drive-end bearings of the CP-200 every 3000 operating hours."
PASSAGE = (
    "CP-200 depot transfer pump - Bearing re-grease interval\n"
    + QUOTE.replace("operating hours", "operating\nhours")
    + " Read this page together with the depot lock-out procedure."
)


class FixedAnswer:
    name, model = "fixed", "test"

    def __init__(self, answer, quote):
        self.response = LLMAnswer(text=answer, cited=[CitedQuote(1, quote)])

    def answer(self, question, passages):
        return self.response


class RegisterSession:
    def __init__(self, rows, owns_citation):
        self.rows = rows
        self.owns_citation = owns_citation
        self.profile_reads = 0

    def scalar(self, statement):
        self.profile_reads += 1
        return None  # default equipment_register

    def execute(self, statement, params):
        sql = str(statement)
        if "c.suspicious" in sql:
            assert "c.tenant_id = :tenant AND d.tenant_id = :tenant" in sql
            assert "d.lifecycle_status = 'active'" in sql and "c.is_current AND d.kind = :kind" in sql
            assert params["tenant"] == "tenant" and params["kind"] == "equipment_register"
            return [(asset, body, suspicious) for asset, body, suspicious in self.rows if asset in params["ids"]]
        if "SELECT c.id " in sql:
            return [("chunk",)] if self.owns_citation else []
        return SimpleNamespace(all=lambda: [(asset, body) for asset, body, _ in self.rows if asset in params["ids"]])


def run(monkeypatch, *, enabled=True, entity_gate=True, asset=ASSET, model="CP-200", rows=None,
        question=QUESTION, answer=ANSWER, quote=QUOTE, passage=PASSAGE, owns_citation=True, enforce_entities=True,
        decompose=False):
    monkeypatch.setenv("EAOP_TUNING", json.dumps({
        "question_asset_id_exemption": enabled, "claim_completion": True, "entity_gate": entity_gate,
        "decompose_answers": decompose,
    }))
    hit = Hit("chunk", "doc", "manual.pdf", "equipment_manual", 1, passage, 1, None, False, 1, 1, 1)
    monkeypatch.setattr(rag, "search", lambda *a, **k: [hit])
    session = RegisterSession([(asset, f"model: {model}", False)] if rows is None else rows, owns_citation)
    result = rag.answer_question(session, "tenant", question, DeterministicEmbedder(), FixedAnswer(answer, quote),
                                 enforce_entities=enforce_entities)
    return result, session


def test_flag_only_changes_the_copied_identifier_number(monkeypatch):
    assert Tuning().question_asset_id_exemption is False
    off, session = run(monkeypatch, enabled=False)
    assert session.profile_reads == 0
    assert off.problems == ["number(s) not found in the cited evidence: 3111"]
    on, _ = run(monkeypatch)
    assert on.grounded and on.answer == ANSWER
    assert [c["quote"] for c in on.citations] == [QUOTE]
    for enabled in (False, True):
        ordinary, _ = run(monkeypatch, enabled=enabled, answer="Re-grease every 3000 operating hours [1].")
        assert ordinary.grounded


def test_flag_off_preserves_recorded_configuration_hash():
    settings = Tuning(entity_boost=0.02, entity_gate=True, query_override_gate=True, claim_completion=True,
                      numeric_verification=True, guidance_query="asset_context", low_authority_suppression=True)
    assert tuning_hash(settings) == "c9ef06c22b4e7a062571d5b330ed6999e893b98fd0a2af1c4baa6555186430cd"
    assert tuning_hash(replace(settings, question_asset_id_exemption=True)) != tuning_hash(settings)


@pytest.mark.parametrize(("asset", "model", "answer", "quote"), [
    ("P-1010", "CP-250", "The tolerance for P-1010 is 0.05 mm [1].",
     "Parallel and angular misalignment on the CP-200 must both stay below 0.05 mm."),
    ("VH-2009", "MX-300", "The air dryer cartridge interval for VH-2009 is 14 months [1].",
     "Replace the MX-350 air dryer cartridge every 14 months."),
])
def test_wrong_model_reaches_and_fails_entity_gate(monkeypatch, asset, model, answer, quote):
    result, _ = run(monkeypatch, asset=asset, model=model, question=f"What does the manual specify for {asset}?",
                    answer=answer, passage=quote, quote=quote)
    assert not result.grounded and result.insufficient_evidence
    assert result.problems[0].startswith("identifier(s) named in the question not found in the cited evidence:")


@pytest.mark.parametrize(("asked", "repeated", "rows"), [
    ("the pump", ASSET, None),             # registered id absent from the question
    (ASSET, "VH-4455", None),              # model-generated/fabricated
    (ASSET, "vh-3111", None),              # model changed spelling
    ("pref-VH-3111", ASSET, None),         # question has only a partial-token match
    ("pref.VH-3111", ASSET, None),         # dotted qualification is also a partial token
    ("XVH-3111", ASSET, None),             # question has only a substring
    (ASSET, "VH-3111-extra", None),        # answer has only a partial-token match
    (ASSET, "VH-31112", None),             # answer has only a substring
    (ASSET, "VH-3111.5", None),            # number extends beyond the asset-token boundary
    (ASSET, "VH-3111,999", None),
    (ASSET, ASSET, []),                    # no visible current tenant register row
    (ASSET, ASSET, [(ASSET, "model: CP-200", False)] * 2),  # ambiguous even with the same model
    (ASSET, ASSET, [(ASSET, "model: CP-200; model: CP-250", False)]),
    (ASSET, ASSET, [(ASSET, "model: CP-200", True)]),
    (ASSET, ASSET, [(ASSET, "name: unknown model", False)]),
    ("CP-250", "CP-250", [(ASSET, "model: CP-250", False)]),  # model code only
    ("PN-4417", "PN-4417", [("PN-4417", "model: CP-200", False)]),
    ("INC-2025-1001", "INC-2025-1001", [("INC-2025-1001", "model: CP-200", False)]),
])
def test_invalid_or_uncertain_references_keep_strict_numeric_verification(monkeypatch, asked, repeated, rows):
    result, _ = run(monkeypatch, question=f"What interval applies to {asked}?",
                    answer=ANSWER.replace(ASSET, repeated), rows=rows)
    assert not result.grounded
    assert any(problem.startswith("number(s) not found") for problem in result.problems)


@pytest.mark.parametrize(("answer", "missing"), [
    (ANSWER + " The count is 3111.", "3111"),
    (ANSWER.replace("3000", "3111"), "3111"),
    (ANSWER.replace("3000", "3500"), "3500"),
])
def test_numbers_outside_eligible_span_still_need_independent_evidence(monkeypatch, answer, missing):
    result, _ = run(monkeypatch, answer=answer)
    assert not result.grounded
    assert result.problems == [f"number(s) not found in the cited evidence: {missing}"]


@pytest.mark.parametrize(("answer", "passage", "quote"), [
    (ANSWER, "Inspect the CP-200 seal every 3000 operating hours.", "Inspect the CP-200 seal every 3000 operating hours."),
    (ANSWER, f"Never {QUOTE[0].lower()}{QUOTE[1:]}", QUOTE[0].lower() + QUOTE[1:]),
    (ANSWER, f"CP-200 inspection. {QUOTE.removesuffix('.')} only under exceptional conditions.",
     QUOTE.removesuffix(".")),
    (ANSWER + " It is located in East Depot.", PASSAGE, QUOTE),
    (f"The asset {ASSET} is located in East Depot [1].", PASSAGE, QUOTE),
    (f"The tolerance for {ASSET} is 3000 bar [1].", PASSAGE, QUOTE),
    (ANSWER, "CP-200 is electrically driven. " + QUOTE.replace("CP-200", "CP-250"), QUOTE.replace("CP-200", "CP-250")),
])
def test_exemption_cannot_ground_an_unjustified_statement(monkeypatch, answer, passage, quote):
    result, _ = run(monkeypatch, answer=answer, passage=passage, quote=quote)
    assert not result.grounded
    assert result.problems == ["the copied asset reference lacks a supporting maintenance interval in the cited manual"]


def test_invalid_citations_and_foreign_citation_sources_still_fail(monkeypatch):
    invalid, session = run(monkeypatch, quote="something never said in the manual")
    assert invalid.problems == [
        "citation [1] quote not found in the cited passage", "answer marker [1] has no verified citation",
    ]
    assert session.profile_reads == 0
    foreign, _ = run(monkeypatch, owns_citation=False)
    assert foreign.problems == ["citation source chunk is not a current chunk owned by this tenant"]


@pytest.mark.parametrize("enforce_entities", [True, False])
def test_entity_gate_is_required_for_exemption(monkeypatch, enforce_entities):
    result, session = run(monkeypatch, entity_gate=not enforce_entities, enforce_entities=enforce_entities)
    assert result.problems == ["number(s) not found in the cited evidence: 3111"]
    assert session.profile_reads == 0


def test_decomposition_cannot_upgrade_a_partial_original_token(monkeypatch):
    result, session = run(monkeypatch, question="What applies to VH-3111-extra? What is the operating interval?",
                          decompose=True)
    assert not result.grounded
    assert all("3111" in problem for problem in result.problems)
    assert session.profile_reads == 0


@pytest.mark.parametrize("with_profile", [False, True])
def test_registered_asset_must_be_current_unique_and_owned_by_requesting_tenant(
    app_db, owner_engine, monkeypatch, with_profile,
):
    owner = make_tenant(owner_engine, "h3-register")
    other = make_tenant(owner_engine, "h3-other")
    embedder = DeterministicEmbedder()
    profile = None
    if with_profile:
        config = json.loads((ROOT / "onboarding" / "meridian.json").read_text(encoding="utf-8"))
        profile = TenantProfile.model_validate(config["profile"])
    register_kind = profile.register_kind if profile else "equipment_register"
    manual_kind = "fleet_manual" if profile else "equipment_manual"
    extra_kinds = {register_kind, manual_kind}
    monkeypatch.setenv("EAOP_TUNING", '{"question_asset_id_exemption":true,"entity_gate":true}')
    base_hit = Hit("", "", "manual.txt", manual_kind, 1, PASSAGE, None, None, False, 1, 1, 1)
    for tenant in (owner, other):
        with owner_engine.connect() as conn:
            uid = conn.execute(text("SELECT id FROM users WHERE email = :email"),
                               {"email": tenant.users["support_engineer"]}).scalar_one()
        with app_db.session(tenant.id, uid) as session:
            if profile:
                save_profile(session, tenant_id=tenant.id, user_id=uid, profile=profile)
            manual = ingest(session, tenant_id=tenant.id, user_id=uid, filename="manual.txt",
                            data=PASSAGE.encode(), kind=manual_kind, embedder=embedder, extra_kinds=extra_kinds)
            chunk = session.execute(text("SELECT id FROM document_chunks WHERE document_id = :doc"),
                                    {"doc": manual.document_id}).scalar_one()
            hit = replace(base_hit, chunk_id=str(chunk), document_id=manual.document_id)
            monkeypatch.setattr(rag, "search", lambda *a, hit=hit, **k: [hit])
            if tenant == owner:
                ingest(session, tenant_id=tenant.id, user_id=uid, filename="register.csv",
                       data=b"equipment_id,model\nVH-3111,CP-200\n", kind=register_kind, embedder=embedder,
                       extra_kinds=extra_kinds)
            session.commit()
            result = rag.answer_question(session, tenant.id, QUESTION, embedder, FixedAnswer(ANSWER, QUOTE))
            assert result.grounded is (tenant == owner), result.problems
            if tenant != owner:
                assert "3111" in result.problems[0]
    with app_db.session(owner.id) as session:
        assert resolve_references(session, owner.id, QUESTION, ANSWER) == {ASSET: "CP-200"}
        chunk_params = {"asset": ASSET, "tenant": owner.id}
        with owner_engine.begin() as conn:
            conn.execute(text("UPDATE document_chunks SET is_current = false WHERE record_id = :asset AND tenant_id = :tenant"),
                         chunk_params)
        assert resolve_references(session, owner.id, QUESTION, ANSWER) == {}
        with owner_engine.begin() as conn:
            conn.execute(text("UPDATE document_chunks SET is_current = true WHERE record_id = :asset AND tenant_id = :tenant"),
                         chunk_params)
            conn.execute(text("UPDATE documents SET lifecycle_status = 'deleted', deleted_at = now(), cleanup_state = 'pending' "
                              "WHERE kind = :kind AND tenant_id = :tenant"),
                         {"tenant": owner.id, "kind": register_kind})
        assert resolve_references(session, owner.id, QUESTION, ANSWER) == {}
