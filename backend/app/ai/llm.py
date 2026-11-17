"""LLM client interface and the deterministic TEST-ONLY backend.

The deterministic backend is extractive and rule-based. It is used for unit tests, CI and functional
workflow checks only. It says nothing about real LLM quality or latency; the Ollama backend (Phase 3)
is the production-equivalent provider and is evaluated separately.
"""
from dataclasses import dataclass, field
from typing import Protocol

from app.ai import rules
from app.retrieval.text import content_tokens, sentences, tokens


@dataclass
class Passage:
    index: int  # 1-based marker used in the answer, e.g. [1]
    chunk_id: str
    text: str


@dataclass
class CitedQuote:
    index: int
    quote: str


@dataclass
class LLMAnswer:
    text: str
    cited: list[CitedQuote] = field(default_factory=list)


class LLMClient(Protocol):
    name: str
    model: str

    def answer(self, question: str, passages: list[Passage]) -> LLMAnswer: ...

    def extract_fields(self, report_text: str, profile=None) -> dict: ...


class DeterministicLLM:
    name = "deterministic"
    model = "extractive-rules-test-only"

    def answer(self, question: str, passages: list[Passage]) -> LLMAnswer:
        q = set(content_tokens(question))
        picks: list[tuple[float, Passage, str]] = []
        for passage in passages:
            best, best_score = None, 0.0
            for sentence in sentences(passage.text):
                score = len(q & set(tokens(sentence))) / (len(q) or 1)
                if score > best_score:
                    best, best_score = sentence, score
            if best:
                picks.append((best_score, passage, best))
        picks.sort(key=lambda p: -p[0])
        picks = picks[:3]
        if not picks:
            return LLMAnswer(text="", cited=[])
        parts, cited = [], []
        for _, passage, sentence in picks:
            parts.append(f"{sentence.rstrip('.')} [{passage.index}].")
            cited.append(CitedQuote(index=passage.index, quote=sentence))
        return LLMAnswer(text=" ".join(parts), cited=cited)

    def extract_fields(self, report_text: str, profile=None) -> dict:
        if profile is not None:
            from app.profile import engine
            return engine.parse_report(profile, report_text)
        return rules.parse_report(report_text)


class LLMOutputInvalid(Exception):
    """The model returned output that is not valid JSON / does not match the required schema."""


_LLM_CACHE: dict[str, LLMClient] = {}


def get_llm(backend: str) -> LLMClient:
    if backend == "deterministic":
        return DeterministicLLM()
    if backend == "ollama":
        if "ollama" not in _LLM_CACHE:
            from app.ai.ollama_llm import OllamaLLM
            from app.core.config import get_settings

            s = get_settings()
            _LLM_CACHE["ollama"] = OllamaLLM(s.ollama_base_url, s.ollama_model, timeout=s.ollama_timeout)
        return _LLM_CACHE["ollama"]
    raise ValueError(f"Unknown LLM backend '{backend}' (use 'deterministic' or 'ollama')")
