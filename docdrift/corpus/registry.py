"""Build DocDrift's document registry: every ABB publication in the manifest as
version n, plus a synthetic n-1 for the few documents a change thread targets."""
from __future__ import annotations

import re
from datetime import date, timedelta

from ..abb_registry import AbbManifest, load_chunk_cache, load_manifest
from ..models import Chunk, ContentProvenance, DocumentVersion
from .historical import DISCLAIMER, HISTORICAL, reconstruct_page

#: How far before the current revision the reconstructed previous revision sits.
HISTORICAL_LAG_DAYS = 430


def family_of(model: str) -> str:
    m = re.match(r"^(ACS\d{3}|ACH\d{3}|ACQ\d{3}|PSTX|PSR|PSE|MS1\d{2}|MS4\d{2}|UMC\d+|AF)", model)
    return m.group(1) if m else model


def version_label(rec) -> str:
    return rec.revision or "1"


def previous_effective(current: date) -> date:
    return current - timedelta(days=HISTORICAL_LAG_DAYS)


def build_registry(manifest: AbbManifest | None = None, chunk_cache: dict | None = None,
                   owners: dict[str, str] | None = None
                   ) -> tuple[list[DocumentVersion], list[Chunk]]:
    manifest = manifest or load_manifest()
    cache = chunk_cache if chunk_cache is not None else load_chunk_cache()
    owners = owners or {}
    versions: list[DocumentVersion] = []
    chunks: list[Chunk] = []

    for rec in manifest.documents:
        cached = cache.get(rec.doc_key) or []
        # A publication that is on disk and was ingested but has no text layer (CAD
        # drawings, scanned sheets) is still an ABB publication; it just cannot be
        # quoted until the OCR adapter exists. Only a missing library is a placeholder.
        ingested = rec.doc_key in cache
        provenance = (ContentProvenance.ABB_PUBLIC_PDF if (cached or (ingested and rec.available))
                      else ContentProvenance.SYNTHETIC_PLACEHOLDER)
        version = version_label(rec)
        effective = rec.published or date(2020, 1, 1)
        families = sorted({family_of(m) for m in rec.covers_models}) or [rec.category]
        history = HISTORICAL.get(rec.doc_key)

        versions.append(DocumentVersion(
            doc_id=rec.doc_key, version=version, title=rec.title, doc_type=rec.doc_type,
            effective_date=effective, status="current",
            supersedes=history.previous if history else None,
            owner_person_id=owners.get(rec.category), category=rec.category,
            applies_to_families=families, applies_to_models=rec.covers_models,
            provenance=provenance, abb_document_id=rec.abb_document_id,
            source_url=rec.source_url,
            source_path=f"data/library/{rec.library_path}" if rec.available else None))

        if cached:
            chunks += [Chunk(chunk_id=c["chunk_id"], doc_id=rec.doc_key, version=version,
                             section=c["section"], section_title=c["section_title"],
                             page=c["page"], text=c["text"],
                             provenance=ContentProvenance.ABB_PUBLIC_PDF) for c in cached]
        elif not ingested:
            chunks.append(Chunk(
                chunk_id=f"{rec.doc_key}-placeholder", doc_id=rec.doc_key, version=version,
                section="0", section_title="content not indexed", page=1,
                text=(f"The text of ABB document {rec.doc_key} ({rec.title}) is not indexed on "
                      f"this machine. Place the library under data/library/ and run "
                      f"scripts/import_library.py and scripts/ingest_abb.py. No ABB content is "
                      f"reproduced or invented here."),
                provenance=ContentProvenance.SYNTHETIC_PLACEHOLDER))

        if not history:
            continue
        pages: dict[int, str] = {}        # long pages are split into chunks; rejoin them
        for c in cached:
            pages[c["page"]] = (pages.get(c["page"], "") + " " + c["text"]).strip()
        versions.append(DocumentVersion(
            doc_id=rec.doc_key, version=history.previous,
            title=f"{rec.title} - synthetic historical reconstruction", doc_type=rec.doc_type,
            effective_date=history.effective, status="superseded",
            owner_person_id=owners.get(rec.category), category=rec.category,
            applies_to_families=families, applies_to_models=rec.covers_models,
            provenance=ContentProvenance.SYNTHETIC_HISTORICAL, disclaimer=DISCLAIMER,
            source_path=f"data/synthetic_pdfs/{rec.doc_key}_rev{history.previous}_SYNTHETIC.pdf"))
        for edit in history.pages:
            body, _ = reconstruct_page(pages.get(edit.page), edit)
            chunks.append(Chunk(
                chunk_id=f"{rec.doc_key}-{history.previous}-p{edit.page:04d}",
                doc_id=rec.doc_key, version=history.previous, section=str(edit.page),
                section_title=f"{edit.title} (previous revision)", page=edit.page,
                text=f"{body} [{DISCLAIMER}]", provenance=ContentProvenance.SYNTHETIC_HISTORICAL))
    return versions, chunks
