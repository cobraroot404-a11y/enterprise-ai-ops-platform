"""D1 (answer decomposition, off by default): combining per-part answers never presents a half-answered question as answered, and renumbers citation markers. No model needed."""
import pytest
from app.ai.rag import INSUFFICIENT, AnswerResult, combine_parts
from app.ai.tuning import Tuning


def ok(text, n_citations, marker_start=1):
    cites = [{"marker": marker_start + i, "quote": f"q{i}", "filename": "f.pdf"} for i in range(n_citations)]
    return AnswerResult(text, grounded=True, insufficient_evidence=False, citations=cites, llm_backend="ollama", llm_model="m", embedding_backend="e")


def refused():
    return AnswerResult(INSUFFICIENT, grounded=False, insufficient_evidence=True, llm_backend="ollama", llm_model="m", embedding_backend="e")


def withheld(problem):
    return AnswerResult("The model's output was not valid and was withheld.", grounded=False, insufficient_evidence=False, problems=[problem], llm_backend="ollama", llm_model="m", embedding_backend="e")


def test_grounded_parts_are_joined_with_renumbered_markers_and_citations():
    combined = combine_parts([ok("The limit is 5.5 mm/s [1].", 1), ok("Reference REF-5541 was logged [1][2].", 2)])
    assert combined.grounded and combined.answer == "The limit is 5.5 mm/s [1]. Reference REF-5541 was logged [2][3]."
    assert [c["marker"] for c in combined.citations] == [1, 2, 3] and combined.llm_model == "m"


def test_one_ungrounded_part_means_the_whole_answer_is_not_grounded():
    for parts in ([ok("a [1].", 1), refused()], [refused(), ok("b [1].", 1)], [ok("a [1].", 1), withheld("quote not found")]):
        combined = combine_parts(parts)
        assert not combined.grounded and combined.citations == []  # nothing from the answered part is released as if complete
    assert combine_parts([ok("a [1].", 1), withheld("quote not found")]).problems == ["quote not found"]


def test_every_part_refused_is_a_refusal():
    combined = combine_parts([refused(), refused()])
    assert combined.insufficient_evidence and not combined.grounded and combined.answer == INSUFFICIENT


def test_the_flag_is_off_by_default_and_known_to_the_tuning_loader():
    assert Tuning().decompose_answers is False
    with pytest.raises(ValueError):
        import os

        from app.ai import tuning

        os.environ["EAOP_TUNING"] = '{"decompose_answer": true}'
        try:
            tuning.get_tuning()
        finally:
            del os.environ["EAOP_TUNING"]
