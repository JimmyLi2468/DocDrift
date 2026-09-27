"""Qdrant vector store for the production stack.

Same interface as `LocalVectorStore`: `index`, `search(where=...)`, `vector_for`.
Point ids are UUIDv5 of the chunk id, so re-loading the corpus overwrites rather than
duplicates. Metadata filters become Qdrant payload filters and run inside Qdrant.
Only `scripts/load_production.py` indexes; the API only searches.
"""
from __future__ import annotations

import uuid
from typing import Sequence

import numpy as np

from ..embeddings import Embedder

_NS = uuid.UUID("5b1f3c1e-8d2a-4c61-9a57-0d7c1f2e9b10")


def point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(_NS, chunk_id))


class QdrantVectorStore:
    META = "docdrift_meta"

    def __init__(self, url: str, embedder: Embedder, collection: str = "docdrift_chunks",
                 api_key: str | None = None, client=None) -> None:
        from qdrant_client import QdrantClient  # lazily: the base stack does not need it

        if client is not None:
            self.client = client
        elif url == ":memory:":
            self.client = QdrantClient(location=":memory:")
        elif url.startswith("file:"):                  # embedded on-disk mode, for tests
            self.client = QdrantClient(path=url[len("file:"):])
        else:
            # A read-only key for the API, the full key for the loader (docker-compose.yml).
            self.client = QdrantClient(url=url, api_key=api_key, https=url.startswith("https"),
                                       check_compatibility=False)
        self.embedder, self.collection = embedder, collection

    def put_fingerprint(self, fp: str) -> None:
        from qdrant_client import models
        if self.client.collection_exists(self.META):
            self.client.delete_collection(self.META)
        self.client.create_collection(self.META, vectors_config=models.VectorParams(size=1, distance=models.Distance.DOT))
        self.client.upsert(self.META, points=[models.PointStruct(id=1, vector=[1.0],
                                                                payload={"fingerprint": fp, "collection": self.collection})])

    def get_fingerprint(self) -> str | None:
        try:
            got = self.client.retrieve(self.META, ids=[1], with_payload=True)
            return got[0].payload.get("fingerprint") if got else None
        except Exception:
            return None

    # ---------------------------------------------------------------- writes
    def recreate(self) -> None:
        from qdrant_client import models
        if self.client.collection_exists(self.collection):
            self.client.delete_collection(self.collection)
        dim = int(self.embedder.encode(["dimension probe"]).shape[1])
        self.client.create_collection(
            self.collection, vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE))
        for field in ("doc_id", "version", "section"):
            self.client.create_payload_index(self.collection, field, models.PayloadSchemaType.KEYWORD)

    def index(self, ids: Sequence[str], texts: Sequence[str], payloads: Sequence[dict],
              batch: int = 256, progress=None) -> None:
        from qdrant_client import models
        if not self.client.collection_exists(self.collection):
            self.recreate()
        for i in range(0, len(ids), batch):
            vecs = self.embedder.encode(list(texts[i:i + batch]))
            self.client.upsert(self.collection, points=[
                models.PointStruct(id=point_id(cid), vector=np.asarray(v, dtype=float).tolist(),
                                   payload={**p, "chunk_id": cid})
                for cid, v, p in zip(ids[i:i + batch], vecs, payloads[i:i + batch])])
            if progress:
                progress(min(i + batch, len(ids)), len(ids))

    # ---------------------------------------------------------------- reads
    def close(self) -> None:
        self.client.close()

    def count(self) -> int:
        if not self.client.collection_exists(self.collection):
            return 0
        return self.client.count(self.collection, exact=True).count

    @staticmethod
    def _filter(where: dict | None):
        from qdrant_client import models
        if not where:
            return None
        must = []
        for k, v in where.items():
            if isinstance(v, (list, tuple, set)):
                must.append(models.FieldCondition(key=k, match=models.MatchAny(any=[str(x) for x in v])))
            else:
                must.append(models.FieldCondition(key=k, match=models.MatchValue(value=str(v))))
        return models.Filter(must=must)

    def search(self, query: str, top_k: int, where: dict | None = None) -> list[tuple[str, float]]:
        q = np.asarray(self.embedder.encode([query])[0], dtype=float).tolist()
        res = self.client.query_points(self.collection, query=q, query_filter=self._filter(where),
                                       limit=top_k, with_payload=["chunk_id"])
        return [(p.payload["chunk_id"], float(p.score)) for p in res.points]

    def vector_for(self, item_id: str) -> np.ndarray | None:
        got = self.client.retrieve(self.collection, ids=[point_id(item_id)], with_vectors=True)
        return np.asarray(got[0].vector) if got else None

    def encode(self, text: str) -> np.ndarray:
        return self.embedder.encode([text])[0]
