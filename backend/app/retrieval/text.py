"""Shared text utilities for chunking, tokenization and quote matching."""
import re

STOPWORDS = frozenset(
    "a an and are as at be by can do does for from has have how i if in is it its of on or our "
    "that the their there this to was we were what when where which who why will with you your "
    "should would could about into than then them they these those not no".split()
)

_TOKEN = re.compile(r"[a-z0-9]+")
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def content_tokens(text: str) -> list[str]:
    return [t for t in tokens(text) if t not in STOPWORDS and len(t) > 1 or t.isdigit()]


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(text) if s and s.strip()]


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def overlap_ratio(query: str, passage: str) -> float:
    q = set(content_tokens(query))
    if not q:
        return 0.0
    return len(q & set(tokens(passage))) / len(q)


def chunk_text(text: str, max_chars: int = 900) -> list[str]:
    """Split on paragraph boundaries, then sentences, into chunks of at most max_chars."""
    chunks: list[str] = []
    current = ""
    for para in [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]:
        pieces = [para] if len(para) <= max_chars else sentences(para)
        for piece in pieces:
            if current and len(current) + len(piece) + 1 > max_chars:
                chunks.append(current)
                current = piece
            else:
                current = f"{current} {piece}".strip() if current else piece
    if current:
        chunks.append(current)
    return chunks
