"""Synthetic historical (n-1) revisions.

IMPORTANT: none of this is an ABB publication. A real revision changes a few passages
of a document and repeats the rest, so each reconstruction here is written as a *diff
against the current ABB revision*: the n-1 page is the current page with a small number
of passages reverted to what DocDrift pretends they said before. The repository
therefore carries only the edits - short passages - and never a copy of an ABB page;
the overlapping text is derived at build time from the local, gitignored ABB text.

Each reconstruction is deliberately compact: one or two source pages, cut to a window
around the edited passage, rendered as a 1-2 page PDF with a revision-history block.

Every version built from this module carries `ContentProvenance.SYNTHETIC_HISTORICAL`,
a visible disclaimer, a "(synthetic)" citation marker and - when rendered to PDF - a
diagonal watermark on every page.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

DISCLAIMER = ("SYNTHETIC HISTORICAL RECONSTRUCTION - NOT AN ABB PUBLICATION. "
              "Authored for the DocDrift demonstration to stand in for the previous "
              "revision of this document. Do not use for engineering purposes.")

EXCERPT_CHARS = 1100


@dataclass(frozen=True)
class PageEdit:
    page: int
    title: str
    #: (text in the current ABB revision, what the previous revision said instead)
    edits: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class HistoricalRevision:
    doc_key: str
    previous: str                     # revision label of the reconstruction
    effective: date                   # effective date of the reconstruction
    why: str                          # what the reconstruction is needed for
    history: tuple[tuple[str, str, str], ...]   # (revision, date, change) up to n-1
    pages: tuple[PageEdit, ...] = field(default_factory=tuple)

    @property
    def changes_to_current(self) -> list[str]:
        """What changed between this reconstruction and the current ABB revision."""
        out = []
        for p in self.pages:
            for cur, prev in p.edits:
                out.append(f"p.{p.page}: " + (f'"{prev}" became "{cur}"' if prev
                                               else f'added "{cur}"'))
        return out


HISTORICAL_REVISIONS: tuple[HistoricalRevision, ...] = (
    # ---- drives ------------------------------------------------------------------
    HistoricalRevision(
        "3AXD50000016097", "H", date(2024, 7, 28),
        "ECN-2025-129 was approved between rev H and rev J and carried into rev J; only "
        "the n-1 window finds it. ECN-2026-011 targets the same fault row.",
        (("G", "2023-09-12", "Parameter listing updated."),
         ("H", "2024-07-28", "Fault table reorganised; safety cross-references updated.")),
        (PageEdit(556, "Fault tracing - fault messages", (
            ("5091 Safe torque off Programmable fault: 31.22 STO indication run/stop Safe "
             "torque off function is active",
             "5091 Safe torque off Safe torque off function is active"),)),)),
    HistoricalRevision(
        "3AXD50000047399", "F", date(2024, 9, 2),
        "ECN-2025-071 added the control board supply check to the 5091 row; incorporated "
        "in rev G. Same fault code as M4, different family.",
        (("E", "2023-11-20", "New parameters for firmware 2.1x."),
         ("F", "2024-09-02", "Fault tracing chapter renumbered.")),
        (PageEdit(539, "Fault tracing - fault messages", (
            ("(page 342). Check the value of parameter 95.04 Control board supply.",
             "(page 338)."),)),)),
    HistoricalRevision(
        "3AXD50000047392", "E", date(2023, 3, 15),
        "EB-2026-020 targets the insulation measurement section of this manual.",
        (("D", "2022-04-04", "Frame R4 added."),
         ("E", "2023-03-15", "Electrical installation chapter restructured.")),
        (PageEdit(64, "Measuring the insulation resistance", (
            ("Also, there are voltage-limiting circuits inside the drive which cut down "
             "the testing voltage automatically. ", ""),)),)),
    HistoricalRevision(
        "3AXD50000015497", "E", date(2021, 6, 14),
        "ECN-2022-015 required 360-degree grounding of input cable shields; incorporated "
        "in rev F.",
        (("D", "2020-05-11", "Cabling panel option +H381 added."),
         ("E", "2021-06-14", "Installation procedure updated.")),
        (PageEdit(124, "Connecting the power cables", (
            ("Ground the cable shields 360° at the entry plate.",
             "Ground the cable shields at the entry plate."),)),)),
    HistoricalRevision(
        "4FPS10000309652", "0", date(2024, 3, 1),
        "ECN-2025-102 adopted an annual drive inspection interval; the current schedule "
        "states it.",
        (("0", "2024-03-01", "First issue."),),
        (PageEdit(1, "Maintenance schedule - introduction", (
            ("ABB recommends annual drive inspections to ensure the highest reliability",
             "ABB recommends regular drive inspections to ensure the highest reliability"),)),)),

    # ---- softstarters ------------------------------------------------------------
    HistoricalRevision(
        "1SFC132081M0201", "P", date(2021, 1, 31),
        "The maintenance-interval (CHG-2026-014) and EOL-class (CHG-2026-018) threads "
        "target these pages.",
        (("N", "2019-11-04", "PSTX720...1250 added."),
         ("P", "2021-01-31", "Parameter chapter revised.")),
        (PageEdit(150, "9.1 Regular maintenance", (
            ("• Tighten the terminal screws and bolts on the connection bars, if necessary. ",
             ""),)),
         PageEdit(103, "Electronic overload protection", (
            ("13.02 EOL class Sets the EOL trip class. 10 A, 10, 20, 30 10",
             "13.02 EOL class Sets the EOL trip class. 10, 20, 30 10"),)))),
    HistoricalRevision(
        "1SFC132012C0201", "H", date(2024, 9, 16),
        "Catalog summary of the PSTX protections; overlaps the EOL-class thread.",
        (("G", "2023-08-21", "PSE range updated."),
         ("H", "2024-09-16", "Communication accessories revised.")),
        (PageEdit(63, "PSTX protections", (
            ("Dual overload (separate overload for start and run) Possible to set separate "
             "overloads for start and full speed ", ""),)),)),
    HistoricalRevision(
        "1SFC132031M0001", "H", date(2012, 5, 2),
        "Coolant pump softstarter S3: a revision with no change thread at all.",
        (("G", "2010-10-18", "UL data added."),
         ("H", "2012-05-02", "Short-circuit ratings revised.")),
        (PageEdit(1, "Installation and operating instruction", (
            ("85000 rms symmetrical A", "65000 rms symmetrical A"),)),)),

    # ---- motor protection --------------------------------------------------------
    HistoricalRevision(
        "1SBC100214C0202", "2023", date(2022, 12, 2),
        "The AF38 terminal re-torque (CHG-2026-033) and coil band (CHG-2026-031) threads "
        "target these pages.",
        (("2022", "2021-11-15", "AF..Z range extended."),
         ("2023", "2022-12-02", "Technical data pages revised.")),
        (PageEdit(180, "AF09...AF38 connecting characteristics", (
            ("Tightening torque 1.5 Nm / 13 lb.in 2.5 Nm / 22 lb.in",
             "Tightening torque 1.2 Nm / 11 lb.in 2.5 Nm / 22 lb.in"),)),
         PageEdit(175, "AF09...AF38 coil operating limits", (
            ("AC supply At θ ≤ 60 °C", "AC supply At θ ≤ 55 °C"),)))),
    HistoricalRevision(
        "2CDC131058D0201", "C", date(2019, 10, 1),
        "The transformer-protection thread (CHG-2026-027) targets this data sheet.",
        (("B", "2018-02-12", "MS132-KT added."),
         ("C", "2019-10-01", "Technical data revised.")),
        (PageEdit(1, "Circuit breakers for transformer protection", (
            ("fixed to 20 times the operational current",
             "fixed to 17 times the operational current"),)),)),
)

HISTORICAL: dict[str, HistoricalRevision] = {h.doc_key: h for h in HISTORICAL_REVISIONS}


def _excerpt(text: str, anchor: int, size: int = EXCERPT_CHARS) -> str:
    start = max(0, anchor - size // 3)
    if start:
        start = text.find(" ", start) + 1
    end = min(len(text), start + size)
    if end < len(text):
        end = text.rfind(" ", start, end)
    return ("... " if start else "") + text[start:end].strip() + (" ..." if end < len(text) else "")


def reconstruct_page(page_text: str | None, edit: PageEdit) -> tuple[str, bool]:
    """Return (n-1 text for the page, derived_from_current).

    With the ABB text available, the current page is cut to a window around the first
    edited passage and the edits are reverted *inside that window*, so the previous and
    current excerpts cover exactly the same stretch of the page and differ only where
    an edit says so. Without the ABB text only the edited passages exist.
    """
    if page_text:
        window = current_excerpt(page_text, edit)
        prev, applied = window, False
        for cur, old in edit.edits:
            if cur in prev:
                prev, applied = prev.replace(cur, old, 1), True
        if applied:
            return " ".join(prev.split()), True
    passages = [old or "(passage not present in this revision)" for _, old in edit.edits]
    return " ".join(passages), False


def current_excerpt(page_text: str, edit: PageEdit) -> str:
    """The same window of the current page, for side-by-side comparison."""
    flat = " ".join(page_text.split())
    at = min((flat.find(cur) for cur, _ in edit.edits if cur in flat), default=0)
    return _excerpt(flat, at)
