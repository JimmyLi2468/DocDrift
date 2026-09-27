"""Check the production stack after scripts/load_production.py.

    PYTHONPATH=. python scripts/check_production.py

1. Each service is reachable and holds the same build of the corpus.
2. The API's credentials really are read-only: a write is attempted through each one
   and must be refused by the service itself.
3. The three demo questions give the same status, equipment and cited pages as the
   base stack. (Wording may differ: the local LLM rephrases steps.)
"""
from __future__ import annotations

import os
import sys

# The loader saved every chunk embedding here, so the base-stack comparison below does
# not have to embed the corpus again.
os.environ.setdefault("DOCDRIFT_EMBEDDING_CACHE", "data/cache")

from docdrift.app import BackendNotAvailable, build_pipeline
from docdrift.config import DEMO_QUESTIONS, Settings

OK, FAIL = "ok  ", "FAIL"


def refused(fn) -> tuple[bool, str]:
    try:
        fn()
    except Exception as exc:  # the service said no - which is the point
        return True, type(exc).__name__ + ": " + str(exc).splitlines()[0][:90]
    return False, "the write was accepted"


def main() -> int:
    os.environ["DOCDRIFT_STACK"] = "production"
    settings = Settings.from_env()
    failures = 0
    try:
        prod = build_pipeline(settings)
    except BackendNotAvailable as exc:
        print(f"{FAIL} services: {exc}")
        return 1
    print(f"{OK} services reachable and loaded from one build")
    print(f"     LLM: {prod.llm.name}" + ("" if prod.llm.name == "ollama" else
          "  (Ollama not reachable - answers use the manual's own sentences)"))

    # --- 2. read-only credentials
    probes = {
        "PostgreSQL (docdrift_reader)": lambda: prod.store.conn.execute(
            "UPDATE docdrift.communications SET channel = channel"),
        "PostgreSQL schema change": lambda: prod.store.conn.execute("CREATE TABLE docdrift.x (y int)"),
        "Neo4j (read session)": lambda: prod.graph._run("CREATE (:Probe {id: 'write-test'})"),
    }
    try:
        from qdrant_client import models
        def qdrant_write():
            # A throwaway collection, so a wrongly accepted write touches no real data.
            c = prod.retriever.vs.client
            c.create_collection("docdrift_write_probe",
                                vectors_config=models.VectorParams(size=1, distance=models.Distance.DOT))
            c.delete_collection("docdrift_write_probe")
        probes["Qdrant (read-only key)"] = qdrant_write
    except ImportError:
        pass
    for name, fn in probes.items():
        ok, detail = refused(fn)
        failures += not ok
        print(f"{OK if ok else FAIL} write refused by {name}: {detail}")

    # --- 3. parity with the base stack, same embedding model: only the stores differ
    os.environ["DOCDRIFT_STACK"] = "base"
    base_settings = Settings.from_env()
    base_settings.embedder, base_settings.embedding_model = settings.embedder, settings.embedding_model
    base = build_pipeline(base_settings)
    for q in DEMO_QUESTIONS:
        a, _ = prod.ask(q)
        b, _ = base.ask(q)
        pages = lambda ans: sorted({(c.label, c.page) for s in ans.guidance for c in s.citations})
        same = (a.status, a.equipment_summary) == (b.status, b.equipment_summary)
        overlap = set(pages(a)) & set(pages(b))
        ok = same and (bool(overlap) or not pages(b))
        failures += not ok
        print(f"{OK if ok else FAIL} {q[:60]:60s} {a.status.value}"
              + ("" if ok else f"  (base: {b.status.value}; pages {pages(a)[:3]} vs {pages(b)[:3]})"))
    rejected = getattr(prod.llm, "rejected", [])
    if rejected:
        print(f"     {len(rejected)} LLM rewordings discarded because they changed a value, e.g. "
              f"{rejected[0][1]}")
    print("all checks passed" if not failures else f"{failures} check(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
