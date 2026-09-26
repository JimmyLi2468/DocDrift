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


def _fragments(quote: str, words: int) -> list[str]:
    toks = quote.split()
    if len(toks) <= words:
        return [" ".join(toks)] if toks else []
    return [" ".join(toks[i:i + words]) for i in range(0, len(toks) - words + 1, max(1, words - 1))]


_KEY = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:N·?m|Nm|lb\.?in|mm²?|A|V|kW|°C|x Uc|%)(?![\w])|\b[0-9A-F]{4}\b")


_STOP = set("""a an the of to in on at for and or is are be it this that with from by as what which how
does do did should must can could would will need needs needed keep keeps kept show shows check checked
manual manuals specify specified give gives say says tell drive drives softstarter contactor breaker
machine equipment please after before during when why where there their its about any some""".split())


def focus_terms(question: str) -> list[str]:
    """Terms from the operator's question worth marking on a page: fault codes, type
    codes, and two-word phrases ("tightening torque", "main terminals")."""
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9.\-]*", question)
    codes = [w for w in words if re.fullmatch(r"[0-9A-F]{4}|[A-Z]{2,}\d[\w.\-]*", w) and not re.fullmatch(r"[A-Z]\d", w)]
    content = [w.lower() for w in words if w.lower() not in _STOP and len(w) > 2 and not re.fullmatch(r"[A-Z]\d+", w)]
    pairs = [f"{a} {b}" for a, b in zip(content, content[1:])]
    return list(dict.fromkeys(codes + pairs))


def _row_rects(pg, terms: list[str]) -> list:
    """Table rows that name a question term and carry a value: the term's line plus
    every span on the same row (same baseline), so "Tightening torque | 1.5 Nm | 2.5 Nm"
    is marked as one row and the header or empty sub-heading rows are not."""
    import pymupdf
    lines = []
    for block in pg.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = "".join(s["text"] for s in line["spans"]).strip()
            if text:
                lines.append((pymupdf.Rect(line["bbox"]), text))
    out = []
    for rect, text in lines:
        low = text.lower()
        if not any(t.lower() in low for t in terms):
            continue
        row = [r for r, _ in lines if min(r.y1, rect.y1) - max(r.y0, rect.y0) > 0.6 * rect.height]
        row_text = " ".join(x for r, x in lines if r in row)
        if re.search(r"\d", row_text.replace(text, "", 1)) or re.search(r"\b[0-9A-F]{4}\b", text):
            out.extend(row)
    return out


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _prose_lines(pg, quote: str, min_words: int = 6) -> list:
    """Page lines of running text that the quote contains verbatim. Matching whole
    lines survives the line breaks and bullets that defeat phrase search; the length
    floor keeps short table cells ("10 mm", "Rigid") from lighting up."""
    import pymupdf
    q = " " + _norm(quote) + " "
    out = []
    for block in pg.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = _norm("".join(s["text"] for s in line["spans"]))
            if len(text.split()) >= min_words and f" {text} " in q:
                out.append(pymupdf.Rect(line["bbox"]))
    return out


def _highlight_rects(pg, quote: str, terms: list[str] | None = None) -> list:
    """Find a quoted passage on the page. PDF text is laid out in lines and table
    cells, so a sentence rarely matches in one piece: try overlapping runs of six
    words, then three, then the quote's values and codes ("2.5 Nm", "5091")."""
    quote = re.sub(r"\s+", " ", quote).strip(" .")
    rows = _row_rects(pg, [t for t in terms if t.lower() in quote.lower()]) if terms else []
    rects = rows + _prose_lines(pg, quote)
    if rects:
        return rects
    return [r for key in dict.fromkeys(_KEY.findall(quote)) for r in pg.search_for(key)][:6]


@functools.lru_cache(maxsize=64)
def render_page(doc_id: str, page: int, version: str | None = None,
                quotes: tuple[str, ...] = (), dpi: int = 110, question: str = "") -> bytes:
    import pymupdf

    path, synthetic = pdf_path(doc_id, version)
    doc = pymupdf.open(path)
    try:
        index = 0 if synthetic else page - 1
        if not 0 <= index < doc.page_count:
            raise PreviewUnavailable(f"{doc_id} has no page {page}")
        pg = doc[index]
        terms = focus_terms(question) if question else None
        seen = set()
        for quote in quotes:
            for rect in _highlight_rects(pg, quote, terms):
                if tuple(rect) in seen:
                    continue
                seen.add(tuple(rect))
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
