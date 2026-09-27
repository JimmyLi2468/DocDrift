# DocDrift

Local, read-only maintenance intelligence with **documentation-drift detection** and an
explicit **change-governance test**.

A conventional RAG assistant retrieves passages from a manual and answers. DocDrift adds
the controls that make an answer usable where documentation is controlled:

1. **Equipment verification** - which asset is the operator asking about, with a confidence score and an ambiguity check.
2. **Applicability and currency** - is the retrieved document the current, applicable revision for that asset.
3. **Change governance** - is there an *approved* change the document does not yet reflect, and can that approval prove itself.

The operator gets citation-backed guidance, the documentation status
(`Verified Current` / `Potential Approved Update`), the approval evidence when relevant,
an escalation to the responsible document owner - and, for every record that was refused,
the reason it was refused. DocDrift never modifies documentation, never approves anything,
and never replaces a formal engineering procedure.

---

## The governance test

A change may alter operating guidance only if **every** condition holds. One failure
demotes it to evidence: still shown, with the reason, but unable to move the status or the
troubleshooting steps.

| condition | question it answers |
|---|---|
| `C1_RELEVANT` | does this bear on the question and the equipment asked about |
| `C2_WITHIN_FRESHNESS_WINDOW` | is it dated on or after the n-1 effective date |
| `C3_FORMAL_RECORD` | is there a formal change record - **policy-configurable, see below** |
| `C4_DECISION_APPROVED` | is the decision state `APPROVED`, not merely favourable |
| `C5_APPROVER_IDENTIFIED` | does the named approver resolve in personnel records |
| `C6_AUTHORITY_IN_SCOPE` | does that person's role carry authority for *this* scope |
| `C7_AUTHORITY_VALID_ON_DATE` | did that authority cover the decision date |
| `C8_NOT_ALREADY_INCORPORATED` | is the change absent from the current revision |
| `C9_NOT_INVALIDATED` | has no later authorised decision retired it |

### Decision state and authority state are independent

`DecisionState` is what the record says: `DISCUSSION`, `PROPOSED`, `PENDING_CONFIRMATION`,
`APPROVED`, `REJECTED`, `CANCELLED`, plus the reversal-only `WITHDRAWN` and `SUPERSEDED`.
It is extracted from the record.

`AuthorityState` is what DocDrift concludes: `NOT_APPLICABLE`, `NOT_CHECKED`, `VERIFIED`,
`UNVERIFIED`, `OUT_OF_SCOPE`, `EXPIRED`. It is never read from the record - it is derived
from personnel records and a time-bounded authority matrix. Keeping the two separate is
what lets an Engineering Manager be `VERIFIED` and the decision still be
`PENDING_CONFIRMATION`.

### Governance modes

`C3` is the only policy-configurable condition.

- **Strict** (default): only a formal change record can establish approval.
- **Flexible**: a direct approval from an authorised person in Teams or email also counts.

Flexible relaxes the *record* requirement and nothing else. `C5`, `C6` and `C7` apply
identically in both modes, so a Procurement Manager writing "Approved" on a wiring change
is refused in flexible mode exactly as in strict.

Supported channels: `teams_chat`, `email`, `formal_change_notice`, `engineering_bulletin`,
`meeting_minutes`. An engineering bulletin is a supported channel but not an approval
channel in either mode.

### Later invalidation, and authority on reversals

After an approval is found, DocDrift searches the same `change_ref` thread for later
`CANCELLED`, `REJECTED`, `WITHDRAWN` or `SUPERSEDED` decisions. A reversal is re-checked
against the authority matrix before it counts: a maintenance technician declaring an
approved engineering change cancelled does not cancel it, and the audit record says so.

### Why the freshness date is the *n-1* effective date

Searching from the current revision's effective date misses changes approved between n-1
and n that were never carried into n. `versioning.py` walks the supersession chain and
sets `freshness_search_from = previous.effective_date`.

### Two tiers of drift

A change affecting the same asset but a different subject does not flip the headline
status - a question about enclosure ratings should not be answered with a wiring-torque
banner. It is still disclosed, under *other approved changes open against this asset*.
Relevance requires two independent shared content terms, not a ratio: "Safe Torque Off"
and "terminal tightening torque" share the word *torque* and have nothing to do with each
other.

---

## Documents: what is real and what is not

**Version n is real.** The current revision of every document is an ABB publication from
the local document library in `data/library/` - one folder per equipment model, as
downloaded from ABB's public library. `scripts/import_library.py` records each
publication's identity in `data/abb_document_manifest.json`: ABB document number and
revision (from the file name, else from the document's own first pages), printed revision
date, page count, SHA-256, language, and the type codes its text names. Byte-identical
files and the same publication served under two file names are indexed once; every file
stays on disk.

**Version n-1 is synthetic, says so, and is written as a revision, not a whole file.**
Ten documents have a reconstructed previous revision. A real revision changes a few
passages and repeats the rest, so each reconstruction is stored as a *diff against the
current ABB page*: `corpus/historical.py` holds only the edited passages (current wording,
previous wording), and the overlapping text is derived at build time from the local ABB
text. Each reconstruction covers one or two source pages, cut to a window around the
edit, and renders as a one-page PDF with a synthetic revision-history block.

| document | current (ABB) | synthetic n-1 | what differs | change traffic |
|---|---|---|---|---|
| `3AXD50000016097` ACS580 firmware manual | J 2025-10-01 | H 2024-07-28 | p.556 5091 row lacks "Programmable fault: 31.22 ..." | `ECN-2025-129` incorporated; `ECN-2026-011` open |
| `3AXD50000047399` ACS480 firmware manual | G 2025-11-05 | F 2024-09-02 | p.539 5091 row lacks the 95.04 check | `ECN-2025-071` incorporated |
| `3AXD50000047392` ACS480 hardware manual | F 2024-05-20 | E 2023-03-15 | p.64 no voltage-limiting sentence | `EB-2026-020` bulletin |
| `3AXD50000015497` ACS580-04 hardware manual | F 2022-09-26 | E 2021-06-14 | p.124 shields grounded, not "360°" | `ECN-2022-015` incorporated |
| `4FPS10000309652` ACS580 maintenance schedule | 1 2026-04-27 | 0 2024-03-01 | p.1 "regular" instead of "annual" inspections | `ECN-2025-102` incorporated |
| `1SFC132081M0201` PSTX I&C manual | Q 2022-04-06 | P 2021-01-31 | p.150 no connection-bar step; p.103 no class 10A | maintenance and EOL threads |
| `1SFC132012C0201` Softstarter catalog | J 2026-02-23 | H 2024-09-16 | p.63 no dual overload | none - topically near the EOL thread, but no record targets it |
| `1SFC132031M0001` PSR instruction | I 2013-12-11 | H 2012-05-02 | p.1 lower short-circuit rating | none - a revision with no traffic at all |
| `1SBC100214C0202` Motor protection main catalog | 2024 | 2023 2022-12-02 | p.180 main torque 1.2 Nm; p.175 coil limit at 55 °C | AF38 torque and coil threads |
| `2CDC131058D0201` MS132-T data sheet | D 2021-03-01 | C 2019-10-01 | p.1 short-circuit setting 17x | transformer-protection thread |

All other publications have no history, and their freshness window opens at the current
revision. Each reconstruction carries `ContentProvenance.SYNTHETIC_HISTORICAL`, a
visible disclaimer and a `(synthetic)` marker in every citation label. When rendered by
`scripts/make_synthetic_history.py` it also carries a diagonal **SYNTHETIC - NOT AN ABB
PUBLICATION** watermark and footer; the generated PDFs are gitignored like the library
they derive from. Gate `G8_PROVENANCE_LABELLED` fails the answer if synthetic text is
ever presented as an ABB publication. On the demo page, the *Compare with previous
revision* tab shows the word-level diff, with the synthetic side labelled as such.

**The enterprise layer is entirely invented.** People, departments, roles, Teams messages,
emails, change notices and approval records describe a fictional plant that operates real
ABB equipment. Each change thread is anchored to a real page of a current ABB document,
and the tests assert both that the page still says what the thread assumes and that the
change's normative terms are absent from it - so the incorporation test has a genuine
negative to find.

| thread | anchored to |
|---|---|
| `CHG-2026-011` STO wiring for fault 5091 | ACS580 firmware manual rev J p.556 - the 5091 fault-table row |
| `CHG-2025-129` document 5091's programmable response | same row - already says "31.22 STO indication run/stop" |
| `CHG-2026-014` PSTX inspection interval | PSTX I&C manual rev Q p.150 "9.1 Regular maintenance" (gives no interval) |
| `CHG-2026-018` EOL trip class 20 on S1 | PSTX I&C manual p.103 "13.02 EOL class" |
| `CHG-2026-033` AF38 main terminal re-torque | main catalog p.180 - AF09...AF38 tightening torque 1.5 / 2.5 Nm |
| `CHG-2026-031` tighter AF38 coil band | main catalog p.175 - coil operating limits 0.85...1.1 x Uc |
| `CHG-2026-027` standard MS132 on transformer primaries | MS132-T data sheet p.1 |
| `CHG-2026-020` ACS480 insulation measurement (bulletin) | ACS480 hardware manual rev F p.64 |

**ABB PDFs are not redistributed.** `data/library/` and `data/cache/` are gitignored. The
repository carries the manifest (identities and checksums only) and the scripts:

```bash
PYTHONPATH=. python scripts/unpack_library.py ~/Downloads/*.zip   # one zip per equipment model
PYTHONPATH=. python scripts/import_library.py                     # manifest: 141 publications
PYTHONPATH=. python scripts/ingest_abb.py                         # every page; ~30 s for 5,631 pages
PYTHONPATH=. python scripts/make_synthetic_history.py             # the 10 watermarked n-1 PDFs
```

`ingest_abb.py` now reads every page by default (`--max-pages 0`); long pages are split at
line boundaries with a two-line overlap so a fault-table row or numbered step is never cut.
German and multilingual publications stay in the library and the manifest but are not
linked to assets, because guidance is given in English. Ten one-page CAD drawings have no
text layer; they are listed as ABB publications and become quotable once the OCR adapter
exists.

---

## Setup (once)

Written for macOS on Apple silicon. Part A is enough for the demo page on the base
stack; part B adds the production stack. Both are run once per machine.

### Before you start

| needed for | what | check |
|---|---|---|
| A | Python 3.11 or newer (macOS ships 3.9) | `python3.12 --version`; if missing: `brew install python@3.12` |
| A | the eight ABB bundles and `docdrift-repo.tar.gz` in one folder | `ls` shows the bundle folders and the archive |
| B | Docker Desktop, started at least once | `docker --version` (see *docker: command not found* below) |
| B | Homebrew, for Ollama | `brew --version` |
| B | about 12 GB free disk (model 4.9 GB, images and volumes about 3 GB, Python packages about 2 GB) | `df -h ~` |

### A. Base stack

From the folder that holds the bundles and the archive:

```bash
tar -xzf docdrift-repo.tar.gz && cd docdrift
python3.12 -m venv .venv                  # not plain python3: on macOS that is 3.9
source .venv/bin/activate
python --version                          # must print 3.11 or newer
pip install --upgrade pip
pip install pydantic numpy pymupdf reportlab fastapi uvicorn python-multipart pytest httpx
export PYTHONPATH=.

python scripts/unpack_library.py ../ACH580-01* ../ACS480* ../ACS580-04* ../AF38* ../MS132* ../PSR25* ../PSTX142* ../PSTX30*
python scripts/import_library.py          # manifest: 141 publications
python scripts/ingest_abb.py              # every page, about 30 s: 6,741 chunks
python scripts/make_synthetic_history.py  # 10 watermarked n-1 PDFs
python -m pytest -q                       # 85 passed, 1 skipped (the Qdrant test, until part B)

uvicorn docdrift.api:app --port 8000      # demo page at http://localhost:8000
```

Bundles can be zip files or already-unzipped folders, under any download name that starts
with the type code. The originals are copied, not moved.

### B. Production stack

Start Docker Desktop first (`open -a Docker`, then wait until its menu-bar icon says it
is running). Then, in the activated environment inside `docdrift`:

```bash
brew install ollama
brew services start ollama                # runs Ollama in the background, also after a reboot
ollama pull llama3.1:8b                   # about 4.9 GB

pip install "psycopg[binary]" qdrant-client neo4j sentence-transformers
python -m pytest -q                       # now 86 passed

docker compose up -d                      # PostgreSQL, Qdrant, Neo4j, reachable on 127.0.0.1 only
docker compose ps                         # all three "running"; postgres also "healthy"
python scripts/load_production.py         # a few minutes: downloads the embedding model once, embeds 6,753 chunks
python scripts/check_production.py        # expect: all checks passed

DOCDRIFT_STACK=production uvicorn docdrift.api:app --port 8000 --reload
```

The page header shows `Stack: production` and `LLM: ollama llama3.1:8b`.

**`docker: command not found`.** Docker Desktop is either not installed or has not put
its command-line tool on the path yet.

```bash
ls -d /Applications/Docker.app            # "No such file": install it - brew install --cask docker
open -a Docker                            # first start: accept the prompts, wait for "running"
ls ~/.docker/bin/docker /usr/local/bin/docker 2>/dev/null
```

If the tool is only in `~/.docker/bin` (Docker's "per-user" install), add it to the path.
The first line makes it permanent for new Terminal windows; the second applies it to the
window you are in, because `~/.zshrc` is only read when a window opens:

```bash
echo 'export PATH="$HOME/.docker/bin:$PATH"' >> ~/.zshrc
export PATH="$HOME/.docker/bin:$PATH"
docker --version
```

Alternatively, in Docker Desktop: *Settings > Advanced > System (requires password)*
installs it to `/usr/local/bin`.

### Every new Terminal window

```bash
cd ~/path/to/DocDrift/docdrift
source .venv/bin/activate
export PYTHONPATH=.
```

### Everyday commands

```bash
uvicorn docdrift.api:app --port 8000 --reload                           # base stack
docker compose up -d && DOCDRIFT_STACK=production uvicorn docdrift.api:app --port 8000 --reload
python -m docdrift.cli                    # the core use case in the console
python scripts/evaluate.py                # 20 cases x 2 modes, writes a scorecard
python -m pytest -q                       # offline, about 7 s
docker compose stop                       # frees the containers' memory; data is kept
```

## Using DocDrift

### The demo page

`docdrift/web/` is a static page served by the API itself, so it needs no Node build. The
layout follows the demo sketch:

| column | content |
|---|---|
| 1 | conversation history for this browser tab |
| 2 | relevant documents: cited first, then documents a change record targets, then the rest collapsed; ABB/synthetic labels, previous revision |
| 3 | status, equipment and the cited guidance steps, above the page preview: the real PDF page with the rows and lines the answer relies on highlighted, page arrows, and *Open PDF* |
| 4 | approval evidence (change notice, channel, decision, approver, whether the change is reflected in the current document, and a one-line change description), escalation with a demo-only button, and every record examined |

The cited guidance sits above the preview because the sketch had no answer area, and the
operator needs it next to the page it quotes. *View approval evidence records* opens a
second page with one card per record examined: the same five fields and change
description on the left, and on the right the approval log - every message and notice
on that change, oldest first, as plain text. The three demo questions are always shown,
and a strict/flexible toggle sets the governance mode per question. When an answer is
withheld, each failed check is listed on its own line; if the equipment could not be
confirmed, only that check is listed, with the closest registered asset. The page uses
ABB's palette: red `#FF000F`, black and white, grey neutrals, with orange for *Potential
Approved Update* and green for *Verified Current*. The ABB logo is not reproduced.

Highlighting works in two ways. In tables, a row is marked when it names a term from the
question ("tightening torque", "5091") and carries a value. In running text, a line is
marked when the cited passage contains it and it has at least six words. Page navigation
re-renders only the preview and never moves the page's scroll position.

The history lives only in the page's memory. It is never put in localStorage or
sessionStorage, and a reload clears it.

### Static demo (GitHub Pages)

`docs/` holds a copy of the demo page that needs no server. It replays the answers the
real pipeline gave to the three demo questions, in both governance modes, with the cited
pages rendered and highlighted as the live page shows them. Records, the evidence page and
page navigation around each cited page all work; *Open PDF* links to the document in the
ABB Library. Any other question is refused with a note to run DocDrift locally.

To publish: on GitHub, *Settings > Pages > Build and deployment*, source *Deploy from a
branch*, branch `main`, folder `/docs`. The page appears at
`https://<user>.github.io/<repository>/` after a minute.

Rebuild after any change that alters answers (it needs the local ABB library):

```bash
python scripts/build_static_demo.py      # about 1 minute; writes docs/, about 8 MB
```

### Audit trail - off by default

| setting | default | effect when on |
|---|---|---|
| `DOCDRIFT_AUDIT_ENABLED` | `false` | every question/answer turn is appended to the conversation store, and the full governance reasoning to `audit/decisions.jsonl` |
| `DOCDRIFT_AUDIT_STORE` | `sqlite:///audit/conversations.sqlite` (base), `postgresql://...` (production) | where the `conversation_turns` table lives |

The business records are also read-only at the database level. They are loaded once at
startup, then the connection is sealed (`PRAGMA query_only`), and SQLite itself refuses
any insert, update, delete or schema change for the rest of the run. The audit store is a
separate connection. For the production stack, the same guarantee comes from connecting
to PostgreSQL as a role granted `SELECT` only, with loading done by a separate role.

With audit off, the backend writes nothing: no file, no row, and `GET
/api/audit/conversations` returns an empty list. The page header shows the current
setting. Stored turns are grouped by a per-tab session id and are append-only.

### After updating the code

Stop the server (Ctrl+C) and start it again, then reload the page. The page files are
read from disk on every request, but the Python code is loaded once at startup, so an
old server behind new page files is a mismatch. The page checks for this and shows
"restart the server" in the header. During development,
`uvicorn docdrift.api:app --port 8000 --reload` restarts automatically on code changes.

### Base stack and production stack

The base stack stays the default and is never removed. Selection is by configuration at
startup, not by a control on the page, and the active stack is shown in the page header.

| component | base (default) | production |
|---|---|---|
| records | SQLite in memory | PostgreSQL 16 (Docker) |
| vector search | in-process index | Qdrant (Docker) |
| knowledge graph | in-process graph | Neo4j 5 Community (Docker) |
| embeddings | hashing (no download) | `BAAI/bge-small-en-v1.5` |
| wording | the manual's own sentences | Ollama `llama3.1:8b`, native |

```bash
DOCDRIFT_STACK=base        uvicorn docdrift.api:app --port 8000
DOCDRIFT_STACK=production  uvicorn docdrift.api:app --port 8000
DOCDRIFT_STACK=base DOCDRIFT_LLM_BACKEND=ollama uvicorn docdrift.api:app --port 8000   # mixed
```

Every component can be overridden on its own: `DOCDRIFT_RECORD_STORE`,
`DOCDRIFT_VECTOR_BACKEND`, `DOCDRIFT_GRAPH_BACKEND`, `DOCDRIFT_EMBEDDER`,
`DOCDRIFT_EMBEDDING_MODEL`, `DOCDRIFT_LLM_BACKEND`, `DOCDRIFT_OLLAMA_MODEL`,
`DOCDRIFT_AUDIT_STORE`, plus the service URLs and keys. A selected service that cannot
be reached stops the startup with a message; there is no silent fallback. The one
exception is Ollama: if it is not running, answers use the manual's own sentences, and
the header says so.

**Loading and serving are separate.** `scripts/load_production.py` writes the corpus into
PostgreSQL, Qdrant and Neo4j with the loader credentials, and stamps each with a build
fingerprint. The API connects read-only and refuses to start if the three hold
different builds, so a half-finished reload cannot serve mixed data.

**Read-only is enforced by each service**, not only by the code:

| service | API credential | what the service refuses |
|---|---|---|
| PostgreSQL | role `docdrift_reader`: `SELECT` on records, `INSERT` on the audit table only | any update, delete or schema change; changing a stored audit turn |
| Qdrant | read-only API key | any upsert or delete |
| Neo4j | read-access sessions | any write query |

`scripts/check_production.py` attempts a write through each one and fails unless the
service refuses it.

**Neo4j checks approval authority.** For every change with an approver, the graph is
asked for a path: the decision, decided by a person, who holds a role, which is
authorised for the change's scope on the decision date. This is derived separately from
the authority records. Gate G10 requires the two to agree; if they disagree, the answer
is withheld. The path is shown on the evidence records page.

**The LLM only rewords, and is checked.** Each guidance step is the manual's sentence,
reworded by the model. The rewording is discarded, and the manual's sentence used, if it
adds or drops any number, code or value, adds or removes a negation, or is much longer.
The citation always quotes the manual verbatim.

---

## The corpus

| artefact | count |
|---|---:|
| product categories (drives, softstarters, motor protection) | 3 |
| equipment models | 8 |
| ABB publications (version n) | 141, from 170 PDF files |
| ABB pages indexed | 5,398 of 5,631 (the rest are blank, contents-only or image-only) |
| synthetic historical versions (n-1) | 10, each 1-2 source pages, written as diffs |
| communications | 62 (three months of traffic plus four older approved notices) |
| formal change notices | 8 |
| personnel / departments | 13 / 6 |
| approval scopes / authority rows | 8 / 15 |
| indexed chunks | 6,753 (6,741 extracted from ABB publications, 12 synthetic historical) |
| evaluation questions | 20, run in both modes |

The brief's target of 12-20 ABB documents is deliberately exceeded, because the whole
downloaded library is indexed.

### Equipment

| tag | model / type code | asset | documents linked |
|---|---|---|---:|
| M4 | ACS580-01 | Line 2 supply fan drive | 14 |
| M7 | ACS580-04 | Line 3 extraction fan drive module | 10 |
| M9 | ACS480 | Packing line machinery drive | 9 |
| S1 | PSTX30 / PSTX30-600-70 | Line 1 belt conveyor softstarter | 32 |
| S2 | PSTX142 / PSTX142-600-70 | Line 2 mixer softstarter | 26 |
| S3 | PSR25 / PSR25-600-70 | Coolant pump softstarter | 19 |
| P5 | MS132-10T | Control transformer primary breaker | 17 |
| K2 | AF38 / AF38-30-00-13 | Line 1 conveyor feeder contactor | 20 |

M4 is documented from the ACH580-01 bundle: ABB publishes the ACS580-01, ACH580-01 and
ACQ580-01 wall-mounted drives in shared hardware documents, and the ACS580 firmware manual
applies family-wide. A publication is linked to an asset when it sits in the asset's
bundle and does not name only other families, when it names the exact model, or when it
is a family-wide firmware manual. A title that scopes a publication to a frame range is
decisive: the PSTX1050...1250 and PSTX720...840 service manuals are not linked to a
PSTX142, however often their body text mentions other frames.

### The cases the corpus is built to test

| record | what it is | DocDrift's finding |
|---|---|---|
| `ECN-2026-011` | formal notice, Chief Engineer, safety-function scope, not yet in firmware manual rev J | **effective** - the headline drift |
| `ECN-2025-129` | approved before rev J and carried into it | `already_incorporated` - found only because the window opens at n-1 |
| `C-4130` | Procurement Manager writes "Approved" on the STO wiring | `unauthorized_approval` - `OUT_OF_SCOPE` |
| `C-4111` | Chief Engineer approves the PSTX inspection interval in Teams, no formal record | strict: `approval_without_formal_record`; flexible: **effective** |
| `C-4121` | Engineering Manager: "This looks reasonable; let me confirm after the safety review." | `pending_confirmation` - `VERIFIED` authority, unapproved decision |
| `C-4140` | technicians discussing AF38 terminal torque in Teams | `discovery_evidence` - excluded before the incorporation comparison |
| `ECN-2026-033` → `C-4160` | approved, then "cancelled" by a technician | still **effective** - the reversal lacks authority |
| `ECN-2026-031` | approved under a delegation that had lapsed on the decision date | `approval_authority_expired` |
| `ECN-2026-027` → `C-4150` | approved, then cancelled by the Chief Engineer | `invalidated` |
| `EB-2026-020` | engineering bulletin carrying an approval | refused in both modes - not an approval channel |

---

## Operator-photo OCR extension

Interface and feature flag only. `ENABLE_OPERATOR_OCR=false`.

```
operator uploads a photo
  -> validate content type and size          validate_upload()
  -> extract visible text                    OperatorPhotoExtractor.extract()   [not implemented]
  -> detect model / asset tag / fault code   parse_extracted_text()             [works today]
  -> operator reviews and edits              PhotoExtraction.apply_edits()
  -> combine with the mandatory text input   combine_with_question()
  -> continue through the normal workflow
```

The text question stays mandatory: a photo on its own is rejected. The extraction is an
operator-editable hint about which machine is meant - it is never cited, and nothing
extracted from a photo becomes evidence. With the flag off, `DisabledPhotoExtractor`
refuses and `POST /ask/photo` returns 501. `TesseractPhotoExtractor` is declared with no
body, so no half-working OCR path can be reached by accident.

---

## Pipeline

| stage | module | what it decides |
|---|---|---|
| Equipment resolution | `entity.py` | tag / model / fault-code extraction, confidence, ambiguity, unique-model resolution |
| Version resolution | `versioning.py` | current and previous revision per applicable document, freshness date |
| Hybrid retrieval | `retrieval.py` | BM25 (inverted index) + dense vectors fused with reciprocal rank fusion, under a hard document filter |
| Precision rerank | `rerank.py` | question coverage, phrase match, model and frame-range anchoring, fault-table row detection, contents-page and accessory-page demotion |
| Temporal change search | `drift.py` | communications since the freshness date, applicability, topical scope |
| Governance test | `governance.py`, `drift.py` | the nine conditions, decision state, authority state, invalidation |
| Incorporation check | `drift.py` | normative-term coverage plus effective-date-versus-approval-date |
| Answer composition | `answer.py` | extractive, question-anchored, one citation per step |
| Citation validation | `validate.py` | quote verbatim, page matches, source revision is current |
| Deterministic gates | `policy.py` | G1-G9; a blocking failure withholds the answer |
| Audit | `audit.py` | append-only JSONL with the verdict for every record examined |

### Verification gates

| gate | withholds the answer when |
|---|---|
| `G1_EQUIPMENT_IDENTIFIED` | equipment unresolved or below the confidence threshold |
| `G2_APPLICABLE_CURRENT_DOCUMENT` | no applicable document resolves to a current revision |
| `G3_EVERY_STEP_CITED` | any guidance step lacks a citation |
| `G4_CITATIONS_RESOLVE` | a quote is not verbatim, the page disagrees, or the source revision is superseded |
| `G5_DRIFT_DISCLOSED` | a change passed every condition and the answer does not disclose it |
| `G6_NO_UNAUTHORISED_APPROVAL_CLAIM` | a refused record is presented as an approved change |
| `G7_EVIDENCE_FULLY_DISCLOSED` | a refused record is hidden from the operator |
| `G8_PROVENANCE_LABELLED` | synthetic text is presented as an ABB publication |
| `G9_READ_ONLY` | advisory only - asserts no write was performed |

### Grounding

Guidance sentences are **selected**, not generated. Prose is quoted whole; specification
tables are quoted as a verbatim window around the matched phrase ("Tightening torque 1.5
Nm / 13 lb.in 2.5 Nm / 22 lb.in"). For a fault question, steps come only from the page that
defines the fault and stop at the next fault row. Each step quotes a span of a retrieved
chunk verbatim, so `validate.py` can prove the quote exists in the cited source. The LLM
adapter (`llm.py`) may rephrase an already-grounded sentence for readability and nothing
else; the cited quote remains the original span and the gates re-run over the result. With
no Ollama running, the extractive composer is used and the output is deterministic.

---

## Evaluation

`scripts/evaluate.py` runs 20 questions in both governance modes - 40 case runs, 252
checks - and checks the *conclusion*, not merely that an answer appeared: which asset was
resolved, which documentation status was reached, which record was allowed to alter
guidance, how each refused record was classified, that the expected ABB page was cited,
that no superseded revision was cited, and that the gates held. Current result:
**40/40**. Deliberately wrong expectations (a wrong status, a wrong page) are caught.

`pytest` covers the same ground structurally: corpus scale, channel coverage, provenance,
the anchoring of every change thread to its real page, frame-range applicability, each
governance branch, invalidation with and without authority, both modes, the n-1 window,
the OCR interface, citation validation, gate blocking, the audit switch, stack selection,
the demo-page API, the synthetic PDFs and download-name handling. **86 tests,
no network, ~6 s.**

A fresh checkout has the manifest but not the library. There, the 17 tests that assert on
ABB text skip with a pointer to the three library scripts, and the 36 that test
governance logic pass. Without the text, DocDrift cannot confirm that `ECN-2025-129` is
in rev J, so it surfaces the change instead of assuming it - the conservative outcome, and
tested as such.

---

## Production stack: operating notes

Setup is in *Setup (once)*, part B.

Memory: the three containers take about 2 GB (Neo4j is capped at 768 MB),
`llama3.1:8b` about 5-6 GB while loaded, and the API with the embedding model about
1 GB. `docker compose stop` frees the first; Ollama unloads the model after 30 minutes
idle. Neo4j Browser, at http://localhost:7474 (user `neo4j`, password `docdrift1`), shows
the graph: try
`MATCH p=(:Communication {id:'ECN-2026-011'})-[:DECIDED_BY]->()-[:HAS_ROLE]->()-[:AUTHORISED_FOR]->() RETURN p`.

Reload after changing the library, the synthetic history or the enterprise records: run
`load_production.py` again, then restart the API. To start over completely:
`docker compose down -v`, then `docker compose up -d` and `load_production.py`.

## Adapters

Every backend sits behind a protocol in `store/base.py`; all wiring lives in `app.py`.
Nothing in the pipeline imports a database driver.

| base | production | interface |
|---|---|---|
| `SqliteRecordStore` | `PostgresRecordStore` (same tables, JSONB payloads) | `RecordStore` |
| `LocalVectorStore` | `QdrantVectorStore` (payload-filtered search) | `VectorStore` |
| `MemoryGraphStore` | `Neo4jGraphStore` (Cypher authority path) | `GraphStore` |
| `HashingEmbedder` | `SentenceTransformerEmbedder` | `Embedder` |
| `ExtractiveClient` | `GuardedClient(OllamaClient)` | `LLMClient` |
| `DisabledPhotoExtractor` | `TesseractPhotoExtractor` behind `ENABLE_OPERATOR_OCR` | `OperatorPhotoExtractor` |

Keyword search (BM25) stays in-process in both stacks, over the chunks read from the
record store, so the two stacks rank from the same text.
