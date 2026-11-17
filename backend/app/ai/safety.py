"""Prompt-injection heuristics for retrieved (untrusted) text.

Retrieved documents are data, never instructions. Chunks matching these patterns are flagged at
ingestion, excluded from LLM context, and surfaced to the caller. Model output can never trigger
business actions: ticket submission is only reachable through the human-approval workflow.
"""
import re

_PATTERNS = [
    r"ignore\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier)\s+(instructions|rules|prompts?)",
    r"disregard\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier|system)",
    r"(reveal|print|show|repeat)\s+(your\s+|the\s+)?system\s+prompt",
    r"you\s+are\s+now\s+(an?\s+|the\s+)?",
    r"\b(approve|submit|close|delete)\s+(the\s+|this\s+|all\s+)?(ticket|tickets|incident|incidents)\b",
    r"do\s+not\s+(tell|inform|notify)\s+the\s+user",
    r"<\|?(system|assistant|im_start)\|?>",
    r"new\s+instructions\s*:",
]
_COMPILED = [re.compile(p, re.IGNORECASE) for p in _PATTERNS]


def looks_like_injection(text: str) -> bool:
    return any(p.search(text) for p in _COMPILED)


# E8b: attempts, written in a QUESTION, to override the evidence rules, the tenant boundary or the approval workflow. Such a request is refused
# as insufficient evidence; no document or model output can lift these rules.
_OVERRIDE = [re.compile(p, re.IGNORECASE) for p in (
    r"\b(ignore|disregard|bypass|skip|override|forget)\b[^.?!]{0,40}\b(evidence|rules?|instructions?|policy|policies|supervisor|approvals?|tenant)\b",
    r"\banswer\s+from\s+(memory|your\s+own\s+knowledge)\b",
    r"\bwithout\s+(any\s+)?(evidence|citations?|review|approval)\b",
    r"\bno\s+approvals?\s+(are\s+)?(needed|required)\b",
)]


def looks_like_override(question: str) -> bool:
    return any(p.search(question) for p in _OVERRIDE)
