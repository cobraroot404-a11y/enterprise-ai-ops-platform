"""Deterministic replay of the saved E2-A-0066 answer and citation counterexamples."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from app.ai import rag
from app.ai.embeddings import DeterministicEmbedder
from app.ai.llm import CitedQuote, LLMAnswer
from app.ai.safeguards import unsupported_numbers
from app.ingestion.parsers import parse_pdf
from app.retrieval.search import Hit

QUESTION = "Compare the discharge valve opening at start of the CP-250 and the CP-300: what is each value?"
SAVED_ANSWER = (
    "The CP-250 has a discharge valve opening of about 10 percent, while "
    "the CP-300 has a discharge valve opening of about 20 percent [1, 2]."
)
SAVED_CITATIONS = (
    (1, "Start the CP-250 with the discharge valve about 10 percent open and open it gradually."),
    (2, "Start the CP-300 with the discharge valve about 20 percent open and open it gradually."),
)
CORPUS = Path(__file__).resolve().parents[2] / "evaluation/datasets/eval-v2/corpus/apex"


@pytest.fixture(scope="module")
def pages():
    hits = []
    for model, page in [(250, 6), (300, 5)]:
        filename = f"apex_cp-{model}_manual.pdf"
        parsed = parse_pdf((CORPUS / filename).read_bytes())
        source, = [segment.text for segment in parsed.segments if segment.page_number == page]
        hits.append(Hit(f"cp-{model}/{page}", filename, filename, "manual", 1, source, page, None, False, 1, 1, 1))
    return hits


@pytest.fixture
def replay(monkeypatch, pages):
    monkeypatch.setenv("EAOP_TUNING", '{"claim_completion": true, "entity_gate": true}')

    def run(answer=SAVED_ANSWER, citations=SAVED_CITATIONS, *, extra_hits=(), foreign=()):
        monkeypatch.setattr(rag, "search", lambda *args, **kwargs: [*pages, *extra_hits])
        llm = SimpleNamespace(
            name="fixed", model="test",
            answer=lambda question, passages: LLMAnswer(answer, [CitedQuote(*entry) for entry in citations]),
        )

        def execute(statement, params):
            if "SELECT c.id " in str(statement):
                assert params["t"] == "apex"
                return [(chunk,) for chunk in params["ids"] if chunk not in foreign]
            assert "SELECT upper(c.record_id)" in str(statement)
            return SimpleNamespace(all=lambda: [])

        session = SimpleNamespace(execute=execute)
        return rag.answer_question(session, "apex", QUESTION, DeterministicEmbedder(), llm)

    return run


def test_saved_answer_grounds(replay):
    result = replay()
    assert result.grounded and result.answer == SAVED_ANSWER, result.problems
    assert [(c["marker"], c["quote"]) for c in result.citations] == list(SAVED_CITATIONS)


def test_completion_does_not_chase_marker_digits(replay):
    # An unrelated page containing both digits would otherwise be added by claim completion.
    other = Hit("other", "other", "other.pdf", "manual", 1, "CP-250 has settings 1 and 2.", 1, None, False, 1, 1, 1)
    result = replay(extra_hits=(other,))
    assert result.grounded and result.answer == SAVED_ANSWER, result.problems
    assert [(c["marker"], c["quote"]) for c in result.citations] == list(SAVED_CITATIONS)


@pytest.mark.parametrize(("answer", "citations", "problem"), [
    (SAVED_ANSWER.replace("10 percent", "11%"), SAVED_CITATIONS, "number(s) not found in the cited evidence: 11"),
    (SAVED_ANSWER, SAVED_CITATIONS[:1], "answer marker [2] has no verified citation"),
    (SAVED_ANSWER.replace("[1, 2]", "[1, 3]"), SAVED_CITATIONS, "answer marker [3] has no verified citation"),
    (SAVED_ANSWER, (*SAVED_CITATIONS[:1], (2, "Invented quote.")), "citation [2] quote not found"),
    ("Use startup settings [1, 2].", SAVED_CITATIONS, "number(s) not found in the cited evidence: 1, 2"),
    (SAVED_ANSWER.replace("[1, 2]", "[2, 1]"), SAVED_CITATIONS, "number(s) not found in the cited evidence: 1, 2"),
    (SAVED_ANSWER.replace("[1, 2]", "[1-2]"), SAVED_CITATIONS, "number(s) not found in the cited evidence: 1, 2"),
])
def test_unverified_markers_and_unsupported_numbers_withhold(replay, answer, citations, problem):
    result = replay(answer, citations)
    assert not result.grounded and not result.insufficient_evidence
    assert not result.citations
    assert any(problem in item for item in result.problems), result.problems


def test_single_marker_unchanged(replay):
    result = replay(SAVED_ANSWER.replace("[1, 2]", "[1][2]"))
    assert result.grounded, result.problems


def test_list_digits_are_still_numeric_evidence(monkeypatch):
    monkeypatch.delenv("EAOP_TUNING", raising=False)
    assert unsupported_numbers("Use settings 1 and 2.", ["Use settings [1, 2]."]) == []


def test_verified_marker_cannot_bypass_source_check(replay):
    result = replay(foreign=("cp-300/5",))
    assert not result.grounded and not result.citations
    assert result.problems == ["citation source cp-300/5 is not a current chunk owned by this tenant"]
