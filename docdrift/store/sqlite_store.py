"""SQLite-backed authoritative record store.

Mirrors the PostgreSQL schema one-to-one (same tables, same columns); swapping in
psycopg is a driver change, not a model change.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from typing import Sequence

from ..models import (Chunk, Communication, Department, DocumentVersion, Equipment,
                      Person)

SCHEMA = """
CREATE TABLE IF NOT EXISTS equipment (asset_tag TEXT PRIMARY KEY, payload TEXT NOT NULL, family TEXT, model TEXT);
CREATE TABLE IF NOT EXISTS departments (department_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS people (person_id TEXT PRIMARY KEY, payload TEXT NOT NULL, role TEXT);
CREATE TABLE IF NOT EXISTS doc_versions (doc_id TEXT, version TEXT, payload TEXT NOT NULL,
    effective_date TEXT, status TEXT, PRIMARY KEY (doc_id, version));
CREATE TABLE IF NOT EXISTS chunks (chunk_id TEXT PRIMARY KEY, doc_id TEXT, version TEXT, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS communications (comm_id TEXT PRIMARY KEY, date TEXT,
    change_ref TEXT, channel TEXT, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_chunks_docver ON chunks (doc_id, version);
CREATE INDEX IF NOT EXISTS ix_comms_date ON communications (date);
CREATE INDEX IF NOT EXISTS ix_comms_change ON communications (change_ref);
"""


class SqliteRecordStore:
    def __init__(self, path: str = ":memory:") -> None:
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    # ---------------------------------------------------------------- writes
    def _bulk(self, sql: str, rows: list[tuple]) -> None:
        self.conn.executemany(sql, rows)
        self.conn.commit()

    def upsert_equipment(self, items: Sequence[Equipment]) -> None:
        self._bulk(
            "INSERT OR REPLACE INTO equipment VALUES (?,?,?,?)",
            [(e.asset_tag, e.model_dump_json(), e.family, e.model) for e in items],
        )

    def upsert_people(self, items: Sequence[Person]) -> None:
        self._bulk("INSERT OR REPLACE INTO people VALUES (?,?,?)",
                   [(p.person_id, p.model_dump_json(), p.role) for p in items])

    def upsert_versions(self, items: Sequence[DocumentVersion]) -> None:
        self._bulk(
            "INSERT OR REPLACE INTO doc_versions VALUES (?,?,?,?,?)",
            [(v.doc_id, v.version, v.model_dump_json(), v.effective_date.isoformat(), v.status) for v in items],
        )

    def upsert_chunks(self, items: Sequence[Chunk]) -> None:
        self._bulk("INSERT OR REPLACE INTO chunks VALUES (?,?,?,?)",
                   [(c.chunk_id, c.doc_id, c.version, c.model_dump_json()) for c in items])

    def upsert_communications(self, items: Sequence[Communication]) -> None:
        self._bulk("INSERT OR REPLACE INTO communications VALUES (?,?,?,?,?)",
                   [(c.comm_id, c.date.isoformat(), c.change_ref, c.channel.value,
                     c.model_dump_json()) for c in items])

    def upsert_departments(self, items: Sequence[Department]) -> None:
        self._bulk("INSERT OR REPLACE INTO departments VALUES (?,?)",
                   [(d.department_id, d.model_dump_json()) for d in items])

    # ---------------------------------------------------------------- reads
    def all_equipment(self) -> list[Equipment]:
        return [Equipment.model_validate_json(r["payload"]) for r in self.conn.execute("SELECT payload FROM equipment")]

    def get_equipment(self, asset_tag: str) -> Equipment | None:
        r = self.conn.execute("SELECT payload FROM equipment WHERE asset_tag = ?", (asset_tag,)).fetchone()
        return Equipment.model_validate_json(r["payload"]) if r else None

    def get_person(self, person_id: str) -> Person | None:
        r = self.conn.execute("SELECT payload FROM people WHERE person_id = ?", (person_id,)).fetchone()
        return Person.model_validate_json(r["payload"]) if r else None

    def versions_for_doc(self, doc_id: str) -> list[DocumentVersion]:
        rows = self.conn.execute("SELECT payload FROM doc_versions WHERE doc_id = ?", (doc_id,))
        return sorted((DocumentVersion.model_validate_json(r["payload"]) for r in rows),
                      key=lambda v: v.effective_date)

    def versions_for_family(self, family: str) -> list[DocumentVersion]:
        out = []
        for r in self.conn.execute("SELECT payload FROM doc_versions"):
            v = DocumentVersion.model_validate_json(r["payload"])
            if family in v.applies_to_families:
                out.append(v)
        return out

    def chunks_for(self, doc_id: str, version: str) -> list[Chunk]:
        rows = self.conn.execute("SELECT payload FROM chunks WHERE doc_id = ? AND version = ?", (doc_id, version))
        return [Chunk.model_validate_json(r["payload"]) for r in rows]

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        r = self.conn.execute("SELECT payload FROM chunks WHERE chunk_id = ?", (chunk_id,)).fetchone()
        return Chunk.model_validate_json(r["payload"]) if r else None

    def all_chunks(self) -> list[Chunk]:
        return [Chunk.model_validate_json(r["payload"]) for r in self.conn.execute("SELECT payload FROM chunks")]

    def get_department(self, department_id: str) -> Department | None:
        r = self.conn.execute("SELECT payload FROM departments WHERE department_id = ?",
                              (department_id,)).fetchone()
        return Department.model_validate_json(r["payload"]) if r else None

    def communications_for_change(self, change_ref: str) -> list[Communication]:
        rows = self.conn.execute(
            "SELECT payload FROM communications WHERE change_ref = ? ORDER BY date", (change_ref,))
        return [Communication.model_validate_json(r["payload"]) for r in rows]

    def communications_since(self, since: date) -> list[Communication]:
        rows = self.conn.execute("SELECT payload FROM communications WHERE date >= ? ORDER BY date",
                                 (since.isoformat(),))
        return [Communication.model_validate_json(r["payload"]) for r in rows]
