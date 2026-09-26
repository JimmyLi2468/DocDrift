from datetime import date

from docdrift.versioning import resolve_versions
from tests.marks import ABB_TEXT_INDEXED

FW580 = "3AXD50000016097"


def test_freshness_date_is_the_previous_revision_effective_date(pipeline):
    res = {r.doc_id: r for r in resolve_versions(pipeline.store, pipeline.store.get_equipment("M4"))}
    fw = res[FW580]
    assert fw.current.version == "J"
    assert fw.previous is not None and fw.previous.version == "H"
    assert fw.freshness_search_from == fw.previous.effective_date
    assert fw.freshness_search_from < fw.current.effective_date


def test_a_document_without_history_opens_its_window_at_the_current_revision(pipeline):
    res = resolve_versions(pipeline.store, pipeline.store.get_equipment("S3"))
    plain = [r for r in res if r.previous is None]
    assert plain and len(plain) < len(res)      # S3 has one reconstructed revision
    assert all(r.freshness_search_from == r.current.effective_date for r in plain)
    hist = [r for r in res if r.previous is not None]
    assert all(r.freshness_search_from == r.previous.effective_date for r in hist)


def test_applicability_comes_from_the_asset_register(pipeline):
    eq = pipeline.store.get_equipment("S3")
    res = resolve_versions(pipeline.store, eq)
    assert {r.doc_id for r in res} == set(eq.doc_ids)


def test_the_n_minus_1_window_finds_a_change_approved_before_rev_j(pipeline):
    """ECN-2025-129 predates rev J. Searching from rev J would never see it; searching
    from the n-1 date does, and it is then correctly refused as already incorporated."""
    _, bundle = pipeline.ask("Drive M4 trips with fault 5091 after operating for ten minutes.")
    fw = next(r for r in bundle.versions if r.doc_id == FW580)
    ecn = next(c for c in bundle.candidate_changes if c.communication.comm_id == "ECN-2025-129")
    assert fw.freshness_search_from <= ecn.communication.date < fw.current.effective_date
    assert fw.freshness_search_from < date(2025, 6, 10)
    if ABB_TEXT_INDEXED:
        assert ecn.classification == "already_incorporated"
    else:
        # Without the document text incorporation cannot be confirmed, so the change is
        # surfaced rather than assumed to be in the manual - the conservative outcome.
        assert ecn.incorporation is not None and not ecn.incorporation.incorporated
