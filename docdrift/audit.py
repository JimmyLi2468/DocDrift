"""Audit trail: the decision log and the conversation store.

Both are OFF unless `Settings.audit_enabled` (env `DOCDRIFT_AUDIT_ENABLED=true`). With it
off, nothing an operator asks is written anywhere by the backend.

- Decision log: one JSON object per question with the governance reasoning for every
  record examined (`audit/decisions.jsonl`).
- Conversation store: one row per question/answer turn, grouped by the browser
  session that asked it. SQLite file in the base stack, PostgreSQL in production -
  same table, same columns. Append-only: DocDrift never updates or deletes a row.
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
from datetime import datetime, timezone
from typing import Protocol

from .models import EvidenceBundle, OperatorAnswer

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversation_turns (
    turn_id        TEXT PRIMARY KEY,
    session_id     TEXT NOT NULL,
    asked_at       TEXT NOT NULL,
    question       TEXT NOT NULL,
    governance_mode TEXT NOT NULL,
    equipment      TEXT,
    status         TEXT NOT NULL,
    answered       INTEGER NOT NULL,
    pending_change TEXT,
    decision       TEXT NOT NULL      -- the decision-log entry as JSON
)
"""


def decision_entry(question: str, bundle: EvidenceBundle, answer: OperatorAnswer) -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "question": question,
        "governance_mode": bundle.mode.value,
        "equipment": bundle.equipment.equipment.asset_tag if bundle.equipment.equipment else None,
        "equipment_confidence": bundle.equipment.confidence,
        "equipment_input": bundle.equipment.source,
        "documents": [f"{r.doc_id}@{r.current.version}" for r in bundle.versions],
        "freshness_search_from": min((r.freshness_search_from for r in bundle.versions), default=None),
        "status": answer.status.value,
        "citations": [{"chunk_id": c.chunk_id, "provenance": c.provenance.value}
                      for s in answer.guidance for c in s.citations],
        "changes_examined": [
            {"comm_id": c.communication.comm_id, "change_ref": c.communication.change_ref,
             "channel": c.communication.channel.value,
             "decision_state": c.verdict.decision_state.value,
             "authority_state": c.verdict.authority_state.value,
             "classification": c.classification, "effective": c.effective,
             "failed_conditions": c.verdict.failed,
             "invalidated_by": c.verdict.invalidated_by}
            for c in bundle.candidate_changes],
        "gates": [{"gate": g.gate, "passed": g.passed, "detail": g.detail} for g in answer.gates],
        "answered": answer.answered,
    }


def record(path: str, question: str, bundle: EvidenceBundle, answer: OperatorAnswer) -> dict:
    """Append one decision-log entry. Callers check `audit_enabled` first."""
    entry = decision_entry(question, bundle, answer)
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as fh:
        fh.write(json.dumps(entry, default=str) + "\n")
    return entry


class ConversationStore(Protocol):
    def append(self, turn_id: str, session_id: str, entry: dict, answer: OperatorAnswer) -> None: ...
    def turns(self, session_id: str | None = None) -> list[dict]: ...


class NullConversationStore:
    """Audit disabled: accepts nothing, stores nothing."""
    enabled = False

    def append(self, *args, **kwargs) -> None:
        return None

    def turns(self, session_id: str | None = None) -> list[dict]:
        return []


class SqliteConversationStore:
    enabled = True

    def __init__(self, path: str) -> None:
        if path != ":memory:":
            pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute(SCHEMA)
        self.db.commit()

    def append(self, turn_id: str, session_id: str, entry: dict, answer: OperatorAnswer) -> None:
        self.db.execute(
            "INSERT INTO conversation_turns VALUES (?,?,?,?,?,?,?,?,?,?)",
            (turn_id, session_id, entry["timestamp"], entry["question"], entry["governance_mode"],
             entry["equipment"], entry["status"], int(entry["answered"]), answer.pending_change,
             json.dumps(entry, default=str)))
        self.db.commit()

    def turns(self, session_id: str | None = None) -> list[dict]:
        q = "SELECT turn_id, session_id, asked_at, question, governance_mode, equipment, status, " \
            "answered, pending_change FROM conversation_turns"
        rows = (self.db.execute(q + " WHERE session_id=? ORDER BY asked_at", (session_id,))
                if session_id else self.db.execute(q + " ORDER BY asked_at"))
        cols = [d[0] for d in rows.description]
        return [dict(zip(cols, r)) for r in rows.fetchall()]


class PostgresConversationStore:
    """Same table in PostgreSQL. Written against psycopg 3; exercised only when the
    production stack is running."""
    enabled = True

    def __init__(self, url: str) -> None:
        import psycopg  # lazily: the base stack does not need the driver
        self.conn = psycopg.connect(url, autocommit=True)
        self.conn.execute(SCHEMA)

    def append(self, turn_id: str, session_id: str, entry: dict, answer: OperatorAnswer) -> None:
        self.conn.execute(
            "INSERT INTO conversation_turns VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (turn_id, session_id, entry["timestamp"], entry["question"], entry["governance_mode"],
             entry["equipment"], entry["status"], int(entry["answered"]), answer.pending_change,
             json.dumps(entry, default=str)))

    def turns(self, session_id: str | None = None) -> list[dict]:
        cur = self.conn.execute(
            "SELECT turn_id, session_id, asked_at, question, governance_mode, equipment, status, "
            "answered, pending_change FROM conversation_turns"
            + (" WHERE session_id=%s" if session_id else "") + " ORDER BY asked_at",
            (session_id,) if session_id else ())
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def build_conversation_store(settings) -> ConversationStore:
    if not settings.audit_enabled:
        return NullConversationStore()
    url = settings.audit_store_url
    if url.startswith("sqlite:///"):
        return SqliteConversationStore(url[len("sqlite:///"):])
    if url.startswith("postgresql://"):
        return PostgresConversationStore(url)
    raise ValueError(f"unsupported audit store {url!r}")
