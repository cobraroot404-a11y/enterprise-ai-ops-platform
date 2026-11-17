"""H2: structured low-authority note suppression (default-off `low_authority_suppression` flag). Synthetic generic data only."""
import inspect
import json

import pytest
from app.ai import rag, suppression
from app.ai.embeddings import DeterministicEmbedder
from app.ai.llm import CitedQuote, LLMAnswer
from app.ai.suppression import find_suppressions, suppress_low_authority
from app.ai.tuning import Tuning, is_default
from app.retrieval.search import Hit


def note(asset="AB-17", desc="Technician note (unverified, not from the manual): shaft alignment tolerance for AB-17 is usually taken as 0.04",
         kind="incident_history", id_field="equipment_id", category="note"):
    return (f"incident_id: INC-N0001; date: 2026-05-14; {id_field}: {asset}; category: {category}; description: {desc}; "
            "root_cause: n/a; resolution: none"), kind


MANUAL = "ZX-250 pump - Shaft alignment tolerance Parallel and angular misalignment on the ZX-250 must both stay below 0.08 mm."


def h(i, text_kind, kind=None):
    text, k = text_kind if isinstance(text_kind, tuple) else (text_kind, kind)
    return Hit(chunk_id=f"c{i}", document_id=f"d{i}", filename=f"f{i}", kind=k, version=1, text=text, page_number=None, record_id=None,
               suspicious=False, score=1.0 - i / 10, similarity=0.99, overlap=1.0)


def resolver(mapping):
    return lambda ids: {i: set(mapping[i]) for i in ids if i in mapping}


ONE = resolver({"AB-17": {"ZX-250"}})


def ctx(*items):
    return [h(i, x, kind) for i, (x, kind) in enumerate(items)]


def test_flag_default_off():
    assert Tuning().low_authority_suppression is False and is_default()


def test_positive_suppresses_with_justifying_manual():
    n, m = h(0, note()), h(1, MANUAL, "equipment_manual")
    found = find_suppressions([n, m], ONE)
    assert [(s.note, s.manual, s.model, s.asset) for s in found] == [(n, m, "ZX-250", "AB-17")]
    assert suppress_low_authority([n, m], ONE) == [m]


@pytest.mark.parametrize("desc,manual,kind,incident_kind", [
    ("Operator remark (hearsay): air dryer cartridge interval for VH-9 is usually 16",
     "The air dryer cartridge on the MX-300 is changed at 10 months.", "fleet_manual", "service_history"),
    ("Operator remark (unconfirmed): coolant temperature warning for VH-9 is taken as 105",
     "Coolant temperature warning Warn the driver of the MX-300 when coolant reaches 104 C.", "fleet_manual", "service_history"),
])
def test_generic_patterns_other_domains(desc, manual, kind, incident_kind):
    n = h(0, note("VH-9", desc, incident_kind, "vehicle_id"))
    m = h(1, manual, kind)
    assert suppress_low_authority([n, m], resolver({"VH-9": {"MX-300"}})) == [m]


def test_note_only_is_not_suppressed():
    n = h(0, note())
    assert suppress_low_authority([n], ONE) == [n]


def test_different_model_manual_not_suppressed():
    n, m = h(0, note()), h(1, MANUAL.replace("ZX-250", "ZX-260"), "equipment_manual")
    assert suppress_low_authority([n, m], ONE) == [n, m]


def test_model_prefix_is_not_a_match():
    n, m = h(0, note()), h(1, MANUAL.replace("ZX-250", "ZX-2500"), "equipment_manual")
    assert suppress_low_authority([n, m], ONE) == [n, m]


def test_unrelated_topic_not_suppressed():
    n = h(0, note())
    m = h(1, "ZX-250 pump - Bearing lubrication interval Lubricate the bearings of the ZX-250 every 4000 hours.", "equipment_manual")
    assert suppress_low_authority([n, m], ONE) == [n, m]


def test_distinct_identifier_in_note_not_suppressed():
    n = h(0, note(desc="Technician note (unverified): shaft alignment tolerance for AB-17 needs shim PN-4412 at 0.04"))
    m = h(1, MANUAL, "equipment_manual")
    assert suppress_low_authority([n, m], ONE) == [n, m]


def test_note_value_not_suppressed_when_manual_states_no_value():
    n = h(0, note())
    m = h(1, "ZX-250 pump - Shaft alignment tolerance Check the shaft alignment tolerance of the ZX-250 before start-up.", "equipment_manual")
    assert suppress_low_authority([n, m], ONE) == [n, m]


@pytest.mark.parametrize("mapping", [{}, {"AB-17": set()}, {"AB-17": {"ZX-250", "ZX-251"}}, {"OTHER-1": {"ZX-250"}}])
def test_missing_or_ambiguous_identity_not_suppressed(mapping):
    n, m = h(0, note()), h(1, MANUAL, "equipment_manual")
    assert suppress_low_authority([n, m], resolver(mapping)) == [n, m]


def test_verified_record_not_suppressed():
    n = h(0, note(desc="Service record: shaft alignment tolerance for AB-17 measured as 0.04"))
    m = h(1, MANUAL, "equipment_manual")
    assert suppress_low_authority([n, m], ONE) == [n, m]


def test_non_note_category_and_non_record_kind_not_suppressed():
    m = h(1, MANUAL, "equipment_manual")
    for n in (h(0, note(category="repair")), h(0, note(kind="equipment_register")), h(0, note(kind="equipment_manual"))):
        assert suppress_low_authority([n, m], ONE) == [n, m]


def test_manual_must_be_authoritative_kind():
    n = h(0, note())
    for kind in ("incident_history", "inspection_report"):
        assert suppress_low_authority([n, h(1, MANUAL, kind)], ONE)[0] is n and len(suppress_low_authority([n, h(1, MANUAL, kind)], ONE)) == 2


def test_self_declared_unverified_manual_is_not_authoritative():
    n, m = h(0, note()), h(1, MANUAL + " (unverified)", "equipment_manual")
    assert len(suppress_low_authority([n, m], ONE)) == 2


def test_nothing_else_removed_and_order_stable():
    other = h(2, "ZX-250 pump - Bearing lubrication interval 4000 hours.", "equipment_manual")
    n, m = h(0, note()), h(1, MANUAL, "equipment_manual")
    assert suppress_low_authority([other, n, m], ONE) == [other, m]


def test_no_dataset_specific_hardcoding():
    src = inspect.getsource(suppression).lower()
    for word in ("apex", "meridian", "p-1010", "vh-", "e2-a", "e2-m", "inc-n", "sr-n", "cp-250", "mx-300"):
        assert word not in src


# ---- RAG pipeline ----------------------------------------------------------------------------------------------------
class Recorder:
    name, model = "rec", "rec"

    def __init__(self):
        self.passages = None

    def answer(self, question, passages):
        self.passages = passages
        return LLMAnswer(text="ok", cited=[CitedQuote(1, passages[0].text.split(".")[0])])


def _run(monkeypatch, tuning, items, mapping):
    monkeypatch.delenv("EAOP_TUNING", raising=False)
    if tuning:
        monkeypatch.setenv("EAOP_TUNING", json.dumps(tuning))
    hits = ctx(*items)
    monkeypatch.setattr(rag, "search", lambda *a, **k: hits)
    monkeypatch.setattr(rag, "resolve_models", lambda s, t, ids: {i: set(mapping[i]) for i in ids if i in mapping})
    monkeypatch.setattr(rag, "verify_citation_sources", lambda *a, **k: [])
    monkeypatch.setattr(rag, "check_answer_support", lambda *a, **k: [])
    monkeypatch.setattr(rag, "required_entities", lambda *a, **k: [])
    llm = Recorder()
    res = rag.answer_question(None, "t", "What shaft alignment tolerance applies to AB-17?", DeterministicEmbedder(), llm)
    return [p.text for p in llm.passages], res


def test_pipeline_off_unchanged_on_removes_note(monkeypatch):
    items = [note(), (MANUAL, "equipment_manual")]
    off, _ = _run(monkeypatch, None, items, {"AB-17": {"ZX-250"}})
    assert off == [items[0][0], MANUAL]
    on, res = _run(monkeypatch, {"low_authority_suppression": True}, items, {"AB-17": {"ZX-250"}})
    assert on == [MANUAL] and res.grounded and res.citations[0]["chunk_id"] == "c1"


def test_pipeline_enabled_without_manual_keeps_note(monkeypatch):
    items = [note(), ("ZX-250 pump - Bearing lubrication interval 4000 hours.", "equipment_manual")]
    on, res = _run(monkeypatch, {"low_authority_suppression": True}, items, {"AB-17": {"ZX-250"}})
    assert on[0] == items[0][0] and len(on) == 2 and res.grounded
