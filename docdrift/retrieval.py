"""Hybrid retrieval: BM25 keyword search + dense vector search, fused with
reciprocal rank fusion, under hard metadata filters (family / doc / version)."""
from __future__ import annotations

import math
from collections import Counter
from typing import Sequence

from .embeddings import tokenize
from .models import Chunk, RetrievedChunk


class BM25:
    """Okapi BM25 over an inverted index, so a query touches only the chunks that
    contain its terms. `allowed` restricts scoring to a subset of chunk positions
    (the metadata filter), which is how retrieval stays confined to the documents
    the asset register assigns to the machine in question."""

    def __init__(self, docs: Sequence[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.len: list[int] = []
        self.postings: dict[str, list[tuple[int, int]]] = {}
        for i, d in enumerate(docs):
            toks = tokenize(d)
            self.len.append(len(toks))
            for w, f in Counter(toks).items():
                self.postings.setdefault(w, []).append((i, f))
        n = len(self.len)
        self.avgdl = (sum(self.len) / n) if n else 0.0
        self.idf = {w: math.log(1 + (n - len(p) + 0.5) / (len(p) + 0.5))
                    for w, p in self.postings.items()}

    def scores(self, query: str, allowed: set[int] | None = None) -> dict[int, float]:
        out: dict[int, float] = {}
        for w in set(tokenize(query)):
            idf = self.idf.get(w)
            if idf is None:
                continue
            for i, f in self.postings[w]:
                if allowed is not None and i not in allowed:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * self.len[i] / (self.avgdl or 1))
                out[i] = out.get(i, 0.0) + idf * f * (self.k1 + 1) / denom
        return out


def rrf(rank_lists: list[list[str]], k: int = 60) -> dict[str, float]:
    fused: dict[str, float] = {}
    for ranks in rank_lists:
        for pos, item in enumerate(ranks):
            fused[item] = fused.get(item, 0.0) + 1.0 / (k + pos + 1)
    return fused


class HybridRetriever:
    def __init__(self, chunks: Sequence[Chunk], vector_store) -> None:
        self.chunks = {c.chunk_id: c for c in chunks}
        self.order = [c.chunk_id for c in chunks]
        self.bm25 = BM25([f"{c.section_title}\n{c.text}" for c in chunks])
        self.vs = vector_store

    def search(self, query: str, top_k: int = 8, where: dict | None = None) -> list[RetrievedChunk]:
        def keep(cid: str) -> bool:
            if not where:
                return True
            c = self.chunks[cid]
            for k, v in where.items():
                got = getattr(c, k, None)
                if isinstance(v, (list, tuple, set)):
                    if got not in v:
                        return False
                elif got != v:
                    return False
            return True

        allowed = ({i for i, cid in enumerate(self.order) if keep(cid)} if where else None)
        kw_scores = self.bm25.scores(query, allowed)
        kw_ranked = [self.order[i] for i, _ in
                     sorted(kw_scores.items(), key=lambda p: -p[1])[: top_k * 3]]
        vec_ranked = [cid for cid, _ in self.vs.search(query, top_k=top_k * 3, where=where)]
        vec_ranked = [c for c in vec_ranked if keep(c)]

        fused = rrf([kw_ranked, vec_ranked])
        kw_pos = {c: i for i, c in enumerate(kw_ranked)}
        vec_pos = {c: i for i, c in enumerate(vec_ranked)}
        out = [
            RetrievedChunk(chunk=self.chunks[cid], score=score,
                           keyword_rank=kw_pos.get(cid), vector_rank=vec_pos.get(cid))
            for cid, score in sorted(fused.items(), key=lambda p: -p[1])[:top_k]
        ]
        return out
