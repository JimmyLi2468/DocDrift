"""Local dense index with metadata filtering - the Qdrant stand-in.

Same call shape as a Qdrant collection (`index` / `search(where=...)`), so the
swap is a class substitution in `app.py`.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np

from ..embeddings import Embedder


class LocalVectorStore:
    def __init__(self, embedder: Embedder) -> None:
        self.embedder = embedder
        self.ids: list[str] = []
        self.payloads: list[dict] = []
        self.matrix: np.ndarray | None = None

    def index(self, ids: Sequence[str], texts: Sequence[str], payloads: Sequence[dict]) -> None:
        vecs = self.embedder.encode(list(texts))
        self.ids.extend(ids)
        self.payloads.extend(payloads)
        self.matrix = vecs if self.matrix is None else np.vstack([self.matrix, vecs])

    def vector_for(self, item_id: str) -> np.ndarray | None:
        pos = {i: k for k, i in enumerate(self.ids)}.get(item_id) if self.matrix is not None else None
        return None if pos is None else self.matrix[pos]

    def encode(self, text: str) -> np.ndarray:
        return self.embedder.encode([text])[0]

    @staticmethod
    def _matches(payload: dict, where: dict) -> bool:
        for k, v in where.items():
            got = payload.get(k)
            if isinstance(v, (list, tuple, set)):
                if got not in v:
                    return False
            elif got != v:
                return False
        return True

    def search(self, query: str, top_k: int, where: dict | None = None) -> list[tuple[str, float]]:
        if self.matrix is None:
            return []
        q = self.embedder.encode([query])[0]
        sims = self.matrix @ q
        if where:
            mask = np.fromiter((self._matches(p, where) for p in self.payloads), bool,
                               count=len(self.payloads))
            sims = np.where(mask, sims, -np.inf)
            where = None
        order = np.argsort(-sims)
        out: list[tuple[str, float]] = []
        for i in order:
            if not np.isfinite(sims[i]):
                break
            out.append((self.ids[i], float(sims[i])))
            if len(out) >= top_k:
                break
        return out
