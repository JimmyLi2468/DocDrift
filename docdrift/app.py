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
    for s in corpus.authority.scopes:
        graph.add_node("SCOPE:" + s.scope_id, "Scope", description=s.description)
    for a in corpus.authority.authorities:
        graph.add_node("SCOPE:" + a.scope_id, "Scope")
        graph.add_node("ROLE:" + a.role, "Role")
        graph.add_edge("ROLE:" + a.role, "AUTHORISED_FOR", "SCOPE:" + a.scope_id,
                       valid_from=str(a.valid_from),
                       valid_to=str(a.valid_to) if a.valid_to else None,
                       delegation_of=a.delegation_of)
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
        if c.scope_id:
            graph.add_edge(c.comm_id, "IN_SCOPE", "SCOPE:" + c.scope_id)
    graph.flush()


class BackendNotAvailable(RuntimeError):
    """A production backend was selected that this build cannot reach or has no adapter for."""


def _record_store(settings: Settings, url: str | None = None):
    url = url or settings.record_store_url
    if url.startswith("sqlite:///"):
        return SqliteRecordStore(url[len("sqlite:///"):])
    if url.startswith("postgresql://"):
        from .store.postgres_store import PostgresRecordStore
        try:
            return PostgresRecordStore(url)
        except Exception as exc:
            raise BackendNotAvailable(f"PostgreSQL at {url.split('@')[-1]} is not reachable ({exc}). "
                                      "Is `docker compose up -d` running?") from exc
    raise BackendNotAvailable(f"unsupported record store {url.split('@')[-1]!r}")


def _vector_store(settings: Settings, embedder, loader: bool = False):
    if settings.vector_backend == "local":
        return LocalVectorStore(embedder)
    if settings.vector_backend == "qdrant":
        from .store.qdrant_vector import QdrantVectorStore
        key = settings.qdrant_loader_api_key if loader else settings.qdrant_api_key
        return QdrantVectorStore(settings.qdrant_url, embedder, api_key=key or None)
    raise BackendNotAvailable(f"unsupported vector backend {settings.vector_backend!r}")


def _graph_store(settings: Settings, loader: bool = False):
    if settings.graph_backend == "memory":
        return MemoryGraphStore()
    if settings.graph_backend == "neo4j":
        from .store.neo4j_graph import Neo4jGraphStore
        try:
            return Neo4jGraphStore(settings.neo4j_url, read_only=not loader)
        except Exception as exc:
            raise BackendNotAvailable(f"Neo4j at {settings.neo4j_url.split('@')[-1]} is not reachable "
                                      f"({exc})") from exc
    raise BackendNotAvailable(f"unsupported graph backend {settings.graph_backend!r}")


def corpus_fingerprint(corpus) -> str:
    """Identifies one build of the corpus. The loader stamps it into every service; the
    API refuses to start when the services were loaded from different builds."""
    import hashlib
    from . import __version__
    h = hashlib.sha256(__version__.encode())
    for c in sorted(corpus.chunks, key=lambda c: c.chunk_id):
        h.update(c.chunk_id.encode()); h.update(hashlib.sha1(c.text.encode()).digest())
    for m in sorted(corpus.communications, key=lambda m: m.comm_id):
        h.update(m.model_dump_json().encode())
    for v in sorted(corpus.versions, key=lambda v: v.key):
        h.update(v.key.encode())
    h.update(corpus.authority.model_dump_json().encode())
    return h.hexdigest()[:16]


def corpus_from_store(store):
    """Rebuild the corpus object from a loaded external record store, so in-process
    components (local vector index, memory graph) in a mixed stack use exactly the
    records the store holds."""
    from .corpus import Corpus
    return Corpus(departments=store.all_departments(), people=store.all_people(),
                  equipment=store.all_equipment(), versions=store.all_versions(),
                  chunks=store.all_chunks(), communications=store.all_communications(),
                  authority=store.get_authority())


def load_services(settings: Settings, corpus=None, progress=print) -> dict:
    """Write the corpus into every external service of the stack. Used only by
    scripts/load_production.py, with the loader credentials."""
    corpus = corpus if corpus is not None else build_corpus()
    fp = corpus_fingerprint(corpus)
    report = {"fingerprint": fp}
    if settings.record_store_url.startswith("postgresql://"):
        pg = _record_store(settings, settings.loader_store_url or settings.record_store_url)
        pg.create_schema(); pg.truncate()
        pg.upsert_departments(corpus.departments); pg.upsert_people(corpus.people)
        pg.upsert_equipment(corpus.equipment); pg.upsert_versions(corpus.versions)
        pg.upsert_chunks(corpus.chunks); pg.upsert_communications(corpus.communications)
        pg.put_authority(corpus.authority); pg.put_fingerprint(fp)
        report["postgres"] = pg.counts()
        progress(f"PostgreSQL  {report['postgres']}")
    if settings.vector_backend == "qdrant":
        embedder = build_embedder(settings.embedder, settings.embedding_model)
        vs = _vector_store(settings, embedder, loader=True)
        vs.recreate()
        vs.index([c.chunk_id for c in corpus.chunks],
                 [f"{c.section_title}. {c.text}" for c in corpus.chunks],
                 [{"doc_id": c.doc_id, "version": c.version, "section": c.section} for c in corpus.chunks],
                 progress=lambda n, total: progress(f"Qdrant      embedded {n}/{total}") if n % 1024 < 256 or n == total else None)
        vs.put_fingerprint(fp)
        report["qdrant"] = vs.count()
        vs.close()
        progress(f"Qdrant      {report['qdrant']} vectors")
    if settings.graph_backend == "neo4j":
        g = _graph_store(settings, loader=True)
        g.clear(); g.ensure_schema()
        build_graph(corpus, g)
        g.put_fingerprint(fp)
        report["neo4j"] = g.count()
        g.close()
        progress(f"Neo4j       nodes, relationships = {report['neo4j']}")
    return report


def _check_fingerprints(parts: dict[str, str | None]) -> None:
    missing = [k for k, v in parts.items() if not v]
    if missing:
        raise BackendNotAvailable(f"{', '.join(missing)} not loaded yet: run scripts/load_production.py")
    if len(set(parts.values())) > 1:
        raise BackendNotAvailable(
            "the services hold different builds of the corpus "
            f"({', '.join(f'{k}={v}' for k, v in parts.items())}): run scripts/load_production.py again")


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
    external = {}                                 # service -> fingerprint it was loaded with
    if isinstance(store, SqliteRecordStore):
        corpus = corpus if corpus is not None else build_corpus()
        store.upsert_departments(corpus.departments)
        store.upsert_people(corpus.people)
        store.upsert_equipment(corpus.equipment)
        store.upsert_versions(corpus.versions)
        store.upsert_chunks(corpus.chunks)
        store.upsert_communications(corpus.communications)
    else:
        # Loaded beforehand by scripts/load_production.py; the API only reads.
        external["PostgreSQL"] = store.get_fingerprint()
        _check_fingerprints(external)
        corpus = corpus_from_store(store)
    store.seal()                         # read-only from here on, enforced by the database

    embedder = build_embedder(settings.embedder, settings.embedding_model)
    vectors = _vector_store(settings, embedder)
    if settings.vector_backend == "local":
        vectors.index(
            [c.chunk_id for c in corpus.chunks],
            [f"{c.section_title}. {c.text}" for c in corpus.chunks],
            [{"doc_id": c.doc_id, "version": c.version, "section": c.section} for c in corpus.chunks])
    else:
        external["Qdrant"] = vectors.get_fingerprint()

    graph = _graph_store(settings)
    if settings.graph_backend == "memory":
        build_graph(corpus, graph)
    else:
        external["Neo4j"] = graph.get_fingerprint()
    if external:
        # Every external service must hold the same build - and, in a mixed stack with
        # the in-process record store, the build on this disk.
        parts = dict(external)
        if isinstance(store, SqliteRecordStore):
            parts = {"local corpus": corpus_fingerprint(corpus), **parts}
        _check_fingerprints(parts)

    retriever = HybridRetriever(corpus.chunks, vectors)
    return Pipeline(store, graph, retriever, embedder, build_llm(settings),
                    corpus.authority, settings, conversations=build_conversation_store(settings))

