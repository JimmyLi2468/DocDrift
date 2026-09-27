"""PostgreSQL record store for the production stack.

Same tables and queries as `SqliteRecordStore`, in schema `docdrift`, with JSONB
payloads. Two database roles (created by deploy/postgres/init.sql):

  docdrift_loader  owns the schema; used only by scripts/load_production.py
  docdrift_reader  SELECT on the records, nothing else; used by the API

So the API's connection cannot change a record even if the code tried: PostgreSQL
refuses it. `seal()` additionally marks the session read-only.
"""
from __future__ import annotations

from datetime import date
from typing import Sequence

from ..governance import AuthorityMatrix
from ..models import (Chunk, Communication, Department, DocumentVersion, Equipment,
                      Person)

SCHEMA = """
CREATE SCHEMA IF NOT EXISTS docdrift;
CREATE TABLE IF NOT EXISTS docdrift.equipment (asset_tag TEXT PRIMARY KEY, payload JSONB NOT NULL,
    family TEXT, model TEXT);
CREATE TABLE IF NOT EXISTS docdrift.departments (department_id TEXT PRIMARY KEY, payload JSONB NOT NULL);
CREATE TABLE IF NOT EXISTS docdrift.people (person_id TEXT PRIMARY KEY, payload JSONB NOT NULL, role TEXT);
CREATE TABLE IF NOT EXISTS docdrift.doc_versions (doc_id TEXT, version TEXT, payload JSONB NOT NULL,
    effective_date DATE, status TEXT, PRIMARY KEY (doc_id, version));
CREATE TABLE IF NOT EXISTS docdrift.chunks (chunk_id TEXT PRIMARY KEY, doc_id TEXT, version TEXT,
    payload JSONB NOT NULL);
CREATE TABLE IF NOT EXISTS docdrift.communications (comm_id TEXT PRIMARY KEY, date DATE,
    change_ref TEXT, channel TEXT, payload JSONB NOT NULL);
CREATE TABLE IF NOT EXISTS docdrift.governance (key TEXT PRIMARY KEY, payload JSONB NOT NULL);
CREATE INDEX IF NOT EXISTS ix_chunks_docver ON docdrift.chunks (doc_id, version);
CREATE INDEX IF NOT EXISTS ix_comms_date ON docdrift.communications (date);
CREATE INDEX IF NOT EXISTS ix_comms_change ON docdrift.communications (change_ref);
"""

TABLES = ("equipment", "departments", "people", "doc_versions", "chunks", "communications", "governance")


class PostgresRecordStore:
    def __init__(self, url: str) -> None:
        import psycopg  # lazily: the base stack does not need the driver
        from psycopg.types.json import Jsonb

        self._Jsonb = Jsonb
        self.conn = psycopg.connect(url, autocommit=True)
        self.sealed = False

    # ---------------------------------------------------------------- loader only
    def create_schema(self) -> None:
        # The schema itself is created by deploy/postgres/init.sql and owned by the
        # loader. PostgreSQL checks the database-level CREATE privilege before it
        # checks IF NOT EXISTS, and the loader deliberately does not hold it, so the
        # CREATE SCHEMA statement is only sent when the schema is really missing.
        exists = self.conn.execute(
            "SELECT 1 FROM pg_namespace WHERE nspname = 'docdrift'").fetchone()
        for stmt in filter(None, (s.strip() for s in SCHEMA.split(";"))):
            if exists and stmt.upper().startswith("CREATE SCHEMA"):
                continue
            self.conn.execute(stmt)

    def truncate(self) -> None:
        self.conn.execute("TRUNCATE " + ", ".join(f"docdrift.{t}" for t in TABLES))

    def _bulk(self, sql: str, rows: list[tuple]) -> None:
        with self.conn.cursor() as cur:
            cur.executemany(sql, rows)

    def _j(self, model) -> object:
        return self._Jsonb(model.model_dump(mode="json"))

    def upsert_equipment(self, items: Sequence[Equipment]) -> None:
        self._bulk("INSERT INTO docdrift.equipment VALUES (%s,%s,%s,%s) ON CONFLICT (asset_tag) DO UPDATE "
                   "SET payload = EXCLUDED.payload, family = EXCLUDED.family, model = EXCLUDED.model",
                   [(e.asset_tag, self._j(e), e.family, e.model) for e in items])

    def upsert_people(self, items: Sequence[Person]) -> None:
        self._bulk("INSERT INTO docdrift.people VALUES (%s,%s,%s) ON CONFLICT (person_id) DO UPDATE "
                   "SET payload = EXCLUDED.payload, role = EXCLUDED.role",
                   [(p.person_id, self._j(p), p.role) for p in items])

    def upsert_versions(self, items: Sequence[DocumentVersion]) -> None:
        self._bulk("INSERT INTO docdrift.doc_versions VALUES (%s,%s,%s,%s,%s) ON CONFLICT (doc_id, version) "
                   "DO UPDATE SET payload = EXCLUDED.payload, effective_date = EXCLUDED.effective_date, "
                   "status = EXCLUDED.status",
                   [(v.doc_id, v.version, self._j(v), v.effective_date, v.status) for v in items])

    def upsert_chunks(self, items: Sequence[Chunk]) -> None:
        self._bulk("INSERT INTO docdrift.chunks VALUES (%s,%s,%s,%s) ON CONFLICT (chunk_id) DO UPDATE "
                   "SET doc_id = EXCLUDED.doc_id, version = EXCLUDED.version, payload = EXCLUDED.payload",
                   [(c.chunk_id, c.doc_id, c.version, self._j(c)) for c in items])

    def upsert_communications(self, items: Sequence[Communication]) -> None:
        self._bulk("INSERT INTO docdrift.communications VALUES (%s,%s,%s,%s,%s) ON CONFLICT (comm_id) "
                   "DO UPDATE SET date = EXCLUDED.date, change_ref = EXCLUDED.change_ref, "
                   "channel = EXCLUDED.channel, payload = EXCLUDED.payload",
                   [(c.comm_id, c.date, c.change_ref, c.channel.value, self._j(c)) for c in items])

    def upsert_departments(self, items: Sequence[Department]) -> None:
        self._bulk("INSERT INTO docdrift.departments VALUES (%s,%s) ON CONFLICT (department_id) "
                   "DO UPDATE SET payload = EXCLUDED.payload",
                   [(d.department_id, self._j(d)) for d in items])

    def put_authority(self, matrix: AuthorityMatrix) -> None:
        self.conn.execute("INSERT INTO docdrift.governance VALUES ('authority_matrix', %s) "
                          "ON CONFLICT (key) DO UPDATE SET payload = EXCLUDED.payload", (self._j(matrix),))

    def put_fingerprint(self, fp: str) -> None:
        self.conn.execute("INSERT INTO docdrift.governance VALUES ('fingerprint', %s) "
                          "ON CONFLICT (key) DO UPDATE SET payload = EXCLUDED.payload", (self._Jsonb(fp),))

    # ---------------------------------------------------------------- API
    def get_fingerprint(self) -> str | None:
        try:
            return self._one("SELECT payload FROM docdrift.governance WHERE key = 'fingerprint'", ())
        except Exception:
            return None
    def seal(self) -> None:
        """The API's session is read-only; the reader role cannot write in any case."""
        self.conn.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
        self.sealed = True

    def _rows(self, sql: str, params: tuple = ()) -> list:
        return [r[0] for r in self.conn.execute(sql, params).fetchall()]

    def _one(self, sql: str, params: tuple):
        r = self.conn.execute(sql, params).fetchone()
        return r[0] if r else None

    def is_loaded(self) -> bool:
        return bool(self._one("SELECT count(*) FROM docdrift.chunks", ()))

    def counts(self) -> dict[str, int]:
        return {t: self._one(f"SELECT count(*) FROM docdrift.{t}", ()) for t in TABLES}

    def get_authority(self) -> AuthorityMatrix:
        p = self._one("SELECT payload FROM docdrift.governance WHERE key = 'authority_matrix'", ())
        return AuthorityMatrix.model_validate(p) if p else AuthorityMatrix()

    def all_equipment(self) -> list[Equipment]:
        return [Equipment.model_validate(p) for p in self._rows("SELECT payload FROM docdrift.equipment")]

    def get_equipment(self, asset_tag: str) -> Equipment | None:
        p = self._one("SELECT payload FROM docdrift.equipment WHERE asset_tag = %s", (asset_tag,))
        return Equipment.model_validate(p) if p else None

    def get_person(self, person_id: str) -> Person | None:
        p = self._one("SELECT payload FROM docdrift.people WHERE person_id = %s", (person_id,))
        return Person.model_validate(p) if p else None

    def all_people(self) -> list[Person]:
        return [Person.model_validate(p) for p in self._rows("SELECT payload FROM docdrift.people")]

    def versions_for_doc(self, doc_id: str) -> list[DocumentVersion]:
        rows = self._rows("SELECT payload FROM docdrift.doc_versions WHERE doc_id = %s", (doc_id,))
        return sorted((DocumentVersion.model_validate(p) for p in rows), key=lambda v: v.effective_date)

    def versions_for_family(self, family: str) -> list[DocumentVersion]:
        rows = self._rows("SELECT payload FROM docdrift.doc_versions "
                          "WHERE payload->'applies_to_families' ? %s", (family,))
        return [DocumentVersion.model_validate(p) for p in rows]

    def all_versions(self) -> list[DocumentVersion]:
        return [DocumentVersion.model_validate(p) for p in self._rows("SELECT payload FROM docdrift.doc_versions")]

    def chunks_for(self, doc_id: str, version: str) -> list[Chunk]:
        rows = self._rows("SELECT payload FROM docdrift.chunks WHERE doc_id = %s AND version = %s "
                          "ORDER BY chunk_id", (doc_id, version))
        return [Chunk.model_validate(p) for p in rows]

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        p = self._one("SELECT payload FROM docdrift.chunks WHERE chunk_id = %s", (chunk_id,))
        return Chunk.model_validate(p) if p else None

    def all_chunks(self) -> list[Chunk]:
        return [Chunk.model_validate(p) for p in self._rows("SELECT payload FROM docdrift.chunks ORDER BY chunk_id")]

    def get_department(self, department_id: str) -> Department | None:
        p = self._one("SELECT payload FROM docdrift.departments WHERE department_id = %s", (department_id,))
        return Department.model_validate(p) if p else None

    def all_departments(self) -> list[Department]:
        return [Department.model_validate(p) for p in self._rows("SELECT payload FROM docdrift.departments")]

    def communications_for_change(self, change_ref: str) -> list[Communication]:
        rows = self._rows("SELECT payload FROM docdrift.communications WHERE change_ref = %s "
                          "ORDER BY date, comm_id", (change_ref,))
        return [Communication.model_validate(p) for p in rows]

    def communications_since(self, since: date) -> list[Communication]:
        rows = self._rows("SELECT payload FROM docdrift.communications WHERE date >= %s "
                          "ORDER BY date, comm_id", (since,))
        return [Communication.model_validate(p) for p in rows]

    def all_communications(self) -> list[Communication]:
        return [Communication.model_validate(p)
                for p in self._rows("SELECT payload FROM docdrift.communications ORDER BY date, comm_id")]
