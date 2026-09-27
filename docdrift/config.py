"""Runtime configuration, governance policy and feature flags.

Defaults are dependency-free so the whole pipeline runs offline on a laptop with no
Docker services and no model download.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from .governance import GovernanceMode


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class FeatureFlags:
    #: Operator photo OCR. Interface and validation only in this prototype.
    enable_operator_ocr: bool = False

    @classmethod
    def from_env(cls) -> "FeatureFlags":
        return cls(enable_operator_ocr=_flag("ENABLE_OPERATOR_OCR", False))


@dataclass
class Thresholds:
    equipment_confidence_min: float = 0.55
    equipment_ambiguity_margin: float = 0.15
    retrieval_top_k: int = 8
    retrieval_candidates: int = 60     # hybrid-retrieval pool handed to the reranker
    drift_top_k: int = 14
    incorporation_term_coverage: float = 0.50
    incorporation_similarity: float = 0.55
    citation_quote_min_chars: int = 25
    topical_relevance_min: float = 0.28     # lexical overlap to call a change answer-relevant
    topical_similarity_min: float = 0.22    # semantic fallback
    topical_min_shared_terms: int = 2       # distinct content terms shared with the question


@dataclass
class OcrLimits:
    max_bytes: int = 8 * 1024 * 1024
    allowed_content_types: tuple[str, ...] = ("image/jpeg", "image/png", "image/webp", "image/heic")
    min_extracted_chars: int = 3


#: Shown on the operator page at all times.
DEMO_QUESTIONS = (
    "Drive M4 trips with fault 5091 after operating for ten minutes.",
    "What regular maintenance does the manual specify for softstarter S2?",
    "What tightening torque do the main terminals of contactor K2 need?",
)

#: Backend choices per stack. "base" is the dependency-free local stack and stays the
#: default; "production" is the Docker Compose stack. Each component can also be
#: overridden on its own (DOCDRIFT_RECORD_STORE, DOCDRIFT_VECTOR_BACKEND, ...).
STACK_PROFILES: dict[str, dict[str, str]] = {
    "base": {
        "record_store_url": "sqlite:///:memory:",
        "vector_backend": "local",
        "graph_backend": "memory",
        "embedder": "hashing",
        "llm_backend": "extractive",
        "audit_store_url": "sqlite:///audit/conversations.sqlite",
    },
    # The API connects with read-only credentials: PostgreSQL role docdrift_reader
    # (SELECT only, plus INSERT on the audit table), Qdrant's read-only API key, and
    # Neo4j read-access sessions. scripts/load_production.py uses the *_loader_* ones.
    "production": {
        "record_store_url": "postgresql://docdrift_reader:docdrift_reader@localhost:5432/docdrift",
        "loader_store_url": "postgresql://docdrift_loader:docdrift_loader@localhost:5432/docdrift",
        "vector_backend": "qdrant",
        "graph_backend": "neo4j",
        "embedder": "sentence-transformers",
        "embedding_model": "BAAI/bge-small-en-v1.5",
        "llm_backend": "ollama",
        "audit_store_url": "postgresql://docdrift_reader:docdrift_reader@localhost:5432/docdrift",
    },
}

_ENV_OVERRIDES = {
    "record_store_url": "DOCDRIFT_RECORD_STORE",
    "vector_backend": "DOCDRIFT_VECTOR_BACKEND",
    "graph_backend": "DOCDRIFT_GRAPH_BACKEND",
    "embedder": "DOCDRIFT_EMBEDDER",
    "llm_backend": "DOCDRIFT_LLM_BACKEND",
    "audit_store_url": "DOCDRIFT_AUDIT_STORE",
    "qdrant_url": "DOCDRIFT_QDRANT_URL",
    "neo4j_url": "DOCDRIFT_NEO4J_URL",
    "ollama_url": "DOCDRIFT_OLLAMA_URL",
    "ollama_model": "DOCDRIFT_OLLAMA_MODEL",
    "embedding_model": "DOCDRIFT_EMBEDDING_MODEL",
    "loader_store_url": "DOCDRIFT_LOADER_STORE",
    "qdrant_api_key": "DOCDRIFT_QDRANT_API_KEY",
    "qdrant_loader_api_key": "DOCDRIFT_QDRANT_LOADER_API_KEY",
}


@dataclass
class Settings:
    thresholds: Thresholds = field(default_factory=Thresholds)
    flags: FeatureFlags = field(default_factory=FeatureFlags.from_env)
    ocr: OcrLimits = field(default_factory=OcrLimits)

    #: STRICT: only a formal change record can establish approval.
    #: FLEXIBLE: a direct approval from an authorised person in Teams or email also counts.
    governance_mode: GovernanceMode = GovernanceMode.STRICT

    stack: str = "base"
    record_store_url: str = "sqlite:///:memory:"
    vector_backend: str = "local"
    graph_backend: str = "memory"
    embedder: str = "hashing"
    llm_backend: str = "extractive"
    loader_store_url: str = ""
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = "docdrift-read"            # Qdrant read-only key (API)
    qdrant_loader_api_key: str = "docdrift-write"    # Qdrant full-access key (loader only)
    neo4j_url: str = "bolt://neo4j:docdrift1@localhost:7687"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    ollama_model: str = "llama3.1:8b"
    ollama_url: str = "http://localhost:11434"

    #: Conversation and decision audit. OFF by default: questions asked on the demo
    #: page live only in the browser tab and are never written anywhere. When ON, each
    #: question, answer, status and the governance reasoning is appended to the audit
    #: store (SQLite file in the base stack, PostgreSQL in production) and to the
    #: JSONL decision log.
    audit_enabled: bool = False
    audit_store_url: str = "sqlite:///audit/conversations.sqlite"
    audit_path: str = "audit/decisions.jsonl"

    @classmethod
    def for_stack(cls, stack: str = "base", **overrides) -> "Settings":
        if stack not in STACK_PROFILES:
            raise ValueError(f"unknown stack {stack!r}; choose one of {sorted(STACK_PROFILES)}")
        return cls(stack=stack, **{**STACK_PROFILES[stack], **overrides})

    @classmethod
    def from_env(cls) -> "Settings":
        stack = os.environ.get("DOCDRIFT_STACK", "base").strip().lower()
        mode = os.environ.get("DOCDRIFT_GOVERNANCE_MODE", "strict").strip().lower()
        overrides = {k: os.environ[v] for k, v in _ENV_OVERRIDES.items() if os.environ.get(v)}
        return cls.for_stack(
            stack,
            governance_mode=GovernanceMode(mode if mode in ("strict", "flexible") else "strict"),
            audit_enabled=_flag("DOCDRIFT_AUDIT_ENABLED", False),
            **overrides)

    def describe_stack(self) -> dict[str, str]:
        return {"stack": self.stack, "record_store": self.record_store_url.split("@")[-1],
                "vector": self.vector_backend, "graph": self.graph_backend,
                "embedder": self.embedder if self.embedder != "sentence-transformers" else self.embedding_model,
                "llm": self.llm_backend if self.llm_backend != "ollama" else f"ollama {self.ollama_model}"}
