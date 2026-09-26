"""Build data/abb_document_manifest.json from the PDFs under data/library/.

    PYTHONPATH=. python scripts/import_library.py

The library is organised as one folder ("bundle") per equipment model, holding
whatever ABB documents were downloaded for it. The same publication often appears
in several bundles, and ABB sometimes serves one publication under several file
names; both are detected here so each publication is indexed once while every file
stays on disk.

Identity, in order of preference:
  - ABB document number: from the file name, else the most frequent ABB number on
    the first pages of the document
  - revision: from the file name (_Rev_Q, _J_, revJ, ",I"), else "Rev X" on the first
    pages
  - publication date: the first ISO date printed on the first pages (ABB prints the
    revision date there); the PDF creation date only as a fallback, because ABB's
    library regenerates files on download and stamps them with the download date
  - covered models: type codes that occur at least three times in the text
"""
from __future__ import annotations

import collections
import hashlib
import pathlib
import re
import sys
from datetime import date

from docdrift.abb_registry import LIBRARY_DIR, AbbDocumentRecord, AbbManifest, save_manifest

#: bundle folder -> (equipment model the user downloaded it for, category)
BUNDLES = {
    "ACH580-01": ("ACH580-01", "drives"),
    "ACS480": ("ACS480", "drives"),
    "ACS580-04": ("ACS580-04", "drives"),
    "PSTX30-600-70": ("PSTX30-600-70", "softstarters"),
    "PSTX142-600-70": ("PSTX142-600-70", "softstarters"),
    "PSR25-600-70": ("PSR25-600-70", "softstarters"),
    "AF38-30-00-13": ("AF38-30-00-13", "motor_protection"),
    "MS132-10T": ("MS132-10T", "motor_protection"),
}

def canonical_bundle(folder: str) -> str | None:
    """Map a bundle folder to its equipment model. Download names vary ("ACS480 DRIVES",
    "ACH580-01 - WALL-MOUNTED DRIVE FOR HVAC"), so the folder only has to start with
    the model's type code."""
    name = folder.strip().upper()
    for key in sorted(BUNDLES, key=len, reverse=True):
        if name == key.upper() or name.startswith(key.upper() + " ") or name.startswith(key.upper() + "-") \
                or name.startswith(key.upper() + "_"):
            return key
    return None


ABB_ID = re.compile(r"(?<![A-Z0-9])(1S[A-Z]{2}\d{6}[A-Z]\d{4}|2C[A-Z]{2}\d{6}[A-Z]\d{4}"
                    r"|3A(?:FE|UA|XD)\d{8,11}|4FPS\d{11}|9AKK\d{6}A\d{4})(?![0-9])")
REV_FILE = [re.compile(p, re.I) for p in (
    r"_rev_?([A-Z])(?:[_ .]|$)", r"\brev\.? ?([A-Z])\b", r",([A-Z])\.pdf$",
    r"_([A-Z])_A[345]", r"_en_(?:\d_)?([A-Z])_", r"_([A-Z])_(?:Installation|application)",
    r"_([A-Z])\.pdf$", r"Online_([A-Z])")]
REV_TEXT = re.compile(r"\bRev(?:ision)?\.?:?\s*([A-Z])\b")
ISO_DATE = re.compile(r"\b(20\d\d|199\d)-(\d\d)-(\d\d)\b")
GENERIC_LINES = {"ABB DRIVES", "ABB INDUSTRY SPECIFIC DRIVES", "ABB DRIVE TECHNOLOGY", "CATALOG",
                 "MAIN CATALOG", "APPLICATION GUIDE", "DATA SHEET", "TECHNICAL NOTE",
                 "SAFETY INSTRUCTIONS", "EN", "ABB", "MANUAL SUPPLEMENT"}
MODEL_RE = re.compile(r"\b(ACS\d{3}(?:-\d{2})?|ACH\d{3}(?:-\d{2})?|ACQ\d{3}(?:-\d{2})?|PSTX\d+|PSR\d+"
                      r"|PSE\d+|MS1\d{2}(?:-[\d.]+K?T)?|AF\d{2,4}|UMC\d+)\b")
DE_WORDS = re.compile(r"\b(und|der|die|mit|für|nicht|werden)\b")
EN_WORDS = re.compile(r"\b(the|and|with|for|not|must)\b")
JUNK_TITLE = re.compile(r"(\.(cdr|indd|ai|plt|xls|doc)\b|^Microsoft Word|^[A-Z]:\\\\|^\\s*$|recto|print|web\)|"
                        r"^1x\b|^[A-D] [A-D] [A-D]|^\d+ [A-F] [B-F]|^EN_|_Recto)", re.I)

DOC_TYPES = [
    ("firmware_manual", r"firmware manual|standard control program"),
    ("hardware_manual", r"hardware manual"),
    ("service_manual", r"service manual"),
    ("installation_and_commissioning_manual", r"installation and commissioning manual"),
    ("user_manual", r"user.?s? manual|user manual"),
    ("quick_guide", r"quick installation|quick guide|quick installation guide|\bQIG\b|\bQISG\b"),
    ("spare_part_instruction", r"spare part instruction|replace the|service instruction|installation instruction replace"),
    ("installation_instruction", r"installation instruction|safety instructions|montageanleitung|mounting"),
    ("end_of_life_notice", r"end.of.life"),
    ("catalog", r"catalog|catalogue"),
    ("data_sheet", r"data sheet|datasheet"),
    ("selection_table", r"selection table"),
    ("application_guide", r"application guide|application manual|applikationshandbuch|configuration guide"),
    ("application_note", r"application note|technical note|technical description"),
    ("technical_guide", r"technical guide"),
    ("fieldbus_manual", r"fieldbus|profibus|modbus|canopen|devicenet|bacnet|anybus"),
    ("release_note", r"release note|product presentation|faq"),
    ("certificate_or_statement", r"certificate|manufacturer.?s statement|conformance"),
    ("drawing", r"drawing|dimension|circuit diagram|application diagram|proprietary and secret|autocad"),
]


def classify(title: str, text: str, pages: int) -> str:
    """Title first, because body text mentions everything ("mounting" appears in
    every catalogue); then the one-page CAD drawings; then the opening text."""
    for name, pat in DOC_TYPES:
        if re.search(pat, title, re.I):
            return name
    if pages <= 2 and (len(text) < 1500 or re.search(r"approved|drawing|proprietary", text, re.I)):
        return "drawing"
    for name, pat in DOC_TYPES:
        if re.search(pat, text[:1500], re.I):
            return name
    return "technical_document"


def first_lines(doc, n_pages: int = 2) -> list[str]:
    lines = []
    for i in range(min(n_pages, doc.page_count)):
        lines += [" ".join(l.split()) for l in doc[i].get_text().splitlines() if l.strip()]
    return lines


def derive_title(meta_title: str, lines: list[str], file_name: str) -> str:
    if meta_title and not JUNK_TITLE.search(meta_title) and len(meta_title) > 8 \
            and not ABB_ID.fullmatch(meta_title.strip()) \
            and meta_title.strip().upper() not in GENERIC_LINES \
            and not re.search(r"\bRev\.? ?[A-Z]\s*$|\.pdf$", meta_title.strip(), re.I):
        return meta_title.strip()[:140]
    for i, line in enumerate(lines[:30]):
        clean = line.lstrip("—– ").strip()
        if clean.upper() in GENERIC_LINES or clean.upper() in {"EN /", "—"} or len(clean) < 8:
            continue
        if re.match(r"^(\d+/\d+|Page \d)", clean) or re.search(r"©|copyright|www\.", clean, re.I):
            continue
        if re.search(r"specifications subject to change|original drawing|scale factor|\.pdf$|"
                     r"^(\w+ )?rev\.? ?[A-Z]\b|\bRev [A-Z]( \(EN\))?( \d\d/\d\d/\d{4})?$|^DOCUMENT ID",
                     clean, re.I):
            continue
        if re.match(r"^(EN|MUL|DE) ?/", clean):
            clean = clean.split("/", 1)[1].strip()
        if JUNK_TITLE.search(clean) or ABB_ID.fullmatch(clean) or re.fullmatch(r"[\d .|/]+", clean):
            continue
        return clean[:140]
    stem = pathlib.Path(file_name).stem
    return re.sub(r"[_]+", " ", stem)[:140]


#: Identity corrections for publications whose number, revision or title the
#: heuristics cannot read reliably. Each value was checked against the document.
CURATED = {
    "1SBC100214C0202": {"revision": "2024", "doc_type": "catalog",
                        "title": "Motor protection and control - main catalog 2024"},
    "2CDC131058D0201": {"revision": "D", "doc_type": "data_sheet",
                        "title": "Data sheet - circuit breakers for transformer protection MS132-T / MS132-KT"},
    "2CDC131111D0201": {"title": "Selection table - circuit breakers for transformer protection MS132-T / MS132-KT"},
    "3AXD50000016097": {"title": "ACS580 drives standard control program firmware manual"},
    "3AXD50000047399": {"title": "ACS480 drives standard control program firmware manual"},
    "3AXD50000015497": {"title": "ACS580-04 drive modules hardware manual"},
    "3AXD50000047392": {"title": "ACS480 hardware manual"},
    "3AXD50000047400": {"doc_type": "quick_guide",
                        "title": "ACS480 drives quick installation and start-up guide"},
    "3AXD50000349821": {"doc_type": "hardware_manual",
                        "title": "ACS580-01, ACH580-01 and ACQ580-01 +C135 supplement"},
    "1SFC132081M0201": {"title": "Softstarters type PSTX30...PSTX1250 installation and commissioning manual"},
    "1SFC132082M9901": {"title": "Softstarters type PSTX30...PSTX1250 user manual short form (multilingual)",
                        "language": "mul"},
    "1SFC132012C0201": {"title": "Softstarters PSR, PSRC, PSE and PSTX catalog"},
    "1SFC132031M0001": {"doc_type": "installation_instruction",
                        "title": "PSR softstarters installation and operating instruction"},
    "4FPS10000309652": {"doc_type": "maintenance_schedule",
                        "title": "Maintenance schedule - ACS580, ACH580 and ACQ580 drives"},
}


def junk_title(title: str, doc_id: str | None) -> bool:
    t = title.strip()
    if "\\" in t or re.search(r"\b(model \(1\)|abb france|pozidriv|lb\.in|n·m)\b", t, re.I):
        return True
    if doc_id and t.replace(doc_id, "").strip(" -_|/0123456789").lower() in {"", "online", "rev", "en"}:
        return True
    if re.match(r"^[\d.,]", t):
        return True
    words = re.findall(r"[A-Za-z]{4,}", t)
    return len(words) < 2


def main() -> int:
    try:
        import pymupdf
    except ImportError:
        print("PyMuPDF is required: pip install pymupdf", file=sys.stderr)
        return 2

    by_sha: dict[str, AbbDocumentRecord] = {}
    by_identity: dict[tuple, AbbDocumentRecord] = {}
    records: list[AbbDocumentRecord] = []

    for path in sorted(LIBRARY_DIR.rglob("*.pdf")):
        parts = path.relative_to(LIBRARY_DIR).parts
        if any(p == "__MACOSX" or p.startswith("._") for p in parts):
            continue                         # macOS archive metadata, not a document
        bundle = canonical_bundle(parts[0])
        if bundle is None:
            print(f"  skip  {parts[0]}/ - not one of the eight equipment bundles")
            continue
        if bundle not in BUNDLES:
            continue
        rel = str(path.relative_to(LIBRARY_DIR))
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()

        if sha in by_sha:                       # byte-identical file in another bundle
            rec = by_sha[sha]
            if bundle not in rec.bundles:
                rec.bundles.append(bundle)
            rec.alternate_copies.append(rel)
            continue

        doc = pymupdf.open(path)
        lines = first_lines(doc, 4)
        head = " ".join(lines)
        sample = " ".join(doc[i].get_text() for i in range(0, doc.page_count,
                                                             max(1, doc.page_count // 40)))
        full_models = collections.Counter(MODEL_RE.findall(
            " ".join(p.get_text() for p in doc) if doc.page_count <= 700 else sample))

        name_ids = ABB_ID.findall(path.name)
        text_ids = collections.Counter(ABB_ID.findall(head)).most_common(1)
        if name_ids:
            doc_id, source = name_ids[0], "file name"
        elif text_ids:
            doc_id, source = text_ids[0][0], "document text"
        else:
            doc_id, source = None, "none found"

        revision = next((m.group(1).upper() for r in REV_FILE if (m := r.search(path.name))), None)
        if revision is None and (m := REV_TEXT.search(head)):
            revision, source = m.group(1), source + "; revision from document text"

        published, date_source = None, "none"
        for mt in ISO_DATE.finditer(head):
            try:
                cand = date(int(mt.group(1)), int(mt.group(2)), int(mt.group(3)))
            except ValueError:
                continue
            if date(1995, 1, 1) <= cand <= date.today():
                published, date_source = cand, "printed revision date"
                break
        if published is None:
            created = (doc.metadata or {}).get("creationDate") or ""
            m = re.search(r"D:(\d{4})(\d{2})(\d{2})", created)
            if m:
                published = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                date_source = "PDF creation date"

        lang = "de" if len(DE_WORDS.findall(sample)) > len(EN_WORDS.findall(sample)) else "en"
        if re.search(r"(^|_)MUL[_ ]", path.name):
            lang = "mul"
        title = derive_title((doc.metadata or {}).get("title", ""), lines, path.name)
        doc_type = classify(title, head, doc.page_count)
        if junk_title(title, doc_id):
            label = doc_type.replace("_", " ").capitalize()
            ref = doc_id or re.sub(r"[_]+", " ", path.stem)
            title = f"{label} {ref}"
        models = [mdl for mdl, n in full_models.most_common(25) if n >= 3]
        n_pages = doc.page_count
        doc.close()

        identity = (doc_id, revision, lang) if doc_id else None
        if identity and identity in by_identity:   # same publication, different file
            rec = by_identity[identity]
            if bundle not in rec.bundles:
                rec.bundles.append(bundle)
            rec.alternate_copies.append(rel)
            by_sha[sha] = rec
            continue

        key = doc_id or re.sub(r"[^A-Za-z0-9]+", "-", path.stem).strip("-")[:48]
        if any(r.doc_key == key for r in records):
            key = f"{key}-{lang.upper()}" if not any(r.doc_key == f"{key}-{lang.upper()}"
                                                    for r in records) else f"{key}-{sha[:6]}"
        rec = AbbDocumentRecord(
            doc_key=key, abb_document_id=doc_id, title=title, category=BUNDLES[bundle][1],
            doc_type=doc_type, revision=revision, language=lang, file_name=path.name,
            library_path=rel, bundles=[bundle], n_pages=n_pages, bytes=len(raw), sha256=sha,
            published=published, covers_models=models,
            identity_source=f"{source}; date: {date_source}")
        records.append(rec)
        by_sha[sha] = rec
        if identity:
            by_identity[identity] = rec

    for rec in records:
        for field, value in CURATED.get(rec.doc_key, {}).items():
            setattr(rec, field, value)

    manifest = AbbManifest(generated=date.today(),
                           bundles={b: m for b, (m, _) in BUNDLES.items()}, documents=records)
    save_manifest(manifest)
    files = sum(1 + len(r.alternate_copies) for r in records)
    print(f"{len(records)} publications from {files} PDF files "
          f"({sum(r.n_pages or 0 for r in records)} pages to index)")
    for cat in ("drives", "softstarters", "motor_protection"):
        print(f"  {cat:17s} {sum(1 for r in records if r.category == cat)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
