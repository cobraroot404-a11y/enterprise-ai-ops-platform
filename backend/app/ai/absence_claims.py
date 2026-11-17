"""Conservative matching of explicit absence claims in cited passages."""
import re

from app.retrieval.text import normalize_ws, sentences

# Recognize common assertion forms even when their full wording cannot be safely matched.
_PREDICATES = {
    "not specified": "unspecified",
    "unspecified": "unspecified",
    "not stated": "unspecified",
    "not documented": "undocumented",
    "undocumented": "undocumented",
    "not recorded": "undocumented",
    "not available": "unavailable",
    "unavailable": "unavailable",
    "not applicable": "inapplicable",
    "inapplicable": "inapplicable",
}
_PREDICATE = "|".join(_PREDICATES)
_PASSIVE = "|".join(phrase.removeprefix("not ") for phrase in _PREDICATES if phrase.startswith("not "))
_ABSENCE = re.compile(
    rf"\b(?:{_PREDICATE}|not (?:yet |currently )?(?:{_PASSIVE}|provided|listed|found)"
    rf"|no\b[^.!?;,]*?\b(?:{_PASSIVE}|exists?|provided|listed|found)"
    rf"|(?:isn't|aren't|wasn't|weren't)\s+(?:{_PASSIVE}|provided|listed|found)"
    r"|there (?:is|are) no|(?:does not|doesn't|do not|don't) (?:contain|exist|specify|document|include))\b"
)
# Full clauses only. A property cannot absorb the "for" that introduces its subject.
_NAME = r"[a-z0-9]+(?:[-' ][a-z0-9]+)*"
_PROPERTY = r"[a-z0-9]+(?:[-' ](?!for\b)[a-z0-9]+)*?"
_PROPERTY_SCOPE = rf"(?P<property>{_PROPERTY})(?: for (?P<subject>{_NAME}))?"
_FINAL_SCOPE = rf"(?: (?P<relation>for|to) (?P<scope>{_NAME}))?"
_SUBJECT_CODE = re.compile(r"(?:model )?([a-z]{1,4}-\d{2,4}[a-z]?)(?: (?:model|motor|pump|vehicle))?")
_ARTICLE = re.compile(r"^(?:the|a|an) ")

# Each entry gives a clause shape and its assertion, or a named predicate to normalize.
_STATEMENTS = (
    (re.compile(rf"{_PROPERTY_SCOPE} (?:is|are) (?P<predicate>{_PREDICATE}){_FINAL_SCOPE}"), ""),
    (re.compile(rf"no {_PROPERTY_SCOPE} (?:is|are) (?P<predicate>{_PASSIVE}){_FINAL_SCOPE}"), ""),
    (re.compile(rf"no (?P<predicate>value|record) exists for {_PROPERTY_SCOPE}"), ""),
    (re.compile(rf"there (?:is|are) no {_PROPERTY_SCOPE}"), "absent"),
    (re.compile(rf"no (?P<property>{_PROPERTY}) exists(?: for (?P<subject>{_NAME}))?"), "absent"),
    (re.compile(rf"(?P<subject>{_NAME}) (?:does not|doesn't|do not|don't) contain (?:any )?(?P<property>{_PROPERTY})"),
     "does not contain"),
)
_QUESTIONS = (
    re.compile(rf"(?:what (?:is |are )?|is there |are there )(?P<property>{_PROPERTY})"
               rf" (?:exists? for|for|of|applies to|apply to) (?P<subject>{_NAME})"),
    re.compile(rf"(?:does|do) (?P<subject>{_NAME}) contain (?:any )?(?P<property>{_PROPERTY})"),
    re.compile(rf"(?:is|are) {_PROPERTY_SCOPE} (?P<predicate>{_PASSIVE}){_FINAL_SCOPE}"),
)


def _subject(name: str) -> str:
    name = _ARTICLE.sub("", name)
    code = _SUBJECT_CODE.fullmatch(name)
    return code[1] if code else name


def _property_and_subject(match: re.Match) -> tuple[str, str]:
    fields = match.groupdict()
    subject = fields.get("subject") or ""
    scope = fields.get("scope") or ""
    # Two scopes cannot be safely associated with a single property.
    if (subject and scope) or (fields.get("relation") == "to" and "applicable" not in fields["predicate"]):
        return "", ""
    return _ARTICLE.sub("", fields["property"]), _subject(subject or scope)


def _assertion(sentence: str) -> tuple[str, str, str] | None:
    sentence = sentence.removesuffix(".").rstrip()
    for pattern, assertion in _STATEMENTS:
        match = pattern.fullmatch(sentence)
        if match:
            prop, subject = _property_and_subject(match)
            if prop:
                if assertion:
                    return prop, subject, assertion
                predicate = match["predicate"]
                return prop, subject, _PREDICATES.get(predicate) or _PREDICATES.get(f"not {predicate}") or predicate
    return None


def unsupported_absence(answer: str, evidence_texts: list[str], question: str) -> bool:
    """Require each recognized negative to match the question and one explicit cited statement."""
    claims = [s for s in sentences(normalize_ws(answer)) if _ABSENCE.search(s)]
    if not claims:
        return False

    question = normalize_ws(question).removesuffix("?")
    requested = {
        _property_and_subject(match) for pattern in _QUESTIONS if (match := pattern.fullmatch(question))
    }
    evidence = {
        statement for passage in evidence_texts for sentence in sentences(normalize_ws(passage))
        if (statement := _assertion(sentence))
    }
    for claim in claims:
        statement = _assertion(claim)
        if statement is None:
            return True
        prop, subject, assertion = statement
        if not any(
            wanted_property == prop and wanted_subject and (not subject or subject == wanted_subject)
            and (prop, wanted_subject, assertion) in evidence
            for wanted_property, wanted_subject in requested
        ):
            return True
    return False
