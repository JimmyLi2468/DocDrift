import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from tests.marks import needs_abb_text  # noqa: E402


@pytest.fixture(scope="module")
def client():
    from docdrift.api import app
    return TestClient(app)


def test_demo_page_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "DocDrift" in r.text
    assert client.get("/app.js").status_code == 200


def test_config_exposes_three_demo_questions_and_audit_off(client):
    cfg = client.get("/api/config").json()
    assert len(cfg["demo_questions"]) == 3
    assert cfg["audit_enabled"] is False
    assert cfg["stack"]["stack"] == "base"


def test_ask_is_not_stored_by_default(client):
    v = client.post("/api/ask", json={"question": "What EOL trip class should softstarter S1 use?",
                                      "session_id": "t"}).json()
    assert v["stored"] is False
    assert client.get("/api/audit/conversations").json()["turns"] == []


@needs_abb_text
def test_core_view_links_to_the_evidence_records(client):
    v = client.post("/api/ask", json={"question": "Drive M4 trips with fault 5091 after operating for ten minutes."}).json()
    assert v["status"] == "Potential Approved Update"
    assert v["has_unincorporated_approved_change"]
    eff = [c for c in v["changes"] if c["effective"]]
    assert eff and eff[0]["comm_id"] == "ECN-2026-011" and len(eff[0]["conditions"]) == 9
    assert v["documents"][0]["role"] == "cited"


@needs_abb_text
def test_page_image_and_compare(client):
    img = client.get("/api/documents/3AXD50000016097/pages/556.png", params={"q": ["Check safety circuit connections."]})
    assert img.status_code == 200 and img.content[:4] == b"\x89PNG"
    cmp = client.get("/api/documents/3AXD50000016097/pages/556/compare").json()
    changed = [d for d in cmp["diff"] if d["op"] != "same"]
    assert changed == [{"op": "added", "text": "Programmable fault: 31.22 STO indication run/stop"}]


def test_only_manifest_documents_resolve(client):
    assert client.get("/api/documents/..%2F..%2Fetc%2Fpasswd/pdf").status_code == 404
    assert client.get("/api/documents/NOPE/pages/1.png").status_code == 404


def test_every_governance_condition_has_a_label(pipeline):
    from docdrift.views import CONDITION_LABELS
    _, bundle = pipeline.ask("What EOL trip class should softstarter S1 use?")
    ids = {k.condition for c in bundle.candidate_changes for k in c.verdict.conditions}
    assert ids and ids <= set(CONDITION_LABELS)


def test_partial_type_code_names_the_closest_asset_and_one_check(pipeline):
    a, _ = pipeline.ask("MS132-10 keeps tripping at 10A")
    assert not a.answered
    lines = a.clarification_needed.splitlines()
    assert "P5" in lines[0] and "MS132-10T" in lines[0]
    assert [l for l in lines if l.startswith("- ")] == [l for l in lines if l.startswith("- Equipment identified")]


def test_page_and_server_versions_match():
    import re
    from docdrift import __version__
    from docdrift.api import WEB_DIR
    js = (WEB_DIR / "app.js").read_text()
    assert re.search(r'const PAGE_VERSION = "([^"]+)"', js).group(1) == __version__


def test_record_store_is_read_only_at_the_database_level(pipeline):
    import sqlite3
    import pytest as _pytest
    with _pytest.raises(sqlite3.OperationalError, match="readonly|read-only|query_only"):
        pipeline.store.conn.execute("UPDATE doc_versions SET payload = '{}'")
    with _pytest.raises(sqlite3.OperationalError):
        pipeline.store.conn.execute("DELETE FROM communications")
    with _pytest.raises(sqlite3.OperationalError):
        pipeline.store.conn.execute("CREATE TABLE x (y)")
