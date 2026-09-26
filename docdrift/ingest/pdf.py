"""PDF ingestion: PyMuPDF text extraction with section-aware chunking.

Real manuals replace `docdrift.corpus.synthetic`: extract -> chunk -> `upsert_chunks`
plus a `DocumentVersion` row carrying effective date, status and applicability.
A Tesseract OCR fallback for scanned pages is declared here but not wired in.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import Chunk

SECTION_RE = re.compile(r"^\s*(\d+(?:\.\d+){0,2})\s+([A-Z][^\n]{3,80})\s*$", re.M)


@dataclass
class Page:
    number: int
    text: str


def extract_pdf(path: str) -> list[Page]:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("PyMuPDF is required for PDF ingestion: pip install pymupdf") from exc
    doc = fitz.open(path)
    return [Page(number=i + 1, text=p.get_text("text")) for i, p in enumerate(doc)]


def ocr_page(path: str, page_number: int) -> str:  # pragma: no cover - declared fallback
    raise NotImplementedError("Tesseract OCR adapter is declared for scanned documents but not enabled.")


def chunk_pages(pages: list[Page], doc_id: str, version: str,
                max_chars: int = 1400, overlap: int = 150) -> list[Chunk]:
    """Split on numbered headings, then pack to a character budget with overlap."""
    chunks: list[Chunk] = []
    n = 0
    for page in pages:
        headings = list(SECTION_RE.finditer(page.text))
        spans = []
        if headings:
            for i, h in enumerate(headings):
                end = headings[i + 1].start() if i + 1 < len(headings) else len(page.text)
                spans.append((h.group(1), h.group(2).strip(), page.text[h.start():end]))
        else:
            spans.append(("", "", page.text))
        for sec, title, body in spans:
            body = body.strip()
            if not body:
                continue
            start = 0
            while start < len(body):
                piece = body[start:start + max_chars]
                n += 1
                chunks.append(Chunk(chunk_id=f"{doc_id}-{version}-{n:04d}", doc_id=doc_id,
                                    version=version, section=sec or "0", section_title=title or "body",
                                    page=page.number, text=piece.strip()))
                if start + max_chars >= len(body):
                    break
                start += max_chars - overlap
    return chunks
