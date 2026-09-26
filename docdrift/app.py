"""Wiring. Swap a backend here, nowhere else."""
from __future__ import annotations

from .config import Settings
from .corpus import build_corpus
from .embeddings import build_embedder
from .llm import build_llm
from .pipeline import Pipeline
from .retrieval import HybridRetriever
from .store import LocalVectorStore, MemoryGraphStore, SqliteRecordStore


def build_graph(corpus, graph) -> None:
    for d in corpus.departments:
        graph.add_node(d.department_id, "Department", name=d.name)
    for e in corpus.equipment:
        graph.add_node(e.asset_tag, "Equipment", model=e.model, family=e.family)
        graph.add_node("MODEL:" + e.model, "Model", family=e.family)
        graph.add_edge(e.asset_tag, "HAS_MODEL", "MODEL:" + e.model)
        for doc in e.doc_ids:
            graph.add_edge("MODEL:" + e.model, "DOCUMENTED_BY", doc)
    for v in corpus.versions:
        graph.add_node(v.doc_id, "Document", title=v.title)
        graph.add_node(v.key, "Version", status=v.status, effective=str(v.effective_date))
        graph.add_edge(v.doc_id, "HAS_VERSION", v.key)
        if v.supersedes:
            graph.add_edge(v.key, "SUPERSEDES", f"{v.doc_id}@{v.supersedes}")
        if v.owner_person_id:
            graph.add_edge(v.doc_id, "OWNED_BY", v.owner_person_id)
    for p in corpus.people:
        graph.add_node(p.person_id, "Person", name=p.name, role=p.role)
        graph.add_node("ROLE:" + p.role, "Role")
        graph.add_edge(p.person_id, "HAS_ROLE", "ROLE:" + p.role)
        graph.add_edge(p.person_id, "MEMBER_OF", p.department_id)
    for a in corpus.authority.authorities:
        graph.add_node("SCOPE:" + a.scope_id, "Scope")
        graph.add_edge("ROLE:" + a.role, "AUTHORISED_FOR", "SCOPE:" + a.scope_id)
    for c in corpus.communications:
        graph.add_node(c.comm_id, "Communication", channel=c.channel.value, date=str(c.date))
        graph.add_edge(c.comm_id, "AUTHORED_BY", c.author_person_id)
        if c.change_ref:
            graph.add_node(c.change_ref, "Change")
            graph.add_edge(c.comm_id, "PART_OF", c.change_ref)
        for doc in c.affects_doc_ids:
            graph.add_edge(c.comm_id, "AFFECTS", doc)
        if c.approver_person_id:
            graph.add_edge(c.comm_id, "DECIDED_BY", c.approver_person_id)


class BackendNotAvailable(RuntimeError):
    """A production backend was selected that this build cannot reach or has no adapter for."""


def _record_store(settings: Settings):
    url = settings.record_store_url
    if url.startswith("sqlite:///"):
        return SqliteRecordStore(url[len("sqlite:///"):])
    raise BackendNotAvailable(
        f"record store {url.split('@')[-1]!r}: the PostgreSQL adapter is not implemented yet. "
        "Run with DOCDRIFT_STACK=base, or DOCDRIFT_RECORD_STORE=sqlite:///:memory:.")


def _vector_store(settings: Settings, embedder):
    if settings.vector_backend == "local":
        return LocalVectorStore(embedder)
    raise BackendNotAvailable(
        f"vector backend {settings.vector_backend!r}: the Qdrant adapter is not implemented yet. "
        "Set DOCDRIFT_VECTOR_BACKEND=local to keep the base vector index.")


def _graph_store(settings: Settings):
    if settings.graph_backend == "memory":
        return MemoryGraphStore()
    raise BackendNotAvailable(
        f"graph backend {settings.graph_backend!r}: the Neo4j adapter is not implemented yet. "
        "Set DOCDRIFT_GRAPH_BACKEND=memory to keep the base graph.")


def build_pipeline(settings: Settings | None = None, corpus=None) -> Pipeline:
    """Build the pipeline for the configured stack.

    Every component is chosen independently from `Settings`, so the base stack stays
    available after the production stack exists: `DOCDRIFT_STACK=base` (the default)
    or `production`, plus per-component overrides for mixed setups such as
    "production LLM, base everything else".
    """
    from .audit import build_conversation_store

    settings = settings or Settings()
    corpus = corpus if corpus is not None else build_corpus()

    store = _record_store(settings)
    store.upsert_departments(corpus.departments)
    store.upsert_people(corpus.people)
    store.upsert_equipment(corpus.equipment)
    store.upsert_versions(corpus.versions)
    store.upsert_chunks(corpus.chunks)
    store.upsert_communications(corpus.communications)

    embedder = build_embedder(settings.embedder)
    vectors = _vector_store(settings, embedder)
    vectors.index(
        [c.chunk_id for c in corpus.chunks],
        [f"{c.section_title}. {c.text}" for c in corpus.chunks],
        [{"doc_id": c.doc_id, "version": c.version, "section": c.section} for c in corpus.chunks])

    graph = _graph_store(settings)
    build_graph(corpus, graph)

    retriever = HybridRetriever(corpus.chunks, vectors)
    return Pipeline(store, graph, retriever, embedder, build_llm(settings),
                    corpus.authority, settings, conversations=build_conversation_store(settings))
