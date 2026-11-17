"""Fixed-answer coverage for the deterministic absence-claim check."""

import pytest
from app.ai import rag
from app.ai.safeguards import check_answer_support
from test_question_asset_id_exemption import run

QUESTION = "What is the bearing grease interval for the AC-490 motor?"
ANSWER = "The bearing grease interval for the AC-490 motor is not specified [1]."
NEGATIVE = "No bearing grease interval is specified for model AC-490."
SILENCE = "Model AC-490 has a drive-end bearing temperature of 81 C."
PROBLEM = "absence claim lacks explicit cited evidence for the requested property and subject"


@pytest.mark.parametrize(("passages", "supported"), [
    ([SILENCE], False),
    ([NEGATIVE], True),
    ([NEGATIVE.replace("bearing grease", "coolant")], False),
    ([NEGATIVE.replace("AC-490", "VX-530") + " " + SILENCE], False),
    (["AC-490 is in service. No bearing grease interval is specified."], False),
    (["No bearing grease interval is specified.", SILENCE], False),
    (["The bearing grease interval is not stated for the AC-490 motor."], True),
    (["The bearing grease interval is not documented for the AC-490 motor."], False),
    (["No bearing grease interval is specified for model AC-490 during commissioning."], False),
    (["If required, no bearing grease interval is specified for model AC-490."], False),
    ([NEGATIVE.replace(".", "?")], False),
    (["No bearing grease interval is specified for model AC-4900.", SILENCE], False),
    (["The seal material is unavailable for AC-490.", "The bearing grease interval is 300 hours for AC-490."], False),
])
def test_absence_requires_explicit_aligned_evidence(passages, supported):
    assert check_answer_support(ANSWER, passages, QUESTION) == ([] if supported else [PROBLEM])


@pytest.mark.parametrize(("question", "answer", "evidence"), [
    (QUESTION, "The bearing grease interval is not specified.", NEGATIVE),
    (QUESTION, "The bearing grease interval is not documented for AC-490.",
     "No bearing grease interval is documented for model AC-490."),
    (QUESTION, "The bearing grease interval for AC-490 is unavailable.",
     "The bearing grease interval is not available for model AC-490."),
    (QUESTION, "No value exists for the bearing grease interval for model AC-490.",
     "No value exists for the bearing grease interval for AC-490."),
    (QUESTION, "No bearing grease interval exists for model AC-490.",
     "There is no bearing grease interval for AC-490."),
    (QUESTION, "The bearing grease interval is not applicable to model AC-490.",
     "No bearing grease interval is applicable for AC-490."),
    ("Does the AC-490 manual contain a bearing grease interval?",
     "The AC-490 manual does not contain a bearing grease interval.",
     "The AC-490 manual doesn't contain any bearing grease interval."),
    ("What inspection record exists for model AC-490?", "No inspection record exists for AC-490.",
     "There is no inspection record for model AC-490."),
    (QUESTION, "No record exists for the bearing grease interval for AC-490.",
     "No record exists for the bearing grease interval for AC-490."),
])
def test_absence_predicates_require_an_explicit_match(question, answer, evidence):
    assert check_answer_support(answer, [evidence], question) == []
    assert check_answer_support(answer, [SILENCE], question) == [PROBLEM]


def test_answer_and_evidence_must_also_match_the_question():
    coolant = NEGATIVE.replace("bearing grease", "coolant")
    assert check_answer_support(coolant, [coolant], QUESTION) == [PROBLEM]
    wrong_motor = NEGATIVE.replace("AC-490", "VX-530")
    assert check_answer_support(wrong_motor, [wrong_motor, SILENCE], QUESTION) == [PROBLEM]


def test_unresolved_and_additional_absence_claims_withheld():
    assert check_answer_support("It is not specified.", [NEGATIVE], QUESTION) == [PROBLEM]
    assert check_answer_support(ANSWER + " Its temperature is unavailable.", [NEGATIVE], QUESTION) == [PROBLEM]
    assert check_answer_support(ANSWER.replace(" [1].", " and its temperature is unavailable."),
                                [NEGATIVE], QUESTION) == [PROBLEM]
    assert check_answer_support("The manual for AC-490 does not specify the bearing grease interval.",
                                [SILENCE], QUESTION) == [PROBLEM]


def test_positive_claims_and_unsupported_numbers_keep_existing_behavior():
    assert check_answer_support("Model AC-490 is at 81 C [1].", [SILENCE], QUESTION) == []
    assert check_answer_support("Model AC-490 is at 82 C [1].", [SILENCE], QUESTION) == [
        "number(s) not found in the cited evidence: 82",
    ]


@pytest.mark.parametrize("h3_enabled", [False, True])
def test_negative_and_empty_answers_keep_distinct_verifier_outcomes(monkeypatch, h3_enabled):
    outcomes = {}
    for answer, passage in ((ANSWER, SILENCE), (ANSWER, NEGATIVE), ("", SILENCE)):
        outcomes[answer, passage], _ = run(monkeypatch, enabled=h3_enabled, asset="AC-490", rows=[],
                                           question=QUESTION, answer=answer, quote=passage, passage=passage)
    withheld = outcomes[ANSWER, SILENCE]
    assert not withheld.grounded and not withheld.insufficient_evidence
    assert withheld.citations == [] and withheld.problems == [PROBLEM]
    grounded = outcomes[ANSWER, NEGATIVE]
    assert grounded.grounded and grounded.citations[0]["quote"] == NEGATIVE
    empty = outcomes["", SILENCE]
    assert empty.answer == rag.INSUFFICIENT and not empty.grounded and empty.insufficient_evidence
    assert empty.problems == []


def test_negative_claim_does_not_bypass_quote_or_source_validation(monkeypatch):
    invalid, _ = run(monkeypatch, asset="AC-490", rows=[], question=QUESTION,
                     answer=ANSWER, quote=NEGATIVE, passage=SILENCE)
    assert not invalid.grounded and "quote not found" in invalid.problems[0]
    foreign, _ = run(monkeypatch, asset="AC-490", rows=[], question=QUESTION,
                     answer=ANSWER, quote=NEGATIVE, passage=NEGATIVE, owns_citation=False)
    assert not foreign.grounded and foreign.problems == [
        "citation source chunk is not a current chunk owned by this tenant",
    ]
