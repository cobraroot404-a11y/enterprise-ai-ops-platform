"""Verify explicit whole-unit service intervals against the cited statement."""

import re
from decimal import Decimal

from app.ai.llm import CitedQuote
from app.ai.safeguards import citation_marker_indexes
from app.retrieval.entities import IDENT
from app.retrieval.search import Hit
from app.retrieval.text import normalize_ws, sentences

_MODEL = IDENT.pattern
_UNIT = r"(?:[a-z]+ )?unit"
_QUESTION = re.compile(
    rf"what is the (?:service interval (?:of|for) (?:the )?(?P<model>{_MODEL}) (?P<unit>{_UNIT})"
    rf"|(?P<first_model>{_MODEL}) (?P<first_unit>{_UNIT}) service interval)\??",
    re.IGNORECASE,
)
_DURATION = r"(?P<amount>[0-9]+(?:\.[0-9]+)?) (?P<units>hours?|days?|weeks?|months?|years?)"
_TRAILING_MARKERS = re.compile(r"(?: *\[[0-9]+\])+$")


def _interval(match: re.Match) -> tuple[Decimal, str]:
    return Decimal(match["amount"]), match["units"].removesuffix("s")


def unsupported_whole_unit_interval(
    question: str, answer: str, citations: list[CitedQuote], hits: list[Hit],
) -> bool:
    """Require the exact model, affirmative service scope and duration in one verified sentence."""
    request = _QUESTION.fullmatch(normalize_ws(question))
    if request is None:
        return False
    model = re.escape(request["model"] or request["first_model"])
    unit = re.escape(request["unit"] or request["first_unit"])
    subject = rf"(?:the )?{model} (?:{unit}|(?:whole )?unit)"
    claim = re.compile(
        rf"(?:(?:the )?service interval (?:of|for) {subject}(?: is |: *)"
        rf"|{subject} service interval(?: is |: *)"
        rf"|{subject} (?:must be|should be|is) serviced every ){_DURATION}"
    )
    markers = citation_marker_indexes(answer)
    answer = _TRAILING_MARKERS.sub("", normalize_ws(answer).removesuffix(".")).removesuffix(".")
    asserted = claim.fullmatch(answer) or re.fullmatch(rf"(?:every )?{_DURATION}", answer)
    if asserted is None:
        return True
    for citation in citations:
        if markers and citation.index not in markers:
            continue
        source = sentences(normalize_ws(hits[citation.index - 1].text))
        for statement in sentences(normalize_ws(citation.quote)):
            # Require a complete source statement, including any qualifiers outside the quote.
            statement = statement.removesuffix(".")
            match = claim.fullmatch(statement)
            if match and _interval(match) == _interval(asserted) and any(
                sentence.removesuffix(".") == statement for sentence in source
            ):
                return False
    return True
