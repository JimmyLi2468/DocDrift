"""Embedder protocol.

Default is a dependency-free hashing embedder so the demo runs with no model
download. `SentenceTransformerEmbedder` is the production path and is loaded
lazily so the import never fails when torch is absent.
"""
from __future__ import annotations

import functools
import hashlib
import math
import re
from typing import Protocol, Sequence

import numpy as np

_TOKEN = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class Embedder(Protocol):
    dim: int
    def encode(self, texts: Sequence[str]) -> np.ndarray: ...


@functools.lru_cache(maxsize=500_000)
def _bucket(token: str, dim: int) -> int:
    return int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest(), "big") % dim


class HashingEmbedder:
    """Sub-linear-tf hashing vectoriser. Deterministic, offline, ~no cost."""

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim

    def _hash(self, token: str) -> int:
        return _bucket(token, self.dim)

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for tok in tokenize(t):
                out[i, self._hash(tok)] += 1.0
        out = np.sign(out) * np.log1p(np.abs(out))
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return out / norms


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        from sentence_transformers import SentenceTransformer  # lazy

        self._model = SentenceTransformer(model_name)
        self.dim = self._model.get_sentence_embedding_dimension()

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        return self._model.encode(list(texts), normalize_embeddings=True)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def build_embedder(name: str = "hashing") -> Embedder:
    if name == "sentence-transformers":
        return SentenceTransformerEmbedder()
    return HashingEmbedder()
