"""Build the static demo page in docs/ - no server, publishable on GitHub Pages.

    PYTHONPATH=. python scripts/build_static_demo.py

Runs the real pipeline (base stack) on the three demo questions in both governance
modes, records the answers, renders the cited pages (and their neighbours) with the
same highlighting as the live page, and writes a copy of the demo page that reads those
recordings instead of calling the API. Requires the local ABB library, as the live page
does. Re-run after any change that alters answers.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import sys

for k in [k for k in os.environ if k.startswith("DOCDRIFT_")]:
    del os.environ[k]                     # always the base stack, audit off

from fastapi.testclient import TestClient  # noqa: E402

from docdrift import __version__  # noqa: E402
from docdrift.abb_registry import load_manifest  # noqa: E402
from docdrift.api import WEB_DIR, app  # noqa: E402
from docdrift.config import DEMO_QUESTIONS  # noqa: E402
from docdrift.preview import render_page  # noqa: E402

import pymupdf  # noqa: E402

DPI = 96

OUT = pathlib.Path(__file__).resolve().parents[1] / "docs"
ABB_URL = ("https://search.abb.com/library/Download.aspx?DocumentID={id}"
           "&LanguageCode={lang}&DocumentPartId=&Action=Launch")


def pages_for(doc: dict, n_pages: int | None) -> dict[int, list[str]]:
    """Page -> highlighted quotes: cited and change pages with one page either side,
    plus the page the preview opens on for a document that is not cited."""
    cited = {int(p): q for p, q in (doc.get("cited_pages") or {}).items()}
    anchors = set(cited) | set(doc.get("change_pages") or [])
    if not anchors:                      # searched, not cited: only the page the preview opens on
        return {(doc.get("compare_pages") or [1])[0]: []}
    wanted = {p + d for p in anchors for d in (-1, 0, 1)}
    top = n_pages or max(wanted)
    return {p: cited.get(p, []) for p in sorted(wanted) if 1 <= p <= top}


def main() -> int:
    manifest = {d.doc_key: d for d in load_manifest().documents}
    if not manifest:
        print("No ABB library: run the setup in README first.", file=sys.stderr)
        return 2
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "pages").mkdir(parents=True)

    client = TestClient(app)
    config = client.get("/api/config").json()
    config.update(audit_enabled=False, static=True)
    answers, links, images, rendered, size = {}, {}, {}, {}, 0
    for i, q in enumerate(DEMO_QUESTIONS):
        for mode in ("strict", "flexible"):
            view = client.post("/api/ask", json={"question": q, "mode": mode}).json()
            key = f"q{i + 1}-{mode}"
            view["stored"] = False
            answers[f"{q}|{mode}"] = {"key": key, "view": view}
            images[key] = {}
            for doc in view["documents"]:
                rec = manifest.get(doc["doc_id"])
                if rec and rec.abb_document_id:
                    links[doc["doc_id"]] = ABB_URL.format(id=rec.abb_document_id, lang=rec.language or "en")
                for page, quotes in pages_for(doc, rec.n_pages if rec else None).items():
                    # Same page with the same highlights is stored once, whichever
                    # question or mode it appears under.
                    ident = json.dumps([doc["doc_id"], page, quotes, q if quotes else ""])
                    name = f"{doc['doc_id']}_p{page}_{hashlib.sha1(ident.encode()).hexdigest()[:8]}.jpg"
                    if name not in rendered:
                        try:
                            png = render_page(doc["doc_id"], page, None, tuple(quotes), dpi=DPI, question=q)
                        except Exception:   # PDF not in the library, or not renderable
                            rendered[name] = False
                            continue
                        jpg = pymupdf.Pixmap(png).tobytes("jpeg", jpg_quality=72)
                        (OUT / "pages" / name).write_bytes(jpg)
                        rendered[name] = True
                        size += len(jpg)
                    if rendered[name]:
                        images[key][f"{doc['doc_id']}_p{page}"] = name
            print(f"  {key}: {view['status']:26s} {len(view['documents'])} documents")

    data = {"config": config, "answers": answers, "pdf_links": links, "images": images}
    (OUT / "static-data.js").write_text(
        "// Recorded by scripts/build_static_demo.py - do not edit by hand.\n"
        "window.DOCDRIFT_STATIC = " + json.dumps(data, default=str) + ";\n")
    for name in ("app.js", "app.css"):
        shutil.copy(WEB_DIR / name, OUT / name)
    html = (WEB_DIR / "index.html").read_text().replace(
        '<script src="app.js"></script>', '<script src="static-data.js"></script>\n<script src="app.js"></script>')
    html = html.replace("<title>DocDrift", "<title>DocDrift static demo")
    (OUT / "index.html").write_text(html)
    (OUT / ".nojekyll").write_text("")     # serve files as they are on GitHub Pages
    total = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    n = sum(1 for v in rendered.values() if v)
    print(f"wrote {OUT}: {n} page images ({size / 1e6:.1f} MB), {total / 1e6:.1f} MB in total, "
          f"recorded from DocDrift {__version__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
