"""H1: evidence-authority ordering for retrieved passages (behind the default-off `authority_demotion` tuning flag).

A passage that labels itself with a generic low-authority marker (e.g. "unverified") must not be the only support for a
value when a higher-authority passage about the same subject was also retrieved. Such passages are moved behind the
unmarked ones (stable order otherwise). Nothing is deleted, and if no relevant unmarked passage was retrieved the order
is unchanged.
"""
import re

from app.retrieval.text import STOPWORDS, tokens

_MARKER = re.compile(r"\b(?:unverified|unconfirmed|not\s+verified|unofficial|hearsay)\b", re.I)
# words that only describe the authority of a statement, not its subject
_AUTHORITY_WORDS = frozenset(
    "unverified unconfirmed verified unofficial hearsay note technician manual usually taken".split())
MIN_SUBJECT_OVERLAP = 0.5


def is_low_authority(text: str) -> bool:
    return bool(_MARKER.search(text))


def _subject_tokens(text: str) -> set[str]:
    # identifiers and values (tokens with digits) carry no subject
    return {t for t in tokens(text)
            if t not in STOPWORDS and t not in _AUTHORITY_WORDS and len(t) > 1 and not any(c.isdigit() for c in t)}


def shares_subject(low_text: str, other_text: str) -> bool:
    subject = _subject_tokens(low_text)
    if not subject:
        return False
    return len(subject & set(tokens(other_text))) / len(subject) >= MIN_SUBJECT_OVERLAP


def apply_authority_order(hits: list) -> list:
    """Return hits with self-declared low-authority passages placed after unmarked passages that share their subject."""
    low = [h for h in hits if is_low_authority(h.text)]
    if not low:
        return list(hits)
    high = [h for h in hits if h not in low]
    demoted = [h for h in low if any(shares_subject(h.text, o.text) for o in high)]
    if not demoted:
        return list(hits)
    return [h for h in hits if h not in demoted] + demoted
