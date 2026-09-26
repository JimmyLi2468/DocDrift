"""The ABB document library: which real ABB publications back version n.

The PDFs are ABB publications the user downloaded from ABB's public library and
placed under `data/library/<bundle>/`, one bundle per equipment model. DocDrift never
invents ABB content. `scripts/import_library.py` reads every PDF in the library and
records its identity - ABB document number, revision, language, page count,
publication date, SHA-256, the models its own text names - in
`data/abb_document_manifest.json`. `scripts/ingest_abb.py` then extracts the text of
every page into `data/cache/abb_chunks.json`.

`data/library/` and `data/cache/` are gitignored. They are a local working copy of
public ABB documents, not repository content, and must not be committed or
redistributed. Until they are populated, version-n chunks carry
`SYNTHETIC_PLACEHOLDER` provenance and every citation says so.
"""
from __future__ import annotations

import json
import pathlib
from datetime import date

from pydantic import BaseModel, Field

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data" / "abb_document_manifest.json"
LIBRARY_DIR = ROOT / "data" / "library"
CACHE_PATH = ROOT / "data" / "cache" / "abb_chunks.json"

#: ABB's public download endpoint. Recorded for traceability only; DocDrift does not
#: download anything - the library is supplied by the user.
DOWNLOAD_URL = ("https://search.abb.com/library/Download.aspx"
                "?DocumentID={doc_id}&LanguageCode={lang}&DocumentPartId=&Action=Launch")


class AbbDocumentRecord(BaseModel):
    """One ABB publication. Identity fields are read from the file name and from the
    document itself; `category` and `doc_type` are DocDrift's classification."""
    doc_key: str                             # unique key used across DocDrift
    abb_document_id: str | None = None       # ABB document number, when one was found
    title: str
    category: str
    doc_type: str
    revision: str | None = None
    language: str = "en"
    file_name: str
    library_path: str                        # relative to data/library
    bundles: list[str] = Field(default_factory=list)
    alternate_copies: list[str] = Field(default_factory=list)
    n_pages: int | None = None
    bytes: int | None = None
    sha256: str | None = None
    published: date | None = None
    covers_models: list[str] = Field(default_factory=list)
    identity_source: str = "file name"       # where abb_document_id / revision came from

    @property
    def local_path(self) -> pathlib.Path:
        return LIBRARY_DIR / self.library_path

    @property
    def available(self) -> bool:
        return self.local_path.exists()

    @property
    def source_url(self) -> str | None:
        if not self.abb_document_id:
            return None
        return DOWNLOAD_URL.format(doc_id=self.abb_document_id, lang=self.language)


class AbbManifest(BaseModel):
    generated: date
    note: str = (
        "Identities of ABB publications supplied by the user under data/library/. The "
        "PDFs are a local working copy and are not redistributed with DocDrift."
    )
    #: bundle folder -> the equipment model it was downloaded for
    bundles: dict[str, str] = Field(default_factory=dict)
    documents: list[AbbDocumentRecord] = Field(default_factory=list)

    def get(self, doc_key: str) -> AbbDocumentRecord | None:
        return next((d for d in self.documents if d.doc_key == doc_key), None)

    def in_bundle(self, bundle: str) -> list[AbbDocumentRecord]:
        return [d for d in self.documents if bundle in d.bundles]


def load_manifest(path: pathlib.Path | str = MANIFEST_PATH) -> AbbManifest:
    p = pathlib.Path(path)
    if not p.exists():
        return AbbManifest(generated=date.today())
    return AbbManifest.model_validate_json(p.read_text())


def save_manifest(manifest: AbbManifest, path: pathlib.Path | str = MANIFEST_PATH) -> None:
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(manifest.model_dump_json(indent=1))


def load_chunk_cache(path: pathlib.Path | str = CACHE_PATH) -> dict[str, list[dict]]:
    p = pathlib.Path(path)
    return json.loads(p.read_text()) if p.exists() else {}
