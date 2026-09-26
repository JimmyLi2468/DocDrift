"""Render the synthetic historical (n-1) documents as watermarked PDFs.

Every page carries a diagonal watermark and a footer disclaimer so that a printed or
screenshotted page cannot be mistaken for an ABB publication. These files exist only
so the version chain has a real artefact behind it; they are never presented as ABB
content and their chunks are labelled `synthetic_historical` everywhere.
"""
from __future__ import annotations

import pathlib
import textwrap

from .abb_registry import load_manifest
from .corpus.historical import DISCLAIMER, HISTORICAL

WATERMARK = "SYNTHETIC - NOT AN ABB PUBLICATION"
OUT_DIR = pathlib.Path(__file__).resolve().parents[1] / "data" / "synthetic_pdfs"


def _draw_watermark(canvas, width: float, height: float) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica-Bold", 30)
    canvas.setFillColorRGB(0.85, 0.25, 0.25, alpha=0.22)
    canvas.translate(width / 2, height / 2)
    canvas.rotate(38)
    canvas.drawCentredString(0, 0, WATERMARK)
    canvas.drawCentredString(0, -230, WATERMARK)
    canvas.drawCentredString(0, 230, WATERMARK)
    canvas.restoreState()


def render_historical_pdf(doc_id: str, title: str, history, sections: list[tuple[int, str, str]],
                          out_dir: pathlib.Path | str = OUT_DIR) -> pathlib.Path:
    """One compact PDF (1-2 pages): revision-history block, then each reconstructed
    page excerpt. Flows onto a second page only when the excerpts need it."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas as rl_canvas

    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{doc_id}_rev{history.previous}_SYNTHETIC.pdf"
    width, height = A4
    c = rl_canvas.Canvas(str(path), pagesize=A4)
    c.setTitle(f"{title} - revision {history.previous} (SYNTHETIC)")
    c.setAuthor("DocDrift demonstration corpus")
    c.setSubject(DISCLAIMER)

    lines: list[tuple[str, int, str]] = []          # (font, size, text)
    for w in textwrap.wrap(f"{title} - revision {history.previous}", 70):
        lines.append(("Helvetica-Bold", 13, w))
    lines.append(("Helvetica", 8, f"Document {doc_id}   revision {history.previous}   "
                                  f"effective {history.effective}"))
    lines.append(("Helvetica", 4, ""))
    lines.append(("Helvetica-Bold", 9, "Revision history (synthetic)"))
    for rev, when, what in history.history:
        lines.append(("Helvetica", 8, f"   Rev {rev:5s} {when}   {what}"))
    lines.append(("Helvetica", 6, ""))
    for page, sec_title, body in sections:
        lines.append(("Helvetica-Bold", 10, f"p.{page}  {sec_title}"))
        for w in textwrap.wrap(body, 108):
            lines.append(("Helvetica", 8.5, w))
        lines.append(("Helvetica", 6, ""))

    def frame(page_no: int, total: int) -> None:
        _draw_watermark(c, width, height)
        c.setFont("Helvetica-Bold", 9)
        c.setFillColorRGB(0.55, 0.1, 0.1)
        c.drawString(40, height - 36, WATERMARK)
        c.setFont("Helvetica-Oblique", 7)
        for k, line in enumerate(textwrap.wrap(DISCLAIMER, 130)):
            c.drawString(40, 46 - k * 9, line)
        c.setFont("Helvetica", 7)
        c.setFillColorRGB(0.35, 0.35, 0.35)
        c.drawRightString(width - 40, 24, f"page {page_no} of {total}")
        c.setFillColorRGB(0, 0, 0)

    top, bottom = height - 60, 70
    per_page, pages, y, cur = [], [], top, []
    for font, size, text in lines:
        step = size + 3.5
        if y - step < bottom:
            pages.append(cur); cur, y = [], top
        cur.append((font, size, text)); y -= step
    pages.append(cur)
    pages = pages[:2]                          # compact by construction: never more than 2
    for n, content in enumerate(pages, 1):
        frame(n, len(pages))
        y = top
        for font, size, text in content:
            c.setFont(font, size)
            c.drawString(40, y, text)
            y -= size + 3.5
        c.showPage()
    c.save()
    return path


def render_all(out_dir: pathlib.Path | str = OUT_DIR) -> list[pathlib.Path]:
    """One watermarked PDF per reconstructed revision."""
    from .abb_registry import load_chunk_cache
    from .corpus.historical import reconstruct_page

    manifest = load_manifest()
    cache = load_chunk_cache()
    written = []
    for doc_key, history in HISTORICAL.items():
        rec = manifest.get(doc_key)
        if rec is None:
            continue
        pages: dict[int, str] = {}
        for ch in cache.get(doc_key, []):
            pages[ch["page"]] = (pages.get(ch["page"], "") + " " + ch["text"]).strip()
        sections = [(e.page, e.title, reconstruct_page(pages.get(e.page), e)[0])
                    for e in history.pages]
        written.append(render_historical_pdf(doc_key, rec.title, history, sections, out_dir))
    return written
