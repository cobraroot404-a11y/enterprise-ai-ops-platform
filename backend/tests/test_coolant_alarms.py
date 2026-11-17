"""Replay fixed answers through the coolant-temperature alarm citation check."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.ai import rag
from app.ai.embeddings import DeterministicEmbedder
from app.ai.llm import CitedQuote, LLMAnswer
from app.ingestion.parsers import parse_pdf
from app.retrieval.search import Hit

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "evaluation/datasets/eval-v2/corpus/meridian"
CAND1 = ROOT / "evaluation/reports/phase8/exp-CAND1-20261112T090552Z"
QUESTION = "What coolant temperature alarm is set on the MX-350?"
ANSWER = "The MX-350 raises a coolant temperature alarm at 112 C."
STATEMENT = "Engine coolant above 112 C triggers an alarm on the MX-350."
HEADING = "MX-350 rigid truck - Coolant temperature alarm"
ROW = "Alarm threshold: 112 C"
WITHHELD = "the cited evidence does not bind the coolant temperature alarm threshold to the requested model"


def _saved_row(file):
    with (CAND1 / file).open(encoding="utf-8") as lines:
        return next(row for row in map(json.loads, lines) if row["id"] == "E2-M-0012")


@pytest.fixture(scope="module")
def saved():
    raw, = _saved_row("qa_rep1.jsonl")["raw_llm_answers"]
    ranked = _saved_row("retrieval_default.jsonl")["modes"]["hybrid"]["ranked"]
    pages = []
    for hit in ranked[:raw["passages"]]:
        document = parse_pdf((CORPUS / hit["file"]).read_bytes())
        page, = (segment.text for segment in document.segments if segment.page_number == hit["unit"])
        pages.append((hit["file"], hit["unit"], page))
    return raw, pages


@pytest.fixture
def replay(monkeypatch):
    monkeypatch.setenv("EAOP_TUNING", '{"entity_gate": true, "claim_completion": true}')

    def run(pages, quotes, *, answer=ANSWER, question=QUESTION, owned=True):
        hits = [
            Hit(str(i), filename, filename, "manual", 1, text, page, None, False, 1, 1, 1)
            for i, (filename, page, text) in enumerate(pages, start=1)
        ]
        monkeypatch.setattr(rag, "search", lambda *args, **kwargs: hits)
        llm = SimpleNamespace(
            name="fixed", model="test",
            answer=lambda question, passages: LLMAnswer(answer, [CitedQuote(*q) for q in quotes]),
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
    assert not result.citations


@pytest.mark.parametrize("include_heading", [False, True], ids=["auto-completion", "explicit-two-quotes"])
def test_saved_sibling_threshold_is_withheld(replay, saved, include_heading):
    raw, pages = saved
    quotes = [(citation["index"], citation["quote"]) for citation in raw["cited"]]
    if include_heading:
        quotes.append((1, HEADING))
    assert_withheld(replay(pages, quotes, answer=raw["text"]))


def test_actual_model_threshold_grounds(replay, saved):
    _, pages = saved
    result = replay(pages, [(1, STATEMENT)])
    assert result.grounded and result.answer == ANSWER, result.problems
    assert [c["quote"] for c in result.citations] == [STATEMENT]


def test_unambiguous_heading_and_row_grounds(replay):
    result = replay([("manual", 1, f"{HEADING}\n{ROW}")], [(1, f"{HEADING} {ROW}")],
                    answer="112 C [1].")
    assert result.grounded, result.problems


@pytest.mark.parametrize(("page", "quote", "answer"), [
    pytest.param(STATEMENT.replace("MX-350", "MX-300"), STATEMENT.replace("MX-350", "MX-300"),
                 "112 C.", id="sibling-same-threshold"),
    pytest.param(f"MX-350 service instructions.\n{STATEMENT.replace('MX-350', 'MX-300')}",
                 STATEMENT.replace("MX-350", "MX-300"), ANSWER, id="model-elsewhere-on-mixed-page"),
    pytest.param("The MX-350 oil temperature alarm is set to 112 C.",
                 "The MX-350 oil temperature alarm is set to 112 C.", ANSWER, id="different-property"),
    pytest.param(f"{STATEMENT}\nThe MX-350 oil temperature alarm is set to 105 C.",
                 STATEMENT, ANSWER.replace("112", "105"), id="wrong-threshold"),
    pytest.param(STATEMENT, STATEMENT, ANSWER.replace(" C.", " F."), id="wrong-unit"),
    pytest.param(f"{HEADING} / MX-300\n{ROW}", f"{HEADING} / MX-300\n{ROW}", ANSWER, id="shared-heading"),
    pytest.param(f"{HEADING}\nMX-300 - Coolant temperature alarm\n{ROW}",
                 ROW, ANSWER, id="intervening-model-heading"),
    pytest.param(f"{HEADING} {ROW}", f"{HEADING} {ROW}", ANSWER, id="missing-row-boundary"),
    pytest.param(f"The bulletin does not say that {STATEMENT}", STATEMENT, ANSWER, id="partial-statement"),
])
def test_unbound_threshold_is_withheld(replay, page, quote, answer):
    assert_withheld(replay([("manual", 1, page)], [(1, quote)], answer=answer))


def test_heading_cannot_scope_a_row_from_another_source(replay):
    pages = [("manual", 1, HEADING), ("sibling manual", 1, ROW)]
    assert_withheld(replay(pages, [(1, HEADING), (2, ROW)]))


def test_other_question_still_uses_general_completion(replay):
    heading = "MX-350 service bulletin."
    code = "The maintenance code is 105."
    result = replay([("manual", 1, heading), ("manual", 2, code)], [(2, code)],
                    question="What is the maintenance code for the MX-350?",
                    answer="The maintenance code for the MX-350 is 105.")
    assert result.grounded, result.problems
    assert [c["quote"] for c in result.citations] == [code, heading]


def test_tenant_source_validation_still_applies(replay):
    result = replay([("manual", 1, STATEMENT)], [(1, STATEMENT)], owned=False)
    assert not result.grounded
    assert result.problems == ["citation source 1 is not a current chunk owned by this tenant"]
