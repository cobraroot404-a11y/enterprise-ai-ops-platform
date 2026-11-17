"""Deterministic QA replays for asset-specific inspection citations."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from app.ai import rag
from app.ai.embeddings import DeterministicEmbedder
from app.ai.llm import CitedQuote, LLMAnswer
from app.ingestion.parsers import parse_pdf
from app.retrieval.search import Hit

QUESTION = "What service brake line pressure did the 2026Q3 inspection record for VH-6103?"
WITHHELD = "the cited inspection evidence does not bind the reading to the requested asset and period"
CORPUS = Path(__file__).resolve().parents[2] / "evaluation/datasets/eval-v2/corpus"
RIGHT_QUOTE = "VH-6103 (MX-350): service brake line pressure measured 114 psi"
SAVED_QUOTE = (
    "VH-7102 (MX-350): service brake line pressure measured 87 psi and coolant temperature 100 C. "
    "Inspector note: keep under observation."
)


class FixedAnswer:
    name, model = "fixed", "test"

    def __init__(self, answer, citations):
        self.result = LLMAnswer(answer, [CitedQuote(index, quote) for index, quote in citations])

    def answer(self, question, passages):
        return self.result


class CurrentEvidence:
    def execute(self, statement, params):
        if "SELECT c.id " in str(statement):
            return [(chunk,) for chunk in params["ids"]]
        assert "SELECT upper(c.record_id)" in str(statement)
        return SimpleNamespace(all=lambda: [
            (asset, "model: MX-350") for asset in ["VH-6103", "VH-7102"] if asset in params["ids"]
        ])


def hit(text, filename="inspection.pdf", page=1, kind="depot_inspection"):
    return Hit(f"{filename}/{page}", filename, filename, kind, 1, text, page, None, False, 1, 1, 1)


def run(monkeypatch, question, answer, hits, *citations):
    monkeypatch.setenv("EAOP_TUNING", '{"entity_gate": true, "claim_completion": true}')
    monkeypatch.setattr(rag, "search", lambda *args, **kwargs: hits)
    return rag.answer_question(CurrentEvidence(), "tenant", question, DeterministicEmbedder(),
                               FixedAnswer(answer, citations))


def inspection(quarter="2026Q3", asset="VH-6103", amount=114, temperature=97, model="MX-350"):
    quote = f"{asset} ({model}): service brake line pressure measured {amount} psi"
    return f"Inspection {quarter} - {asset}\n{quote} and coolant temperature {temperature} C.", quote


def assert_withheld(result):
    assert not result.grounded and not result.insufficient_evidence
    assert result.problems == [WITHHELD]
    assert result.citations == []


@pytest.fixture
def original_pages():
    hits = []
    for quarter, page in [("2026q3", 2), ("2026q1", 4)]:
        filename = f"meridian_inspection_{quarter}.pdf"
        parsed = parse_pdf((CORPUS / "meridian" / filename).read_bytes())
        source, = [segment.text for segment in parsed.segments if segment.page_number == page]
        hits.append(hit(source, filename, page))
    return hits


def test_saved_wrong_answer_is_withheld(monkeypatch, original_pages):
    assert_withheld(run(monkeypatch, QUESTION, "87 psi", original_pages, (2, SAVED_QUOTE)))


def test_original_114_psi_control_is_grounded(monkeypatch, original_pages):
    result = run(monkeypatch, QUESTION, "114 psi", original_pages, (1, RIGHT_QUOTE))
    assert result.grounded and result.answer == "114 psi"
    assert result.citations[0]["page_number"] == 2
    assert result.citations[0]["quote"] == RIGHT_QUOTE


@pytest.mark.parametrize(("asset", "quarter", "model"), [
    pytest.param("VH-7111", "2026Q3", "HX-410", id="wrong-asset-only"),
    pytest.param("VH-6103", "2026Q1", "MX-350", id="wrong-quarter-only"),
    pytest.param("VH-7102", "2026Q3", "MX-350", id="sibling-with-shared-model"),
    pytest.param("VH-6103A", "2026Q3", "MX-350", id="exact-token"),
])
def test_exact_scope(monkeypatch, asset, quarter, model):
    body, quote = inspection(quarter, asset, amount=87, model=model)
    assert_withheld(run(monkeypatch, QUESTION, "87 psi", [hit(body)], (1, quote)))


@pytest.mark.parametrize("wrong_first", [False, True])
def test_other_record_on_same_page_cannot_rescue_wrong_measurement(monkeypatch, wrong_first):
    wrong_page, quote = inspection("2026Q1", "VH-7102", amount=87)
    right_page, _ = inspection()
    records = [wrong_page, right_page] if wrong_first else [right_page, wrong_page]
    assert_withheld(run(monkeypatch, QUESTION, "87 psi", [hit("\n".join(records))], (1, quote)))


def test_other_property_with_same_number_cannot_support_answer(monkeypatch):
    body, _ = inspection(temperature=87)
    assert_withheld(run(monkeypatch, QUESTION, "87 psi", [hit(body)], (1, "coolant temperature 87 C")))


def test_other_property_with_same_number_and_unit_cannot_support_answer(monkeypatch):
    body, _ = inspection()
    body = body.replace("coolant temperature 97 C", "parking brake pressure 87 psi")
    assert_withheld(run(monkeypatch, QUESTION, "87 psi", [hit(body)], (1, "parking brake pressure 87 psi")))


def test_requested_property_cannot_be_matched_by_suffix(monkeypatch):
    body, quote = inspection()
    question = QUESTION.replace("service brake line pressure", "parking brake line pressure")
    assert_withheld(run(monkeypatch, question, "114 psi", [hit(body)], (1, quote)))


@pytest.mark.parametrize("asset", ["VH-6103", "VH-7102"])
def test_observation_without_quarter_still_requires_exact_asset(monkeypatch, asset):
    body, quote = inspection(asset=asset)
    question = QUESTION.replace("2026Q3 ", "")
    result = run(monkeypatch, question, "114 psi", [hit(body)], (1, quote))
    if asset == "VH-6103":
        assert result.grounded
    else:
        assert_withheld(result)


def test_two_plausible_periods_withhold_when_question_has_no_quarter(monkeypatch):
    first, first_quote = inspection(quarter="2026Q1", amount=87)
    second, second_quote = inspection()
    question = QUESTION.replace("2026Q3 ", "")
    assert_withheld(run(monkeypatch, question, "114 psi", [hit(first, page=1), hit(second, page=2)],
                        (1, first_quote), (2, second_quote)))


@pytest.mark.parametrize("mention", ["2026Q1 or 2026Q3", "last quarter", "September 2026"])
def test_ambiguous_or_unsupported_period_withholds(monkeypatch, mention):
    body, quote = inspection()
    assert_withheld(run(monkeypatch, QUESTION.replace("2026Q3", mention), "114 psi", [hit(body)], (1, quote)))


def test_answer_marker_must_point_at_applicable_evidence(monkeypatch, original_pages):
    result = run(monkeypatch, QUESTION, "114 psi [2]", original_pages, (1, RIGHT_QUOTE), (2, SAVED_QUOTE))
    assert_withheld(result)


def test_model_wide_manual_limit_can_use_alias(monkeypatch):
    quote = "The MX-350 service brake line pressure limit during inspection is 120 psi."
    manual = hit(quote, filename="manual.pdf", kind="fleet_manual")
    question = "What is the service brake line pressure limit for VH-6103 during inspection?"
    result = run(monkeypatch, question, "120 psi", [manual], (1, quote))
    assert result.grounded



@pytest.mark.parametrize("question", [
    "What is the inspection interval for VH-6103?",
    "When is the annual inspection scheduled for VH-6103?",
])
def test_model_wide_manual_interval_can_use_alias(monkeypatch, question):
    quote = "Inspection schedule for MX-350: every 12 months."
    manual = hit(quote, filename="manual.pdf", kind="fleet_manual")
    result = run(monkeypatch, question, "Every 12 months.", [manual], (1, quote))
    assert result.grounded


def test_apex_vibration_velocity_matches_drive_end_measurement(monkeypatch):
    filename = "apex_inspection_2026q1.pdf"
    parsed = parse_pdf((CORPUS / "apex" / filename).read_bytes())
    source, = [segment.text for segment in parsed.segments if segment.page_number == 4]
    question = "What vibration velocity did the 2026Q1 inspection record for C-109?"
    quote = "C-109 (CC-300): drive-end vibration measured 5.5 mm/s RMS"
    result = run(monkeypatch, question, "5.5 mm/s RMS", [hit(source, filename, 4, "inspection_report")], (1, quote))
    assert result.grounded

@pytest.mark.parametrize(("answer", "grounded"), [
    ("The service brake-line pressure for VH-6103 was 114 psi in 2026Q3.", True),
    ("The parking brake pressure was 114 psi.", False),
    ("The service brake line pressure was not 114 psi.", False),
    ("114 kPa", False),
])
def test_answer_must_assert_the_requested_property_and_value(monkeypatch, answer, grounded):
    body, quote = inspection()
    result = run(monkeypatch, QUESTION, answer, [hit(body)], (1, quote))
    if grounded:
        assert result.grounded, result.problems
    else:
        assert_withheld(result)


def test_heading_cannot_relabel_measurement_for_different_asset(monkeypatch):
    body, quote = inspection(asset="VH-7102", amount=87)
    body = body.replace("Inspection 2026Q3 - VH-7102", "Inspection 2026Q3 - VH-6103")
    assert_withheld(run(monkeypatch, QUESTION, "87 psi", [hit(body)], (1, quote)))


def test_past_reading_with_quarter_without_word_inspection(monkeypatch):
    body, quote = inspection(quarter="2026Q1", amount=87)
    question = "What was the brake-line pressure for VH-6103 in 2026Q3?"
    assert_withheld(run(monkeypatch, question, "87 psi", [hit(body)], (1, quote)))

@pytest.mark.parametrize("property_label", ["brake pressure", "pressure"])
def test_compact_inspection_requires_explicit_property(monkeypatch, property_label):
    quote = f"2026Q3 inspection: the {property_label} for VH-6103 was 114 psi."
    result = run(monkeypatch, QUESTION, "114 psi", [hit(quote)], (1, quote))
    if property_label == "brake pressure":
        assert result.grounded
    else:
        assert_withheld(result)


@pytest.mark.parametrize("asset", ["VH-6103", "VH-7102"])
def test_direct_service_history_observation_requires_exact_asset(monkeypatch, asset):
    quote = f"The brake line pressure for {asset} measured 114 psi."
    result = run(monkeypatch, "What was the measured brake line pressure for VH-6103?",
                 "114 psi", [hit(quote, kind="service_history")], (1, quote))
    if asset == "VH-6103":
        assert result.grounded
    else:
        assert_withheld(result)
