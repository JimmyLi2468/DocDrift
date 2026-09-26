"""The corpus: scale, provenance, and the anchoring of every change thread to a real page."""
import pytest

from docdrift.corpus.enterprise import ANCHORS, SCENARIO_COMMS, title_excludes, EQUIPMENT
from docdrift.corpus.historical import HISTORICAL
from docdrift.governance import Channel
from docdrift.models import ContentProvenance
from tests.marks import needs_abb_text

#: The brief's targets. ABB documents and synthetic history deliberately differ: the
#: whole downloaded library is indexed (well above 12-20), and synthetic history exists
#: only where a change thread needs a previous revision to resolve against.
TARGETS = {
    "product_categories": (3, 3),
    "equipment_models": (6, 10),
    "communications": (40, 80),
    "change_notices": (5, 10),
    "personnel": (10, 15),
    "departments": (6, 6),
    "approval_scopes": (6, 10),
}


def test_corpus_meets_scale_targets(corpus):
    summary = corpus.summary()
    for key, (low, high) in TARGETS.items():
        assert low <= summary[key] <= high, f"{key}={summary[key]} outside {low}..{high}"
    assert summary["abb_documents"] >= 12


def test_ten_compact_synthetic_revisions(corpus):
    historical = {v.doc_id for v in corpus.versions if v.status == "superseded"}
    assert historical == set(HISTORICAL) and 6 <= len(historical) <= 10
    for h in HISTORICAL.values():
        assert 1 <= len(h.pages) <= 2, h.doc_key
        current = next(v for v in corpus.versions if v.doc_id == h.doc_key and v.status == "current")
        assert h.effective < current.effective_date, h.doc_key


def test_most_revisions_are_tied_to_change_traffic():
    targeted = {d for c in SCENARIO_COMMS for d in c.affects_doc_ids}
    assert len(set(HISTORICAL) & targeted) >= 8


@needs_abb_text
def test_previous_revision_repeats_the_current_text_except_the_edit(corpus):
    """A revision changes passages, not the whole document: the n-1 excerpt must be
    derived from the current page and differ from it only where an edit says so."""
    from docdrift.corpus.historical import current_excerpt, reconstruct_page
    for h in HISTORICAL.values():
        for e in h.pages:
            page = " ".join(c.text for c in corpus.chunks if c.doc_id == h.doc_key
                            and c.page == e.page and c.provenance is ContentProvenance.ABB_PUBLIC_PDF)
            prev, derived = reconstruct_page(page, e)
            assert derived, (h.doc_key, e.page)
            cur = current_excerpt(page, e)
            assert prev != cur
            shared = set(prev.split()) & set(cur.split())
            assert len(shared) / len(set(cur.split())) > 0.8, (h.doc_key, e.page)


def test_every_channel_is_exercised(corpus):
    used = {c.channel for c in corpus.communications}
    assert used == set(Channel), sorted(c.value for c in set(Channel) - used)


def test_communications_span_three_months(corpus):
    dates = sorted(c.date for c in corpus.communications)
    assert (dates[-1] - dates[0]).days >= 84


def test_every_asset_has_applicable_documents(corpus):
    for eq in corpus.equipment:
        assert eq.doc_ids, eq.asset_tag


def test_frame_range_in_the_title_decides_applicability():
    s2 = next(e for e in EQUIPMENT if e.asset_tag == "S2")          # PSTX142
    assert title_excludes("Softstarters Type PSTX1050...1250", s2)
    assert title_excludes("Softstarters Type PSTX210...370", s2)
    assert not title_excludes("Softstarters Type PSTX30...PSTX1250", s2)
    assert not title_excludes("Softstarter catalog", s2)


def test_synthetic_history_is_labelled_and_never_claims_to_be_abb(corpus):
    historical = [v for v in corpus.versions if v.status == "superseded"]
    assert historical
    for v in historical:
        assert v.provenance is ContentProvenance.SYNTHETIC_HISTORICAL
        assert v.disclaimer and "NOT AN ABB PUBLICATION" in v.disclaimer
        assert v.source_url is None
    chunks = [c for c in corpus.chunks if c.provenance is ContentProvenance.SYNTHETIC_HISTORICAL]
    assert chunks and all("(synthetic)" in c.citation_label for c in chunks)


@needs_abb_text
def test_current_versions_are_indexed_abb_publications(corpus):
    current = [v for v in corpus.versions if v.status == "current"]
    assert all(v.provenance is ContentProvenance.ABB_PUBLIC_PDF for v in current)
    no_text = [v for v in current if not any(c.doc_id == v.doc_id for c in corpus.chunks)]
    assert all(v.doc_type in {"drawing", "technical_document"} for v in no_text), no_text
    assert all(v.source_url and "abb.com" in v.source_url for v in current if v.abb_document_id)


@needs_abb_text
@pytest.mark.parametrize("anchor", sorted(ANCHORS))
def test_change_threads_are_anchored_to_real_pages(corpus, anchor):
    doc_id, page = anchor
    text = " ".join(c.text for c in corpus.chunks
                    if c.doc_id == doc_id and c.page == page
                    and c.provenance is ContentProvenance.ABB_PUBLIC_PDF)
    assert ANCHORS[anchor] in text, f"{doc_id} p.{page} no longer says {ANCHORS[anchor]!r}"


INCORPORATED = {"ECN-2025-129", "ECN-2025-071", "ECN-2022-015", "ECN-2025-102"}


@needs_abb_text
def test_incorporated_changes_are_really_in_the_current_page(corpus):
    for comm in SCENARIO_COMMS:
        if comm.comm_id not in INCORPORATED:
            continue
        for doc_id in comm.affects_doc_ids:
            text = " ".join(" ".join(c.text.split()) for c in corpus.chunks
                            if c.doc_id == doc_id and c.section in comm.affects_sections
                            and c.provenance is ContentProvenance.ABB_PUBLIC_PDF).lower()
            for term in comm.normative_terms:
                assert term.lower() in text, (comm.comm_id, doc_id, term)


@needs_abb_text
def test_normative_terms_of_open_changes_are_absent_from_the_current_page(corpus):
    """Otherwise the incorporation test would have nothing real to find."""
    for comm in SCENARIO_COMMS:
        if not comm.normative_terms or comm.comm_id in INCORPORATED:
            continue
        for doc_id in comm.affects_doc_ids:
            text = " ".join(c.text for c in corpus.chunks
                            if c.doc_id == doc_id and c.section in comm.affects_sections
                            and c.provenance is ContentProvenance.ABB_PUBLIC_PDF).lower()
            for term in comm.normative_terms:
                assert term.lower() not in text, (comm.comm_id, doc_id, term)
