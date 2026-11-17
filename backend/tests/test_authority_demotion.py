"""H1: authority ordering of retrieved passages (default-off `authority_demotion` flag). Pure logic plus the RAG context stage with a stubbed search."""
import inspect
import json

import pytest
from app.ai import authority, rag
from app.ai.authority import apply_authority_order, is_low_authority
from app.ai.embeddings import DeterministicEmbedder
from app.ai.llm import CitedQuote, LLMAnswer
from app.ai.tuning import Tuning, is_default
from app.retrieval.search import Hit

NOTE = "Technician note (unverified, not from the manual): shaft alignment tolerance for P-1010 is usually taken as 0.04"
MANUAL = "Shaft alignment tolerance for the pump is 0.05 mm total indicator reading. Check coupling after any realignment."
UNRELATED = "Bearing lubrication interval is 4000 hours. Use the grease specified on the nameplate."
OTHER_NOTE = "Hearsay: coolant warning is usually 95"


class H:
    def __init__(self, text):
        self.text = text


def test_flag_is_default_off():
    assert Tuning().authority_demotion is False and is_default()


def test_manual_gets_preference_over_relevant_unverified_note():
    note, manual = H(NOTE), H(MANUAL)
    assert apply_authority_order([note, manual]) == [manual, note]


def test_note_only_stays_available_and_order_unchanged():
    note, other = H(NOTE), H(UNRELATED)
    assert apply_authority_order([note]) == [note]
    assert apply_authority_order([note, other]) == [note, other]  # unrelated passage must not demote a relevant note


def test_unrelated_manual_passage_does_not_demote():
    note, unrelated = H(NOTE), H(UNRELATED)
    assert apply_authority_order([note, unrelated]) == [note, unrelated]


@pytest.mark.parametrize("marker", ["unverified", "Unconfirmed", "not verified", "unofficial", "hearsay"])
def test_generic_markers(marker):
    assert is_low_authority(f"Operator remark ({marker}): shaft alignment tolerance is high")
    assert not is_low_authority("Shaft alignment tolerance is 0.05 mm")


def test_nothing_is_deleted_and_stable():
    hits = [H(NOTE), H(MANUAL), H(UNRELATED), H(OTHER_NOTE)]
    out = apply_authority_order(hits)
    assert sorted(map(id, out)) == sorted(map(id, hits))
    assert out == [hits[1], hits[2], hits[3], hits[0]]  # hearsay line has no matching higher-authority passage and keeps its slot


def test_no_dataset_specific_hardcoding():
    src = inspect.getsource(authority).lower()
    for word in ("apex", "meridian", "p-1010", "vh-", "e2-a", "e2-m", "inc-n", "sr-n"):
        assert word not in src


# ---- RAG context stage ------------------------------------------------------------------------------------------
def _hit(i, text):
    return Hit(chunk_id=f"c{i}", document_id=f"d{i}", filename=f"f{i}", kind="x", version=1, text=text, page_number=None, record_id=None,
               suspicious=False, score=1.0 - i / 10, similarity=0.99, overlap=1.0)


class Recorder:
    name, model = "rec", "rec"

    def __init__(self):
        self.passages = None

    def answer(self, question, passages):
        self.passages = passages
        return LLMAnswer(text="ok", cited=[CitedQuote(1, passages[0].text.split(".")[0])])


def _run(monkeypatch, tuning, texts):
    for k in ("EAOP_TUNING",):
        monkeypatch.delenv(k, raising=False)
    if tuning:
        monkeypatch.setenv("EAOP_TUNING", json.dumps(tuning))
    hits = [_hit(i, t) for i, t in enumerate(texts)]
    monkeypatch.setattr(rag, "search", lambda *a, **k: hits)
    monkeypatch.setattr(rag, "verify_citation_sources", lambda *a, **k: [])
    monkeypatch.setattr(rag, "check_answer_support", lambda *a, **k: [])
    llm = Recorder()
    res = rag.answer_question(None, "t", "What shaft alignment tolerance applies?", DeterministicEmbedder(), llm)
    return llm.passages, res


def test_pipeline_off_reproduces_current_order_and_on_prefers_manual(monkeypatch):
    texts = [NOTE, MANUAL, UNRELATED]
    off, res_off = _run(monkeypatch, None, texts)
    assert [p.text for p in off] == texts
    on, res_on = _run(monkeypatch, {"authority_demotion": True}, texts)
    assert [p.text for p in on] == [MANUAL, UNRELATED, NOTE]
    assert res_on.citations[0]["chunk_id"] == "c1" and res_off.citations[0]["chunk_id"] == "c0"
    assert res_on.grounded and res_off.grounded


def test_pipeline_note_only_is_unchanged_when_enabled(monkeypatch):
    on, res = _run(monkeypatch, {"authority_demotion": True}, [NOTE, UNRELATED])
    assert [p.text for p in on] == [NOTE, UNRELATED] and res.grounded
