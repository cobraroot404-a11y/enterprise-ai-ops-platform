"""Verify coolant-temperature alarm thresholds against model-specific cited evidence."""

import re
from decimal import Decimal
from itertools import pairwise

from app.ai.llm import CitedQuote
from app.ai.safeguards import citation_marker_indexes
from app.retrieval.entities import IDENT
from app.retrieval.search import Hit
from app.retrieval.text import normalize_ws, sentences

_MODEL = rf"(?P<model>{IDENT.pattern})"
_PROPERTY = r"coolant temperature alarm"
_QUESTION = re.compile(
    rf"(?:what {_PROPERTY} is set on (?:the )?{_MODEL}"
    rf"|what is the {_PROPERTY} threshold (?:for|on) (?:the )?(?P<threshold_model>{IDENT.pattern}))\??",
    re.IGNORECASE,
)
_TEMPERATURE = r"(?P<value>-?[0-9]+(?:\.[0-9]+)?) *(?:\u00b0 *)?(?P<unit>[cf]|celsius|fahrenheit)"
_MODEL_ALARM = re.compile(
    rf"(?:the )?{_MODEL} raises (?:a|the) {_PROPERTY} at {_TEMPERATURE}", re.IGNORECASE,
)
_COOLANT_ABOVE = re.compile(
    rf"(?:engine )?coolant above {_TEMPERATURE} triggers (?:an|the) alarm on (?:the )?{_MODEL}", re.IGNORECASE,
)
_ALARM_SETTING = re.compile(
    rf"(?:the )?{_PROPERTY} (?:threshold )?(?:for|on) (?:the )?{_MODEL} is (?:set (?:at|to) )?{_TEMPERATURE}",
    re.IGNORECASE,
)
_HEADING = re.compile(rf"{_MODEL}(?: rigid truck)? [-\u2013\u2014] {_PROPERTY}", re.IGNORECASE)
_ROW = re.compile(rf"(?:alarm )?threshold: *{_TEMPERATURE}")
_SCALAR = re.compile(_TEMPERATURE)
_TRAILING_MARKERS = re.compile(r"(?: *\[[0-9]+\])+$")


def _statement(text: str) -> re.Match | None:
    return _MODEL_ALARM.fullmatch(text) or _COOLANT_ABOVE.fullmatch(text) or _ALARM_SETTING.fullmatch(text)


def _temperature(match: re.Match) -> tuple[Decimal, str]:
    return Decimal(match["value"]), match["unit"][0]


def unsupported_coolant_alarm(
    question: str, answer: str, citations: list[CitedQuote], hits: list[Hit],
) -> bool:
    """Check only explicit single-model alarm questions, using model-supplied verified quotes."""
    request = _QUESTION.fullmatch(normalize_ws(question))
    if request is None:
        return False
    model = request["model"] or request["threshold_model"]
    markers = citation_marker_indexes(answer)
    claim = _TRAILING_MARKERS.sub("", normalize_ws(answer).removesuffix(".")).removesuffix(".")
    asserted = _statement(claim) or _SCALAR.fullmatch(claim)
    if asserted is None or asserted.groupdict().get("model", model) != model:
        return True
    expected = _temperature(asserted)

    for citation in citations:
        if markers and citation.index not in markers:
            continue
        source = hits[citation.index - 1].text
        complete_statements = {normalize_ws(part).removesuffix(".") for part in sentences(source)}
        for part in sentences(citation.quote):
            statement = normalize_ws(part).removesuffix(".")
            if statement not in complete_statements:
                continue
            match = _statement(statement)
            if match and match["model"] == model and _temperature(match) == expected:
                return False

        # The citation must cover both adjacent full lines of the same chunk.
        # A flattened quote is fine if the underlying source still has those line boundaries.
        quote = normalize_ws(citation.quote)
        lines = map(normalize_ws, source.splitlines())
        for heading, row in pairwise(lines):
            if f"{heading} {row}" != quote:
                continue
            scope = _HEADING.fullmatch(heading)
            threshold = _ROW.fullmatch(row.removesuffix("."))
            if scope and scope["model"] == model and threshold and _temperature(threshold) == expected:
                return False
    return True
