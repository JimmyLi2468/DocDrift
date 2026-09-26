"""Operator-photo OCR extension - interface and feature flag only.

Nothing in this module performs OCR in the current prototype. It defines the
contract, the validation rules and the disabled default so the rest of the system
can be written against the final shape:

    operator uploads a photo
        -> validate content type and size            (validate_upload)
        -> extract visible text                      (OperatorPhotoExtractor.extract)
        -> detect model number, asset tag, fault code (PhotoExtraction)
        -> operator reviews and edits the extraction  (PhotoExtraction.apply_edits)
        -> combine with the mandatory text question   (combine_with_question)
        -> continue through the normal DocDrift workflow

The photo never becomes the sole input: a text question is mandatory, and the
extraction is treated as an operator-editable hint, not as evidence. Nothing
extracted from a photo is ever cited.

    ENABLE_OPERATOR_OCR=false
"""
from __future__ import annotations

import re
from typing import Protocol

from pydantic import BaseModel, Field

from ..config import OcrLimits, Settings

ASSET_TAG_RE = re.compile(r"\b([A-Z]{1,3}-?\d{1,3})\b")
FAULT_RE = re.compile(r"(?:fault|code|alarm|err)\s*#?\s*(\d{3,5})", re.I)
MODEL_RE = re.compile(r"\b(ACS\d{3}(?:-\d{2})?|ACQ\d{3}|PSTX\d+|PSR\d+|MS1\d{2}(?:-[\d.]+[A-Z]*)?"
                      r"|AF\d{2,4}|UMC\d+)\b", re.I)


class OperatorOcrDisabled(RuntimeError):
    """Raised when a photo is submitted while ENABLE_OPERATOR_OCR is false."""


class PhotoValidationError(ValueError):
    """Raised when an upload fails the type or size check."""


class PhotoExtraction(BaseModel):
    """What OCR believes it saw. Every field is operator-editable before use."""
    raw_text: str = ""
    detected_models: list[str] = Field(default_factory=list)
    detected_asset_tags: list[str] = Field(default_factory=list)
    detected_fault_codes: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    engine: str = "none"
    edited_by_operator: bool = False

    def apply_edits(self, *, models: list[str] | None = None,
                    asset_tags: list[str] | None = None,
                    fault_codes: list[str] | None = None) -> "PhotoExtraction":
        return self.model_copy(update={
            "detected_models": models if models is not None else self.detected_models,
            "detected_asset_tags": asset_tags if asset_tags is not None else self.detected_asset_tags,
            "detected_fault_codes": fault_codes if fault_codes is not None else self.detected_fault_codes,
            "edited_by_operator": True,
        })

    @property
    def is_empty(self) -> bool:
        return not (self.detected_models or self.detected_asset_tags or self.detected_fault_codes)


class OperatorPhotoExtractor(Protocol):
    name: str
    def available(self) -> bool: ...
    def extract(self, image: bytes, content_type: str) -> PhotoExtraction: ...


class DisabledPhotoExtractor:
    """The default. Refuses politely and explains which flag turns it on."""
    name = "disabled"

    def available(self) -> bool:
        return False

    def extract(self, image: bytes, content_type: str) -> PhotoExtraction:
        raise OperatorOcrDisabled(
            "Operator photo OCR is not enabled in this build. Set ENABLE_OPERATOR_OCR=true "
            "and install the Tesseract adapter to turn it on.")


class TesseractPhotoExtractor:
    """Declared future implementation. Not wired in: the body is deliberately absent
    so that no half-working OCR path can be reached by accident."""
    name = "tesseract"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def available(self) -> bool:
        if not self.settings.flags.enable_operator_ocr:
            return False
        try:
            import pytesseract  # noqa: F401
        except ImportError:
            return False
        return True

    def extract(self, image: bytes, content_type: str) -> PhotoExtraction:  # pragma: no cover
        if not self.available():
            raise OperatorOcrDisabled(
                "Tesseract adapter unavailable: enable ENABLE_OPERATOR_OCR and install pytesseract.")
        raise NotImplementedError(
            "The Tesseract extraction path is declared but not implemented in this prototype.")


def validate_upload(data: bytes, content_type: str, limits: OcrLimits) -> None:
    if content_type not in limits.allowed_content_types:
        raise PhotoValidationError(
            f"unsupported image type '{content_type}'; allowed: "
            f"{', '.join(limits.allowed_content_types)}")
    if not data:
        raise PhotoValidationError("empty upload")
    if len(data) > limits.max_bytes:
        raise PhotoValidationError(
            f"image is {len(data)} bytes, over the {limits.max_bytes} byte limit")


def parse_extracted_text(text: str) -> PhotoExtraction:
    """Field detection over already-extracted text. Pure and testable: this part of
    the flow works today, so the OCR engine is the only missing piece."""
    return PhotoExtraction(
        raw_text=text,
        detected_models=sorted({m.upper() for m in MODEL_RE.findall(text)}),
        detected_asset_tags=sorted({t.replace("-", "") for t in ASSET_TAG_RE.findall(text)
                                    if not MODEL_RE.fullmatch(t)}),
        detected_fault_codes=sorted(set(FAULT_RE.findall(text))),
        confidence=0.0, engine="text-parse")


def combine_with_question(question: str, extraction: PhotoExtraction | None) -> str:
    """Photo evidence augments the operator's text; it never replaces it."""
    if not question or not question.strip():
        raise PhotoValidationError(
            "a text question is mandatory; a photo on its own is not accepted")
    if extraction is None or extraction.is_empty:
        return question
    hints = ", ".join(extraction.detected_asset_tags + extraction.detected_models
                      + [f"fault {f}" for f in extraction.detected_fault_codes])
    return f"{question.strip()} (from photo: {hints})"


def build_extractor(settings: Settings) -> OperatorPhotoExtractor:
    if settings.flags.enable_operator_ocr:
        candidate = TesseractPhotoExtractor(settings)
        if candidate.available():
            return candidate
    return DisabledPhotoExtractor()
