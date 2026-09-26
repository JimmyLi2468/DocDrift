import pytest

from docdrift.app import BackendNotAvailable, build_pipeline
from docdrift.audit import NullConversationStore, SqliteConversationStore, build_conversation_store
from docdrift.config import STACK_PROFILES, Settings

Q = "What regular maintenance does the manual specify for softstarter S2?"


def test_audit_is_off_by_default(monkeypatch):
    monkeypatch.delenv("DOCDRIFT_AUDIT_ENABLED", raising=False)
    assert Settings().audit_enabled is False
    assert Settings.from_env().audit_enabled is False
    assert isinstance(build_conversation_store(Settings()), NullConversationStore)


def test_nothing_is_written_when_audit_is_off(tmp_path, corpus):
    s = Settings()
    s.audit_path = str(tmp_path / "decisions.jsonl")
    s.audit_store_url = f"sqlite:///{tmp_path / 'conv.sqlite'}"
    p = build_pipeline(s, corpus)
    p.ask(Q, session_id="demo")
    assert not (tmp_path / "decisions.jsonl").exists()
    assert not (tmp_path / "conv.sqlite").exists()


def test_conversations_are_stored_when_audit_is_on(tmp_path, corpus):
    s = Settings(audit_enabled=True, audit_path=str(tmp_path / "d.jsonl"),
                 audit_store_url=f"sqlite:///{tmp_path / 'conv.sqlite'}")
    p = build_pipeline(s, corpus)
    p.ask(Q, session_id="tab-1", turn_id="t1")
    p.ask("What EOL trip class should softstarter S1 use?", session_id="tab-1", turn_id="t2")
    p.ask(Q, session_id="tab-2", turn_id="t3")
    turns = p.conversations.turns("tab-1")
    assert [t["turn_id"] for t in turns] == ["t1", "t2"]
    assert turns[0]["question"] == Q and turns[0]["equipment"] == "S2"
    assert len(SqliteConversationStore(str(tmp_path / "conv.sqlite")).turns()) == 3


def test_env_switches_audit_and_stack(monkeypatch):
    monkeypatch.setenv("DOCDRIFT_AUDIT_ENABLED", "true")
    monkeypatch.setenv("DOCDRIFT_STACK", "production")
    monkeypatch.setenv("DOCDRIFT_VECTOR_BACKEND", "local")
    s = Settings.from_env()
    assert s.audit_enabled and s.stack == "production"
    assert s.vector_backend == "local"                  # per-component override wins
    assert s.llm_backend == STACK_PROFILES["production"]["llm_backend"]


def test_base_stack_is_the_default():
    s = Settings.from_env()
    for k, v in STACK_PROFILES["base"].items():
        assert getattr(s, k) == v


def test_unimplemented_production_backend_fails_loudly(corpus):
    with pytest.raises(BackendNotAvailable, match="PostgreSQL adapter"):
        build_pipeline(Settings.for_stack("production"), corpus)
