"""Load the corpus into the production services (PostgreSQL, Qdrant, Neo4j).

    docker compose up -d
    PYTHONPATH=. python scripts/load_production.py

Run it once after `docker compose up -d`, and again whenever the library, the synthetic
history or the enterprise records change. It uses the loader credentials; the API
itself connects read-only. Takes a few minutes: every chunk is embedded once.
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("DOCDRIFT_STACK", "production")
os.environ.setdefault("DOCDRIFT_EMBEDDING_CACHE", "data/cache")   # reused by check_production.py

from docdrift.app import BackendNotAvailable, load_services  # noqa: E402
from docdrift.config import Settings  # noqa: E402
from docdrift.corpus import build_corpus  # noqa: E402


def main() -> int:
    settings = Settings.from_env()
    t0 = time.time()
    corpus = build_corpus()
    n = len(corpus.chunks)
    abb = sum(1 for c in corpus.chunks if c.provenance.value == "abb_public_pdf")
    if abb == 0:
        print("No ABB text found. Run scripts/import_library.py and scripts/ingest_abb.py first.",
              file=sys.stderr)
        return 2
    print(f"corpus      {n} chunks, {len(corpus.communications)} communications, "
          f"{len(corpus.versions)} document versions")
    try:
        report = load_services(settings, corpus)
    except BackendNotAvailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"loaded build {report['fingerprint']} in {time.time() - t0:.0f} s")
    print("next: PYTHONPATH=. python scripts/check_production.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
