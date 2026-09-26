"""Pydantic schemas: the evidence contract between every stage of the pipeline."""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from .governance import (AuthorityState, Channel, DecisionState, GovernanceMode,
                         GovernanceVerdict)


# ----------------------------------------------------------------- enterprise records

class Department(BaseModel):
    department_id: str
    name: str
    site: str | None = None


class Person(BaseModel):
    person_id: str
    name: str
    role: str
    department_id: str
    email: str | None = None
    active_from: date | None = None
    active_to: date | None = None


class Equipment(BaseModel):
    asset_tag: str
    name: str
    model: str                          # base type code, e.g. PSTX30
    family: str
    category: str                       # drives / softstarters / motor_protection
    type_code: str | None = None        # full ordering code, e.g. PSTX30-600-70
    library_bundle: str | None = None   # data/library/<bundle> downloaded for this asset
    serial: str | None = None
    firmware: str | None = None
    site: str
    line: str | None = None
    commissioned: date | None = None
    doc_ids: list[str] = Field(default_factory=list)


class ContentProvenance(str, Enum):
    """Where a chunk's text came from. Surfaced in every citation so an ABB
    publication is never confused with demonstration material."""
    ABB_PUBLIC_PDF = "abb_public_pdf"           # extracted from a real ABB document
    SYNTHETIC_HISTORICAL = "synthetic_historical"  # generated n-1 or earlier, watermarked
    SYNTHETIC_PLACEHOLDER = "synthetic_placeholder"  # stand-in when the ABB PDF is unavailable


class DocumentVersion(BaseModel):
    doc_id: str
    version: str
    title: str
    doc_type: str
    effective_date: date
    status: Literal["current", "superseded", "draft", "withdrawn"]
    supersedes: str | None = None
    owner_person_id: str | None = None
    category: str | None = None
    applies_to_families: list[str] = Field(default_factory=list)
    applies_to_models: list[str] = Field(default_factory=list)
    provenance: ContentProvenance = ContentProvenance.SYNTHETIC_PLACEHOLDER
    #: Real ABB library document number, when this version maps to an ABB publication.
    abb_document_id: str | None = None
    source_url: str | None = None
    source_path: str | None = None
    disclaimer: str | None = None

    @property
    def key(self) -> str:
        return f"{self.doc_id}@{self.version}"

    @property
    def is_abb_publication(self) -> bool:
        return self.provenance is ContentProvenance.ABB_PUBLIC_PDF


class Chunk(BaseModel):
    chunk_id: str
    doc_id: str
    version: str
    section: str
    section_title: str
    page: int
    text: str
    provenance: ContentProvenance = ContentProvenance.SYNTHETIC_PLACEHOLDER

    @property
    def citation_label(self) -> str:
        mark = "" if self.provenance is ContentProvenance.ABB_PUBLIC_PDF else " (synthetic)"
        return f"{self.doc_id} v{self.version} S{self.section} p.{self.page}{mark}"


class Communication(BaseModel):
    """Anything said after a document was published, on any supported channel.

    `decision_state` is what the record itself asserts (extracted at ingestion).
    `authority_state` is never taken from the record - DocDrift derives it from
    personnel records and the authority matrix at evaluation time.
    """
    comm_id: str
    channel: Channel
    date: date
    subject: str
    body: str
    author_person_id: str
    participants: list[str] = Field(default_factory=list)

    #: Thread key. Every message about one proposed change shares it, which is how
    #: later approvals, rejections and cancellations are tied to the original.
    change_ref: str | None = None
    decision_state: DecisionState = DecisionState.DISCUSSION
    approver_person_id: str | None = None
    decision_date: date | None = None
    formal_approval_record_id: str | None = None
    scope_id: str | None = None

    affects_doc_ids: list[str] = Field(default_factory=list)
    affects_sections: list[str] = Field(default_factory=list)
    equipment_families: list[str] = Field(default_factory=list)
    equipment_models: list[str] = Field(default_factory=list)
    fault_codes: list[str] = Field(default_factory=list)
    normative_terms: list[str] = Field(default_factory=list)
    references_comm_ids: list[str] = Field(default_factory=list)


# ----------------------------------------------------------------- pipeline artefacts

class EquipmentMatch(BaseModel):
    equipment: Equipment | None
    confidence: float
    evidence: list[str] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    asked_tags: list[str] = Field(default_factory=list)
    fault_codes: list[str] = Field(default_factory=list)
    source: Literal["text", "text+photo"] = "text"


class RetrievedChunk(BaseModel):
    chunk: Chunk
    score: float
    keyword_rank: int | None = None
    vector_rank: int | None = None


class VersionResolution(BaseModel):
    doc_id: str
    title: str
    current: DocumentVersion
    previous: DocumentVersion | None = None
    freshness_search_from: date


class IncorporationCheck(BaseModel):
    incorporated: bool
    term_coverage: float
    similarity: float
    matched_terms: list[str] = Field(default_factory=list)
    missing_terms: list[str] = Field(default_factory=list)
    compared_against: list[str] = Field(default_factory=list)
    reason: str = ""


class CandidateChange(BaseModel):
    communication: Communication
    verdict: GovernanceVerdict
    #: "answer_relevant" bears on the question asked; "asset_open_change" affects the
    #: same asset but a different topic and is disclosed as an advisory instead.
    scope: Literal["answer_relevant", "asset_open_change"] = "asset_open_change"
    incorporation: IncorporationCheck | None = None
    relevance: float = 0.0
    thread: list[str] = Field(default_factory=list)

    @property
    def classification(self) -> str:
        return self.verdict.classification

    @property
    def effective(self) -> bool:
        return self.verdict.effective


class DocumentationStatus(str, Enum):
    VERIFIED_CURRENT = "Verified Current"
    POTENTIAL_APPROVED_UPDATE = "Potential Approved Update"
    INSUFFICIENT_EVIDENCE = "Insufficient Evidence"


class Citation(BaseModel):
    chunk_id: str
    label: str
    quote: str
    page: int
    provenance: ContentProvenance = ContentProvenance.SYNTHETIC_PLACEHOLDER


class GuidanceStep(BaseModel):
    text: str
    citations: list[Citation] = Field(default_factory=list)


class EvidenceBundle(BaseModel):
    question: str
    mode: GovernanceMode = GovernanceMode.STRICT
    equipment: EquipmentMatch
    versions: list[VersionResolution] = Field(default_factory=list)
    guidance_chunks: list[RetrievedChunk] = Field(default_factory=list)
    candidate_changes: list[CandidateChange] = Field(default_factory=list)
    status: DocumentationStatus = DocumentationStatus.INSUFFICIENT_EVIDENCE
    notes: list[str] = Field(default_factory=list)


class GateResult(BaseModel):
    gate: str
    passed: bool
    detail: str
    blocking: bool = True


class ChangeDisclosure(BaseModel):
    """One change, as shown to the operator, with the governance reasoning attached."""
    comm_id: str
    change_ref: str | None
    channel: Channel
    date: date
    subject: str
    classification: str
    decision_state: DecisionState
    authority_state: AuthorityState
    failed_conditions: list[str] = Field(default_factory=list)
    detail: list[str] = Field(default_factory=list)


class OperatorAnswer(BaseModel):
    question: str
    answered: bool
    mode: GovernanceMode = GovernanceMode.STRICT
    equipment_summary: str
    equipment_confidence: float
    guidance: list[GuidanceStep] = Field(default_factory=list)
    applicable_documents: list[str] = Field(default_factory=list)
    status: DocumentationStatus = DocumentationStatus.INSUFFICIENT_EVIDENCE
    pending_change: str | None = None
    approval_evidence: list[str] = Field(default_factory=list)
    other_open_changes: list[str] = Field(default_factory=list)
    #: Every change considered, including the ones that were refused, with the reason.
    evidence_considered: list[ChangeDisclosure] = Field(default_factory=list)
    escalation: str | None = None
    clarification_needed: str | None = None
    gates: list[GateResult] = Field(default_factory=list)
    disclaimer: str = (
        "DocDrift is read-only decision support. It does not modify documentation, "
        "approve changes, or replace formal engineering procedures."
    )
