"""Document preview for the operator page: page images with the cited passages
highlighted, the extracted page text, and a side-by-side of the current revision
against the synthetic previous revision.

Read-only: PDFs are opened from the local library and rendered in memory; highlight
annotations are drawn on an in-memory copy and never saved.
"""
from __future__ import annotations

import difflib
import functools
import re

from .abb_registry import LIBRARY_DIR, load_manifest
from .corpus.historical import HISTORICAL, current_excerpt, reconstruct_page
from .synthetic_pdf import OUT_DIR as SYNTHETIC_DIR


class PreviewUnavailable(LookupError):
    pass


@functools.lru_cache(maxsize=1)
def _manifest_index() -> dict:
    return {d.doc_key: d for d in load_manifest().documents}


def pdf_path(doc_id: str, version: str | None = None):
    """Resolve a document to a file. Only manifest entries resolve, so a request can
    never name an arbitrary path."""
    rec = _manifest_index().get(doc_id)
    if rec is None:
        raise PreviewUnavailable(f"unknown document {doc_id}")
    hist = HISTORICAL.get(doc_id)
    if version and hist and version == hist.previous:
        p = SYNTHETIC_DIR / f"{doc_id}_rev{hist.previous}_SYNTHETIC.pdf"
        if not p.exists():
            raise PreviewUnavailable("synthetic PDFs not rendered; run scripts/make_synthetic_history.py")
        return p, True
    p = LIBRARY_DIR / rec.library_path
    if not p.exists():
        raise PreviewUnavailable(f"{doc_id} is not in the local library")
    return p, False


def _fragments(quote: str, words: int = 7) -> list[str]:
    toks = quote.split()
    return [" ".join(toks[i:i + words]) for i in range(0, max(1, len(toks) - 2), words)]


@functools.lru_cache(maxsize=64)
def render_page(doc_id: str, page: int, version: str | None = None,
                quotes: tuple[str, ...] = (), dpi: int = 110) -> bytes:
    import pymupdf

    path, synthetic = pdf_path(doc_id, version)
    doc = pymupdf.open(path)
    try:
        index = 0 if synthetic else page - 1
        if not 0 <= index < doc.page_count:
            raise PreviewUnavailable(f"{doc_id} has no page {page}")
        pg = doc[index]
        for quote in quotes:
            for frag in _fragments(re.sub(r"\s+", " ", quote)):
                for rect in pg.search_for(frag):
                    annot = pg.add_highlight_annot(rect)
                    annot.set_colors(stroke=(1.0, 0.85, 0.2))
                    annot.update()
        return pg.get_pixmap(dpi=dpi).tobytes("png")
    finally:
        doc.close()


def page_count(doc_id: str) -> int:
    rec = _manifest_index().get(doc_id)
    return rec.n_pages if rec and rec.n_pages else 0


def word_diff(old: str, new: str) -> list[dict]:
    a, b = old.split(), new.split()
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append({"op": "same", "text": " ".join(a[i1:i2])})
        else:
            if i2 > i1:
                out.append({"op": "removed", "text": " ".join(a[i1:i2])})
            if j2 > j1:
                out.append({"op": "added", "text": " ".join(b[j1:j2])})
    return out


def compare(doc_id: str, page: int, store) -> dict:
    """Current ABB revision against the synthetic previous revision for one page."""
    hist = HISTORICAL.get(doc_id)
    edit = next((e for e in hist.pages if e.page == page), None) if hist else None
    if edit is None:
        raise PreviewUnavailable(f"no previous revision of {doc_id} p.{page}")
    rec = _manifest_index()[doc_id]
    current_version = rec.revision or "1"
    text = " ".join(c.text for c in store.chunks_for(doc_id, current_version) if c.page == page)
    prev, derived = reconstruct_page(text, edit)
    cur = current_excerpt(text, edit) if derived else ""
    return {"doc_id": doc_id, "page": page, "current_version": current_version,
            "previous_version": hist.previous, "previous_effective": str(hist.effective),
            "revision_history": [list(h) for h in hist.history],
            "changes": hist.changes_to_current, "diff": word_diff(prev, cur) if cur else [],
            "previous_is_synthetic": True}
