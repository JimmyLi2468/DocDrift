"""Neo4j Community graph store for the production stack.

Nodes carry one label and an `id` property; relationships carry the same properties
as the in-memory store (authority windows on AUTHORISED_FOR). Writes are buffered and
sent in UNWIND batches by `flush()`, so loading the corpus is a handful of round trips.
Only `scripts/load_production.py` writes; the API only reads.
"""
from __future__ import annotations

import re
from collections import defaultdict
from urllib.parse import urlparse

_IDENT = re.compile(r"^[A-Z][A-Z_]*$|^[A-Z][A-Za-z]*$")


def _ident(name: str) -> str:
    # Labels and relationship types cannot be query parameters in Cypher, so they are
    # checked against a strict pattern before being placed in the query text.
    if not _IDENT.match(name):
        raise ValueError(f"unsafe graph identifier {name!r}")
    return name


class Neo4jGraphStore:
    def __init__(self, url: str, database: str | None = None, read_only: bool = True) -> None:
        from neo4j import GraphDatabase  # lazily: the base stack does not need the driver

        u = urlparse(url)
        auth = (u.username, u.password) if u.username else None
        self.driver = GraphDatabase.driver(f"{u.scheme}://{u.hostname}:{u.port or 7687}", auth=auth)
        self.driver.verify_connectivity()
        self.database, self.read_only = database, read_only
        self._nodes: dict[str, list[dict]] = defaultdict(list)
        self._edges: dict[str, list[dict]] = defaultdict(list)

    def _run(self, query: str, **params):
        # The API's sessions are READ access mode: the server rejects any write in them
        # ("Writing in read access mode not allowed"). Only the loader opens WRITE sessions.
        import neo4j
        mode = neo4j.READ_ACCESS if self.read_only else neo4j.WRITE_ACCESS
        with self.driver.session(database=self.database, default_access_mode=mode) as s:
            with s.begin_transaction() as tx:          # rolled back if not committed
                rows = list(tx.run(query, **params))
                tx.commit()
                return rows

    def put_fingerprint(self, fp: str) -> None:
        self._run("MERGE (m:Meta {id: 'fingerprint'}) SET m.value = $fp", fp=fp)

    def get_fingerprint(self) -> str | None:
        try:
            rows = self._run("MATCH (m:Meta {id: 'fingerprint'}) RETURN m.value AS v")
            return rows[0]["v"] if rows else None
        except Exception:
            return None

    # ---------------------------------------------------------------- writes
    def clear(self) -> None:
        self._run("MATCH (n) DETACH DELETE n")

    def ensure_schema(self) -> None:
        for label in ("Person", "Role", "Scope", "Communication", "Document", "Version",
                      "Equipment", "Model", "Department", "Change", "Meta"):
            self._run(f"CREATE CONSTRAINT {label.lower()}_id IF NOT EXISTS "
                      f"FOR (n:{label}) REQUIRE n.id IS UNIQUE")

    def add_node(self, node_id: str, label: str, **props) -> None:
        self._nodes[_ident(label)].append({"id": node_id, "props": props})

    def add_edge(self, src: str, rel: str, dst: str, **props) -> None:
        self._edges[_ident(rel)].append({"src": src, "dst": dst, "props": props})

    def flush(self, batch: int = 2000) -> None:
        for label, rows in self._nodes.items():
            for i in range(0, len(rows), batch):
                self._run(f"UNWIND $rows AS r MERGE (n:{label} {{id: r.id}}) SET n += r.props",
                          rows=rows[i:i + batch])
        for rel, rows in self._edges.items():
            for i in range(0, len(rows), batch):
                # MERGE on the endpoint ids only: an edge whose endpoint was never
                # declared as a node gets a bare placeholder node, as in the memory store.
                self._run(f"UNWIND $rows AS r MERGE (a {{id: r.src}}) MERGE (b {{id: r.dst}}) "
                          f"MERGE (a)-[e:{rel}]->(b) SET e += r.props", rows=rows[i:i + batch])
        self._nodes.clear()
        self._edges.clear()

    # ---------------------------------------------------------------- reads
    def neighbors(self, node_id: str, rel: str | None = None) -> list[tuple[str, str]]:
        pattern = f"[r:{_ident(rel)}]" if rel else "[r]"
        rows = self._run(f"MATCH (a {{id: $id}})-{pattern}->(b) RETURN type(r) AS rel, b.id AS dst",
                         id=node_id)
        return [(r["rel"], r["dst"]) for r in rows]

    def path(self, src: str, dst: str, max_depth: int = 4) -> list[str]:
        rows = self._run(
            f"MATCH p = shortestPath((a {{id: $src}})-[*..{int(max_depth)}]->(b {{id: $dst}})) "
            "RETURN [n IN nodes(p) | n.id] AS ids, [r IN relationships(p) | type(r)] AS rels",
            src=src, dst=dst)
        if not rows:
            return []
        ids, rels = rows[0]["ids"], rows[0]["rels"]
        out = [ids[0]]
        for rel, nid in zip(rels, ids[1:]):
            out += [f"-[{rel}]->", nid]
        return out

    AUTHORITY_PATH = (
        "MATCH (c:Communication {id: $comm})-[:DECIDED_BY]->(p:Person)-[:HAS_ROLE]->(r:Role)"
        "-[a:AUTHORISED_FOR]->(s:Scope)<-[:IN_SCOPE]-(c) "
        "WHERE a.valid_from <= $day AND (a.valid_to IS NULL OR $day <= a.valid_to) "
        "RETURN p.id AS person, p.name AS name, r.id AS role, s.id AS scope, "
        "a.valid_from AS valid_from, a.valid_to AS valid_to "
        "ORDER BY a.valid_from LIMIT 1")

    def authority_path(self, comm_id: str, day: str):
        from ..models import AuthorityPath
        rows = self._run(self.AUTHORITY_PATH, comm=comm_id, day=day)
        if not rows:
            return None
        r = rows[0]
        return AuthorityPath(comm_id=comm_id, approver_id=r["person"], approver_name=r["name"] or r["person"],
                             role=r["role"].removeprefix("ROLE:"), scope_id=r["scope"].removeprefix("SCOPE:"),
                             valid_from=r["valid_from"], valid_to=r["valid_to"])

    def count(self) -> tuple[int, int]:
        n = self._run("MATCH (n) RETURN count(n) AS c")[0]["c"]
        e = self._run("MATCH ()-[r]->() RETURN count(r) AS c")[0]["c"]
        return n, e

    def close(self) -> None:
        self.driver.close()
