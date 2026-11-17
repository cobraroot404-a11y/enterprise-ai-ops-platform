"""Fixed-answer replays for the whole-unit service interval trust boundary."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from app.ai import rag
from app.ai.embeddings import DeterministicEmbedder
from app.ai.llm import CitedQuote, LLMAnswer
from app.ingestion.parsers import parse_pdf
from app.retrieval.search import Hit

QUESTION = "What is the service interval of the RT-95 refrigeration unit?"
ANSWER = "The service interval of the RT-95 refrigeration unit is 50 days."
GASKET = "Check the rear door gaskets of the RT-95 at 50 day intervals."
WHOLE_UNIT = "The RT-95 refrigeration unit must be serviced every 50 days."
WITHHELD = "the cited evidence does not bind the whole-unit service interval to the requested model"
MANUAL = Path(__file__).resolve().parents[2] / (
    "evaluation/datasets/eval-v2/corpus/meridian/meridian_rt-95_manual.pdf"
)


@pytest.fixture(scope="module")
def saved_page():
    parsed = parse_pdf(MANUAL.read_bytes())
    page, = [segment.text for segment in parsed.segments if segment.page_number == 5]
    return page


@pytest.fixture
def replay(monkeypatch):
    monkeypatch.setenv("EAOP_TUNING", '{"entity_gate": true, "claim_completion": true}')

    def run(page, quote, *, question=QUESTION, answer=ANSWER, owned=True):
        hits = [
            Hit(str(i), str(i), MANUAL.name, "manual", 1, text, i, None, False, 1, 1, 1)
            for i, text in [(1, "General maintenance information."), (2, page)]
        ]
        monkeypatch.setattr(rag, "search", lambda *args, **kwargs: hits)
        llm = SimpleNamespace(
            name="fixed", model="test",
            answer=lambda question, passages: LLMAnswer(answer, [CitedQuote(2, quote)]),
        )

        def execute(statement, params):
            assert params["t"] == "meridian"
            if "SELECT c.id " in str(statement):
                return [(chunk,) for chunk in params["ids"] if owned]
            assert "SELECT upper(c.record_id)" in str(statement)
            return SimpleNamespace(all=lambda: [])

        return rag.answer_question(SimpleNamespace(execute=execute), "meridian", question,
                                   DeterministicEmbedder(), llm)

    return run


def assert_withheld(result):
    assert not result.grounded and not result.insufficient_evidence
    assert result.problems == [WITHHELD]
    assert result.citations == []


def test_saved_gasket_citation_cannot_support_whole_unit(replay, saved_page):
    assert_withheld(replay(saved_page, GASKET))


def test_explicit_whole_unit_statement_grounds(replay):
    result = replay(WHOLE_UNIT, WHOLE_UNIT)
    assert result.grounded and result.answer == ANSWER, result.problems
    assert result.citations[0]["quote"] == WHOLE_UNIT


def test_gasket_specific_question_still_grounds(replay, saved_page):
    result = replay(saved_page, GASKET, question="What is the rear door gasket check interval for the RT-95?",
                    answer="Check the rear door gaskets of the RT-95 every 50 days.")
    assert result.grounded, result.problems


@pytest.mark.parametrize("quote", [
    pytest.param("The RT-95 refrigeration unit must be inspected every 50 days.", id="different-task"),
    pytest.param(WHOLE_UNIT.replace("RT-95", "RT-90"), id="different-model"),
    pytest.param("The model is RT-95. The refrigeration unit must be serviced. The interval is 50 days.",
                 id="split-statements"),
    pytest.param(WHOLE_UNIT.replace("50", "60"), id="different-duration"),
])
def test_wrong_scope_cannot_borrow_support_from_page(replay, quote):
    assert_withheld(replay(f"{quote} {GASKET}", quote))


def test_quote_cannot_omit_negating_context(replay):
    assert_withheld(replay(f"The manual does not say that {WHOLE_UNIT}", WHOLE_UNIT))


def test_uncited_whole_unit_statement_cannot_rescue_component_quote(replay):
    assert_withheld(replay(f"{WHOLE_UNIT} {GASKET}", GASKET))


def test_whole_unit_control_still_requires_tenant_source_ownership(replay):
    result = replay(WHOLE_UNIT, WHOLE_UNIT, owned=False)
    assert not result.grounded
    assert result.problems == ["citation source 2 is not a current chunk owned by this tenant"]
