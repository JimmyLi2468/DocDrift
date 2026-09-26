"""Stage 8a - citation validation.

Every quote must be recoverable verbatim (whitespace-normalised) from the chunk it
claims to come from, and that chunk must belong to a document version marked current.
"""
from __future__ import annotations

from .models import Citation, OperatorAnswer


def _norm(s: str) -> str:
    return " ".join(s.split()).lower()


def validate_citation(cit: Citation, store) -> tuple[bool, str]:
    chunk = store.get_chunk(cit.chunk_id)
    if chunk is None:
        return False, f"{cit.chunk_id} does not exist in the chunk store"
    if _norm(cit.quote) not in _norm(chunk.text):
        return False, f"quote not found verbatim in {cit.chunk_id}"
    if cit.page != chunk.page:
        return False, f"page {cit.page} does not match chunk page {chunk.page}"
    versions = {v.version: v for v in store.versions_for_doc(chunk.doc_id)}
    v = versions.get(chunk.version)
    if v is None or v.status != "current":
        return False, f"{chunk.doc_id} v{chunk.version} is not the current version"
    return True, "ok"


def validate_answer(answer: OperatorAnswer, store) -> list[tuple[Citation, bool, str]]:
    results = []
    for step in answer.guidance:
        for cit in step.citations:
            ok, why = validate_citation(cit, store)
            results.append((cit, ok, why))
    return results
