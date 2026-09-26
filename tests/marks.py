"""Tests that need the real ABB text indexed locally.

A fresh checkout has no ABB PDFs - they are fetched, not committed - so the tests
that assert on ABB-sourced guidance are skipped rather than failed until the fetch
and ingest scripts have been run. Everything that tests governance logic runs either
way, because that logic does not depend on the document text.
"""
import pytest

from docdrift.abb_registry import load_chunk_cache

ABB_TEXT_INDEXED = bool(load_chunk_cache())

needs_abb_text = pytest.mark.skipif(
    not ABB_TEXT_INDEXED,
    reason=("ABB document text is not indexed on this machine. Run "
            "`python scripts/unpack_library.py <bundles>`, `python scripts/import_library.py`, then `python scripts/ingest_abb.py`."))
