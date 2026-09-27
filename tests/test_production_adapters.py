"""Production adapters that can be tested without the Docker services.

PostgreSQL and Neo4j themselves are exercised by scripts/check_production.py on a
machine running `docker compose up -d`; here: the Qdrant adapter (in-memory mode),
the graph authority path and its gate, the LLM guard, and the build fingerprint.
"""
import pytest

from docdrift.app import BackendNotAvailable, _check_fingerprints, corpus_fingerprint
from docdrift.governance import AuthorityState
from docdrift.llm import GuardedClient, faithful


def test_graph_authority_path_agrees_with_authority_records_for_every_approval(pipeline, corpus):
    n = 0
    for comm in corpus.communications:
        if not (comm.approver_person_id and comm.scope_id):
            continue
        person = pipeline.store.get_person(comm.approver_person_id)
        if person is None:
            continue
        state, _ = corpus.authority.evaluate(person.role, comm.scope_id, comm.decision_date or comm.date)
        path = pipeline.graph.authority_path(comm.comm_id, str(comm.decision_date or comm.date))
        assert (state is AuthorityState.VERIFIED) == (path is not None), comm.comm_id
        n += 1
    assert n >= 10


def test_authority_path_is_shown_for_the_core_case(pipeline):
    _, bundle = pipeline.ask("Drive M4 trips with fault 5091 after operating for ten minutes.")
    ecn = next(c for c in bundle.candidate_changes if c.communication.comm_id == "ECN-2026-011")
    assert ecn.authority_path and ecn.authority_path.role == "Chief Engineer"
    assert ecn.authority_path.scope_id == ecn.communication.scope_id


def test_graph_disagreement_withholds_the_answer(pipeline, monkeypatch):
    monkeypatch.setattr(pipeline.graph, "authority_path", lambda comm_id, day: None)
    answer, _ = pipeline.ask("Drive M4 trips with fault 5091 after operating for ten minutes.")
    g10 = next(g for g in answer.gates if g.gate == "G10_AUTHORITY_PATH_AGREES")
    assert not g10.passed and "ECN-2026-011" in g10.detail
    assert not answer.answered


@pytest.mark.parametrize("orig,new,ok", [
    ("Tighten the main terminals to 2.5 Nm.", "Tighten main terminals to 2.5 Nm.", True),
    ("Tighten the main terminals to 2.5 Nm.", "Tighten main terminals to 3.5 Nm.", False),
    ("Check parameter 31.22 STO indication run/stop.", "Check the STO indication.", False),
    ("Do not use pressurized air to clean the Softstarter.", "Use pressurized air to clean it.", False),
    ("Check terminal X4.", "Check terminal X4 and X5.", False),
])
def test_rewording_guard(orig, new, ok):
    assert faithful(orig, new)[0] is ok


def test_guarded_client_falls_back_to_the_manual_sentence():
    class Wrong:
        name = "ollama"
        def available(self): return True
        def rephrase(self, s): return s.replace("2.5", "25")
    g = GuardedClient(Wrong())
    assert g.rephrase("Tighten to 2.5 Nm.") == "Tighten to 2.5 Nm."
    assert len(g.rejected) == 1


def test_fingerprint_mismatch_refuses_to_start(corpus):
    fp = corpus_fingerprint(corpus)
    _check_fingerprints({"PostgreSQL": fp, "Qdrant": fp, "Neo4j": fp})
    with pytest.raises(BackendNotAvailable, match="different builds"):
        _check_fingerprints({"PostgreSQL": fp, "Qdrant": "0" * 16})
    with pytest.raises(BackendNotAvailable, match="not loaded"):
        _check_fingerprints({"PostgreSQL": fp, "Neo4j": None})


def test_qdrant_adapter_matches_the_local_index(corpus):
    pytest.importorskip("qdrant_client")
    from docdrift.embeddings import HashingEmbedder
    from docdrift.store.local_vector import LocalVectorStore
    from docdrift.store.qdrant_vector import QdrantVectorStore

    chunks = corpus.chunks[:400]
    args = ([c.chunk_id for c in chunks], [f"{c.section_title}. {c.text}" for c in chunks],
            [{"doc_id": c.doc_id, "version": c.version, "section": c.section} for c in chunks])
    emb = HashingEmbedder()
    local, qd = LocalVectorStore(emb), QdrantVectorStore(":memory:", emb)
    local.index(*args)
    qd.index(*args)
    assert qd.count() == len(chunks)
    doc = chunks[0].doc_id
    for q in ("fault 5091 safe torque off", "tightening torque main terminals", "regular maintenance"):
        a, b = local.search(q, 8), qd.search(q, 8)
        # Same scores; same ids except where scores tie (their order is arbitrary).
        assert [round(s, 4) for _, s in a] == [round(s, 4) for _, s in b], q
        cut = a[4][1]
        assert {c for c, s in a if s > cut + 1e-6} == {c for c, s in b if s > cut + 1e-6}, q
        fa = [cid for cid, _ in local.search(q, 5, where={"doc_id": [doc]})]
        fb = [cid for cid, _ in qd.search(q, 5, where={"doc_id": [doc]})]
        assert len(fa) == len(fb) and all(cid.startswith(doc) for cid in fb)
    assert qd.vector_for(chunks[3].chunk_id) is not None
    qd.put_fingerprint("abc")
    assert qd.get_fingerprint() == "abc"


def test_variant_suffix_does_not_name_the_model(pipeline):
    from docdrift.rerank import names_model
    k2 = pipeline.store.get_equipment("K2")
    assert names_model("AF09 ... AF38 3-pole contactors", k2)
    assert names_model("Technical data AF38-30-00-13", k2)
    assert not names_model("AF09..K ... AF38..K contactors with push-in spring terminals", k2)
    assert not names_model("AF09Z...AF38Z for specific applications", k2)
