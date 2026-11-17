"""Bind observed QA readings to the cited inspection record that measured them."""

import re
from collections.abc import Iterator
from decimal import Decimal

from app.ai.authority import is_low_authority
from app.ai.llm import CitedQuote
from app.ai.safeguards import citation_marker_indexes
from app.ai.suppression import NOTE_SOURCE_KINDS, parse_fields
from app.retrieval.search import Hit
from app.retrieval.text import normalize_ws

INSPECTION_KINDS = {"inspection_report", "depot_inspection"}
_ASSET_ID = r"[a-z]{1,4}-[0-9]{2,4}[a-z]?"
_ASSET = re.compile(rf"(?<![\w./–—-]){_ASSET_ID}(?![\w/–—-]|\.\w|,[0-9])")
_QUARTER = re.compile(r"\b[0-9]{4}q[1-4]\b")
_PERIOD_HINT = re.compile(r"\b(?:[0-9]{4}(?:q[0-9]+)?|quarters?|q[1-4]|"
                          r"january|february|march|april|may|june|july|august|september|october|november|december"
                          r"|last|latest|most recent|previous|today|yesterday)\b")
_OBSERVED = re.compile(r"\b(?:recorded|measured|observed|did .+ (?:record|measure|report))\b")
_INSPECTION = re.compile(r"\binspections?\b")
_READING_REQUEST = re.compile(r"\breadings?\b")
_PAST_READING = re.compile(r"^what (?:was|were)\b")
_PRESCRIPTIVE = re.compile(
    r"\b(?:should|procedure|recommended|specification|limit|required|interval|schedul(?:e|ed|ing)|frequency|"
    r"checklist|instructions|threshold|minimum|maximum|rated|standard)\b"
)
_PROPERTIES = {
    "service brake line pressure": "brake line pressure",
    "brake line pressure": "brake line pressure",
    "brake pressure": "brake line pressure",
    "drive end vibration": "vibration velocity",
    "drive end vibration velocity": "vibration velocity",
    "vibration velocity": "vibration velocity",
    "bearing temperature": "bearing temperature",
    "coolant temperature": "coolant temperature",
}
_PROPERTY = re.compile(rf"\b(?:{'|'.join(_PROPERTIES)})\b")
_ASKED_PROPERTY = re.compile(r"^what (?:was |were |is )?(?:the )?(.+?) (?:did|was (?:measured|recorded|observed))\b")
_INLINE_INSPECTION = re.compile(rf"(?P<quarter>{_QUARTER.pattern}) inspection: ")
_HEADING = re.compile(rf"inspection (?P<quarter>{_QUARTER.pattern}) - (?P<asset>{_ASSET_ID})")
_READING = re.compile(rf"(?P<asset>{_ASSET_ID}) \({_ASSET_ID}\): (?P<fields>.+)")
_FIELD_SEPARATOR = re.compile(r" and |; ")
_NUMBER = r"[+-]?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?"
_UNIT = r"(?:mm/s(?: rms)?|mm|psi|kpa|bar|°?[cf]|rpm|v|a|%)"
_QUANTITY = re.compile(rf"(?<![\w.,+-])(?P<number>{_NUMBER}) *(?P<unit>{_UNIT})(?![\w/])")
_ASSERTION = re.compile(
    rf"(?:the )?(?:recorded )?(?P<property>[a-z]+(?:[ -][a-z]+)*?)"
    rf"(?: (?:for|on) {_ASSET_ID})?(?: in {_QUARTER.pattern})?"
    rf"(?: was(?: measured at| recorded as)? | measured |: ){_QUANTITY.pattern}"
    rf"(?: (?:for|on) {_ASSET_ID})?(?: in {_QUARTER.pattern})?"
)
_FIELD = re.compile(rf"(?P<property>[a-z]+(?:[ -][a-z]+)*?)(?: measured)? {_QUANTITY.pattern}")


def _property(label: str) -> str:
    label = label.replace("-", " ")
    return _PROPERTIES.get(label, label)


def _quantity(match: re.Match) -> tuple[Decimal, str]:
    return Decimal(match["number"].replace(",", "")), match["unit"].removeprefix("°")


def _compact_reading(
    hit: Hit, quote: str, asset: str, quarter: str | None, prop: str, inspection_requested: bool,
) -> Iterator[tuple[str | None, tuple[Decimal, str], bool]]:
    """Support a single explicit observation with its scope stated in the sentence."""
    source = normalize_ws(hit.text).removesuffix(".")
    inline = _INLINE_INSPECTION.match(source)
    if inline and hit.kind in INSPECTION_KINDS:
        period = inline["quarter"]
        if quarter and period != quarter:
            return
        statement = source[inline.end():]
    elif not inspection_requested and not quarter and hit.kind in NOTE_SOURCE_KINDS:
        period, statement = None, source
        fields = parse_fields(source)
        if fields:
            ids = set(re.findall(r"(?:^|; )(?:equipment_id|vehicle_id|asset_id): ([^;]+)", source))
            if ids != {asset}:
                return
            statement = fields.get("description", "").removesuffix(".")
            label, sep, details = statement.partition(": ")
            if sep and is_low_authority(label):
                statement = details
        if not _OBSERVED.search(statement):
            return
    else:
        return
    match = _ASSERTION.fullmatch(statement)
    periods = set(_QUARTER.findall(statement))
    if (match and _property(match["property"]) == prop and set(_ASSET.findall(statement)) == {asset}
            and (not periods or periods == {period})):
        quoted = normalize_ws(quote).removesuffix(".")
        yield period, _quantity(match), quoted in {source, statement} and source.count(statement) == 1


def _readings(
    hit: Hit, quote: str, asset: str, quarter: str | None, prop: str, inspection_requested: bool,
) -> Iterator[tuple[str | None, tuple[Decimal, str], bool]]:
    """Read the first measurement sentence under an exact inspection heading.

    Keep PDF line wrapping within that sentence. Later notes and other records cannot contribute
    fields or supply the location of a quote.
    """
    heading, _, body = hit.text.partition("\n")
    heading = normalize_ws(heading)
    scope = _HEADING.fullmatch(heading)
    if not scope:
        yield from _compact_reading(hit, quote, asset, quarter, prop, inspection_requested)
        return
    if hit.kind not in INSPECTION_KINDS or scope["asset"] != asset or (quarter and scope["quarter"] != quarter):
        return
    # Each supported chunk has one inspection heading and one measurement sentence.
    if any(_HEADING.fullmatch(normalize_ws(line)) for line in body.splitlines()):
        return
    body = normalize_ws(body)
    sentence = re.split(r"\.(?: |$)", body, maxsplit=1)[0]
    reading = _READING.fullmatch(sentence)
    if not reading or reading["asset"] != asset:
        return
    quote = normalize_ws(quote)
    passage = f"{heading} {body}"
    start = passage.find(quote)
    if start < 0 or passage.find(quote, start + 1) != -1:
        return

    offset = len(heading) + 1 + reading.start("fields")
    for field in _FIELD_SEPARATOR.split(reading["fields"]):
        measurement = _FIELD.fullmatch(field)
        if measurement and _property(measurement["property"]) == prop:
            quoted = start <= offset and offset + len(field) <= start + len(quote)
            yield scope["quarter"], _quantity(measurement), quoted
        offset += len(field)
        separator = _FIELD_SEPARATOR.match(passage, offset)
        if separator:
            offset += len(separator[0])


def unsupported_inspection_observation(
    question: str, answer: str, citations: list[CitedQuote], hits: list[Hit],
) -> bool:
    """Withhold an asset observation if the verified citations cannot establish one applicable reading."""
    question = normalize_ws(question)
    assets = set(_ASSET.findall(question))
    if not assets:
        return False
    props = {_property(label) for label in _PROPERTY.findall(question.replace("-", " "))}
    quarters = set(_QUARTER.findall(question))
    inspection_requested = bool(_INSPECTION.search(question))
    if not _OBSERVED.search(question):
        # A manual procedure or limit can mention inspection without asking for an actual reading.
        asks_for_reading = (
            inspection_requested or _READING_REQUEST.search(question)
            or (props and (quarters or _PAST_READING.match(question)))
        )
        if not asks_for_reading or _PRESCRIPTIVE.search(question):
            return False
    if match := _ASKED_PROPERTY.match(question):
        props = {_property(match[1])}
    remaining = _QUARTER.sub("", _ASSET.sub("", question))
    if len(assets) != 1 or len(props) != 1 or len(quarters) > 1 or _PERIOD_HINT.search(remaining):
        return True
    asset, prop = next(iter(assets)), next(iter(props))
    quarter = next(iter(quarters), None)

    markers = citation_marker_indexes(answer)
    answer = normalize_ws(re.sub(r"\[[\d, –-]+\]", " ", answer)).removesuffix(".").rstrip()
    answer_assets, answer_quarters = set(_ASSET.findall(answer)), set(_QUARTER.findall(answer))
    if answer_assets - {asset} or len(answer_quarters) > 1:
        return True
    assertion = _INLINE_INSPECTION.sub("", answer, count=1)
    quantity = _QUANTITY.fullmatch(assertion)
    if quantity is None:
        quantity = _ASSERTION.fullmatch(assertion)
        if quantity is None or _property(quantity["property"]) != prop:
            return True
    value = _quantity(quantity)

    readings = set()
    quoted_readings = set()
    for citation in citations:
        if markers and citation.index not in markers:
            continue
        hit = hits[citation.index - 1]
        for period, measured, quoted in _readings(hit, citation.quote, asset, quarter, prop, inspection_requested):
            readings.add((period, measured))
            if quoted:
                quoted_readings.add((period, measured))
    if len(readings) != 1 or readings != quoted_readings:
        return True
    period, measured = readings.pop()
    return value != measured or bool(answer_quarters - {period})
