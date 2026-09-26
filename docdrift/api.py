"""FastAPI surface and the operator demo page.

Read-only by construction: no route mutates a business record. The only write the
backend can make is the audit trail, and only when `DOCDRIFT_AUDIT_ENABLED=true`.

    PYTHONPATH=. uvicorn docdrift.api:app --port 8000      # then open http://localhost:8000
"""
from __future__ import annotations

import pathlib
import uuid

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .app import build_pipeline
from .config import DEMO_QUESTIONS, Settings
from .corpus import build_corpus
from .governance import GovernanceMode
from .ingest.operator_photo import (OperatorOcrDisabled, PhotoValidationError,
                                    build_extractor, parse_extracted_text, validate_upload)
from .models import EvidenceBundle, OperatorAnswer
from .preview import PreviewUnavailable, compare, page_count, pdf_path, render_page
from .views import build_view

WEB_DIR = pathlib.Path(__file__).resolve().parent / "web"

settings = Settings.from_env()
corpus = build_corpus()
_pipeline = build_pipeline(settings, corpus)
_extractor = build_extractor(settings)

app = FastAPI(title="DocDrift", version="0.3.0",
              description="Local, read-only maintenance intelligence with documentation-drift "
                          "detection and explicit change governance.")


class AskRequest(BaseModel):
    question: str
    mode: GovernanceMode | None = None
    include_evidence: bool = False
    session_id: str | None = None


class AskResponse(BaseModel):
    answer: OperatorAnswer
    evidence: EvidenceBundle | None = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "llm": _pipeline.llm.name,
            "governance_mode": settings.governance_mode.value,
            "features": {"operator_ocr": settings.flags.enable_operator_ocr,
                         "ocr_engine": _extractor.name}}


@app.get("/api/config")
def config() -> dict:
    return {"stack": {**settings.describe_stack(), "llm_active": _pipeline.llm.name},
            "governance_mode": settings.governance_mode.value,
            "audit_enabled": settings.audit_enabled,
            "operator_ocr": settings.flags.enable_operator_ocr,
            "demo_questions": list(DEMO_QUESTIONS),
            "corpus": corpus.summary()}


@app.get("/corpus/summary")
def corpus_summary() -> dict:
    return corpus.summary()


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    answer, bundle = _pipeline.ask(req.question, mode=req.mode, session_id=req.session_id)
    return AskResponse(answer=answer, evidence=bundle if req.include_evidence else None)


@app.post("/api/ask")
def ask_view(req: AskRequest) -> dict:
    """The operator page's call: the answer plus the structured views the page needs."""
    turn_id = uuid.uuid4().hex
    answer, bundle = _pipeline.ask(req.question, mode=req.mode, session_id=req.session_id,
                                   turn_id=turn_id)
    return {"turn_id": turn_id, "stored": settings.audit_enabled,
            **build_view(answer, bundle, _pipeline.store)}


@app.get("/api/documents/{doc_id}/pages/{page}.png")
def page_image(doc_id: str, page: int, version: str | None = None,
               q: list[str] = Query(default=[]), question: str = "") -> Response:
    try:
        png = render_page(doc_id, page, version, tuple(q[:8]), question=question[:300])
    except PreviewUnavailable as exc:
        raise HTTPException(404, str(exc)) from exc
    return Response(png, media_type="image/png")


@app.get("/api/documents/{doc_id}/pages/{page}/text")
def page_text(doc_id: str, page: int, version: str | None = None) -> dict:
    versions = [v for v in _pipeline.store.versions_for_doc(doc_id)]
    if not versions:
        raise HTTPException(404, f"unknown document {doc_id}")
    v = next((x for x in versions if x.version == version), None) or \
        next(x for x in versions if x.status == "current")
    chunks = [c for c in _pipeline.store.chunks_for(doc_id, v.version) if c.page == page]
    return {"doc_id": doc_id, "version": v.version, "page": page,
            "provenance": v.provenance.value, "pages": page_count(doc_id),
            "text": "\n\n".join(c.text for c in chunks)}


@app.get("/api/documents/{doc_id}/pages/{page}/compare")
def page_compare(doc_id: str, page: int) -> dict:
    try:
        return compare(doc_id, page, _pipeline.store)
    except PreviewUnavailable as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/documents/{doc_id}/pdf")
def document_pdf(doc_id: str, version: str | None = None) -> FileResponse:
    try:
        path, _ = pdf_path(doc_id, version)
    except PreviewUnavailable as exc:
        raise HTTPException(404, str(exc)) from exc
    return FileResponse(path, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{path.name}"'})


@app.get("/api/audit/conversations")
def audit_conversations(session_id: str | None = None) -> dict:
    """Stored turns - empty unless audit is enabled."""
    store = _pipeline.conversations
    return {"audit_enabled": settings.audit_enabled,
            "turns": store.turns(session_id) if store is not None else []}


@app.get("/equipment/{asset_tag}")
def equipment(asset_tag: str) -> dict:
    eq = _pipeline.store.get_equipment(asset_tag.upper())
    if eq is None:
        raise HTTPException(404, f"unknown asset tag {asset_tag}")
    return eq.model_dump()


@app.post("/ask/photo")
async def ask_with_photo(question: str = Form(...), photo: UploadFile = File(...)) -> dict:
    """Operator photo flow. Declared now, disabled in this build.

    The text question stays mandatory even once OCR is enabled: the photo only
    contributes an operator-editable hint about which machine is meant.
    """
    data = await photo.read()
    try:
        validate_upload(data, photo.content_type or "", settings.ocr)
    except PhotoValidationError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        extraction = _extractor.extract(data, photo.content_type or "")
    except OperatorOcrDisabled as exc:
        raise HTTPException(501, str(exc)) from exc
    except NotImplementedError as exc:  # pragma: no cover
        raise HTTPException(501, str(exc)) from exc
    answer, _ = _pipeline.ask(question, photo=extraction)
    return answer.model_dump()


@app.post("/photo/parse")
def parse_photo_text(text: str = Form(...)) -> dict:
    """The field-detection half of the photo flow, which does work today: given text
    already read off a rating plate, return the editable model/tag/fault extraction."""
    return parse_extracted_text(text).model_dump()


# The demo page. Mounted last so it never shadows an API route.
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
