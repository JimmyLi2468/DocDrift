"""Extract the text of every page of every ABB publication in the manifest.

    PYTHONPATH=. python scripts/ingest_abb.py              # every page (default)
    PYTHONPATH=. python scripts/ingest_abb.py --max-pages 40 --workers 4

One chunk per page, with the running header and footer removed and long pages split
at line boundaries with a small overlap, so a fault-code table or a numbered
procedure is never cut mid-line. Pages are cited by their physical page number in the
PDF, which is what an operator types into a viewer.
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor

from docdrift.abb_registry import CACHE_PATH, load_manifest

BOILERPLATE = ("table of contents", "contents", "list of figures", "trademarks", "disclaimer",
               "copyright", "notes", "intentionally left blank")


def running_headers(pages: list[str], threshold: float = 0.25) -> set[str]:
    """Lines repeated on a quarter of the pages are header/footer, not content."""
    if len(pages) < 4:
        return set()
    counts: dict[str, int] = {}
    for text in pages:
        for line in {" ".join(l.split()) for l in text.splitlines() if l.strip()}:
            if len(line) <= 90:
                counts[line] = counts.get(line, 0) + 1
    floor = max(3, int(len(pages) * threshold))
    return {line for line, n in counts.items() if n >= floor}


def split_page(lines: list[str], max_chars: int, overlap_lines: int = 2) -> list[str]:
    parts, cur, size = [], [], 0
    for line in lines:
        if cur and size + len(line) + 1 > max_chars:
            parts.append(" ".join(cur))
            cur = cur[-overlap_lines:]
            size = sum(len(l) + 1 for l in cur)
        cur.append(line)
        size += len(line) + 1
    if cur:
        parts.append(" ".join(cur))
    return parts


def ingest_one(args) -> tuple[str, list[dict], int]:
    doc_key, path, max_pages, min_chars, max_chars = args
    import pymupdf
    doc = pymupdf.open(path)
    raw = [p.get_text("text") for p in doc]
    doc.close()
    headers = running_headers(raw)
    chunks, n_pages = [], len(raw)
    limit = n_pages if max_pages <= 0 else min(n_pages, max_pages)
    for i in range(limit):
        lines = [" ".join(l.split()) for l in raw[i].splitlines() if l.strip()]
        lines = [l for l in lines if l not in headers]
        body = " ".join(lines)
        if len(body) < min_chars:
            continue
        title = next((l for l in lines if 6 <= len(l) <= 80 and not l.isdigit()), lines[0])[:80]
        if title.lower().strip(" .") in BOILERPLATE and len(body) < 400:
            continue
        pieces = split_page(lines, max_chars)
        for j, text in enumerate(pieces):
            suffix = "" if len(pieces) == 1 else chr(ord("a") + j)
            chunks.append({"chunk_id": f"{doc_key}-p{i + 1:04d}{suffix}", "section": str(i + 1),
                           "section_title": title, "page": i + 1, "text": text})
    return doc_key, chunks, n_pages


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=0, help="0 = every page (default)")
    ap.add_argument("--min-chars", type=int, default=60)
    ap.add_argument("--max-chars", type=int, default=2200)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    manifest = load_manifest()
    jobs = [(r.doc_key, str(r.local_path), args.max_pages, args.min_chars, args.max_chars)
            for r in manifest.documents if r.available]
    missing = [r.doc_key for r in manifest.documents if not r.available]
    if missing:
        print(f"  {len(missing)} manifest entries have no file in data/library: {missing[:5]}")

    cache: dict[str, list[dict]] = {}
    pages_seen = 0
    try:
        pool = ProcessPoolExecutor(max_workers=args.workers)
        results = pool.map(ingest_one, jobs, chunksize=2)
    except (PermissionError, OSError, NotImplementedError):
        # Some sandboxes forbid the semaphores a process pool needs; run serially.
        pool, results = None, map(ingest_one, jobs)
    for key, chunks, n_pages in results:
        cache[key] = chunks
        pages_seen += n_pages
    if pool is not None:
        pool.shutdown()

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache))
    total = sum(len(v) for v in cache.values())
    print(f"read {pages_seen} pages from {len(cache)} publications; wrote {total} chunks "
          f"to {CACHE_PATH.relative_to(CACHE_PATH.parents[2])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
