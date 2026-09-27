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
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        from sentence_transformers import SentenceTransformer  # lazy

        self.model_name = model_name
        self._model = SentenceTransformer(model_name)
        dim = getattr(self._model, "get_embedding_dimension", None) or self._model.get_sentence_embedding_dimension
        self.dim = dim()
        self._cache: dict[str, np.ndarray] = {}
        # Optional on-disk cache (DOCDRIFT_EMBEDDING_CACHE=data/cache): the base stack
        # with real embeddings then re-embeds only new chunks on restart. The
        # production stack does not need it - Qdrant keeps the vectors.
        import os
        import pathlib
        d = os.environ.get("DOCDRIFT_EMBEDDING_CACHE")
        self._disk = (pathlib.Path(d) / f"embeddings_{model_name.replace('/', '_')}.npz") if d else None
        if self._disk and self._disk.exists():
            z = np.load(self._disk, allow_pickle=False)
            self._cache = dict(zip(z["keys"].tolist(), z["vecs"]))

    @staticmethod
    def _key(text: str) -> str:
        import hashlib
        return hashlib.sha1(text.encode()).hexdigest()

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        texts = list(texts)
        keys = [self._key(t) for t in texts]
        missing = {k: t for k, t in zip(keys, texts) if k not in self._cache}
        if missing:
            vecs = self._model.encode(list(missing.values()), normalize_embeddings=True, batch_size=64)
            self._cache.update(zip(missing.keys(), vecs))
            if self._disk and len(missing) >= 100:
                self._disk.parent.mkdir(parents=True, exist_ok=True)
                np.savez(self._disk, keys=np.array(list(self._cache)), vecs=np.stack(list(self._cache.values())))
        return np.stack([self._cache[k] for k in keys]) if texts else np.zeros((0, self.dim))


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def build_embedder(name: str = "hashing", model_name: str | None = None) -> Embedder:
    if name == "sentence-transformers":
        return SentenceTransformerEmbedder(model_name or "BAAI/bge-small-en-v1.5")
    return HashingEmbedder()
