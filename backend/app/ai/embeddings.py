"""Embedding providers.

DeterministicEmbedder is a TEST-ONLY hashed bag-of-words embedder (functional tests and CI). Its behaviour
is lexical and must never be reported as semantic retrieval quality.

SentenceTransformerEmbedder is the real embedding backend (all-MiniLM-L6-v2, 384 dimensions, CPU). It loads
from a pinned revision in a local cache and never downloads implicitly; use scripts/fetch_models.py.
"""
import hashlib
import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from app.core.config import MINILM_MODEL, MINILM_REVISION, get_settings
from app.models import EMBEDDING_DIM
from app.retrieval.text import content_tokens


@dataclass(frozen=True)
class EmbeddingProfileSpec:
    provider: str
    model: str
    revision: str
    dim: int

    def label(self) -> str:
        return f"{self.provider}:{self.model}@{self.revision}:{self.dim}"


class Embedder(Protocol):
    name: str
    model: str
    dim: int
    evidence_threshold: float
    lexical_gate: bool  # also accept passages by raw word overlap (only sensible for the lexical test embedder)
    profile: EmbeddingProfileSpec

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class DeterministicEmbedder:
    name = "deterministic"
    model = "hashed-bow-test-only"
    dim = EMBEDDING_DIM
    evidence_threshold = 0.30
    lexical_gate = True

    def __init__(self, revision: str = "1"):
        self.revision = revision  # a different revision hashes differently (used to test migrations)
        self.profile = EmbeddingProfileSpec("deterministic", self.model, revision, self.dim)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        salt = b"" if self.revision == "1" else self.revision.encode()
        for tok in content_tokens(text):
            digest = hashlib.sha256(salt + tok.encode()).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            vec[0] = 1.0  # avoid zero vectors (undefined cosine distance)
            return vec
        return [v / norm for v in vec]


class SentenceTransformerEmbedder:
    name = "sentence_transformers"
    # Cosine similarity at/above which a passage counts as evidence. Calibrated on the dev split of the
    # evaluation dataset only (never on the held-out test split); see evaluation/reports.
    evidence_threshold = 0.50  # chosen on the dev split of apex-eval-v1 (balanced accuracy 0.958); see reports
    lexical_gate = False  # the similarity threshold alone decides; calibrated on the dev split

    def __init__(self, model: str = MINILM_MODEL, revision: str = MINILM_REVISION,
                 cache_dir: str | None = None, threshold: float | None = None):
        from sentence_transformers import SentenceTransformer  # heavy import, only for the real backend

        self.model = model
        self.revision = revision
        if threshold is not None:
            self.evidence_threshold = threshold
        self._model = SentenceTransformer(model, revision=revision, device="cpu",
                                          cache_folder=cache_dir or get_settings().model_cache_dir,
                                          local_files_only=True)
        self.dim = int(self._model.get_embedding_dimension())
        if self.dim != EMBEDDING_DIM:
            raise ValueError(f"{model} produces {self.dim}-dim vectors; the schema expects {EMBEDDING_DIM}")
        self.profile = EmbeddingProfileSpec("sentence_transformers", model, revision, self.dim)

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False)
        return [[float(x) for x in v] for v in vectors]


@lru_cache(maxsize=4)
def get_embedder(backend: str) -> Embedder:
    if backend == "deterministic":
        return DeterministicEmbedder()
    if backend == "sentence_transformers":
        return SentenceTransformerEmbedder()
    raise ValueError(f"Unknown embedding backend '{backend}' (use 'deterministic' or 'sentence_transformers')")
