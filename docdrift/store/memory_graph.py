"""Small labelled property graph - the Neo4j stand-in for the base stack.

Implements the same queries as `Neo4jGraphStore`: neighbours by relation, shortest
path, and the approval-authority path.
"""
from __future__ import annotations

from collections import deque


class MemoryGraphStore:
    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.out: dict[str, list[tuple[str, str, dict]]] = {}

    def add_node(self, node_id: str, label: str, **props) -> None:
        self.nodes[node_id] = {"label": label, **props}
        self.out.setdefault(node_id, [])

    def add_edge(self, src: str, rel: str, dst: str, **props) -> None:
        self.out.setdefault(src, []).append((rel, dst, props))
        self.out.setdefault(dst, [])

    def flush(self) -> None:
        return None

    def neighbors(self, node_id: str, rel: str | None = None) -> list[tuple[str, str]]:
        return [(r, d) for r, d, _ in self.out.get(node_id, []) if rel is None or r == rel]

    def path(self, src: str, dst: str, max_depth: int = 4) -> list[str]:
        if src not in self.out:
            return []
        q = deque([(src, [src])])
        seen = {src}
        while q:
            node, trail = q.popleft()
            if node == dst:
                return trail
            if len(trail) > max_depth:
                continue
            for rel, nxt, _ in self.out.get(node, []):
                if nxt in seen:
                    continue
                seen.add(nxt)
                q.append((nxt, trail + [f"-[{rel}]->", nxt]))
        return []

    def authority_path(self, comm_id: str, day: str):
        """(decision)-[DECIDED_BY]->(person)-[HAS_ROLE]->(role)-[AUTHORISED_FOR {window
        covering day}]->(scope)<-[IN_SCOPE]-(decision). Same pattern as the Cypher in
        Neo4jGraphStore.authority_path."""
        from ..models import AuthorityPath
        scopes = {d for r, d, _ in self.out.get(comm_id, []) if r == "IN_SCOPE"}
        for r1, person, _ in self.out.get(comm_id, []):
            if r1 != "DECIDED_BY":
                continue
            for r2, role, _ in self.out.get(person, []):
                if r2 != "HAS_ROLE":
                    continue
                for r3, scope, props in self.out.get(role, []):
                    if r3 != "AUTHORISED_FOR" or scope not in scopes:
                        continue
                    lo, hi = props.get("valid_from"), props.get("valid_to")
                    if lo and lo <= day and (hi is None or day <= hi):
                        return AuthorityPath(
                            comm_id=comm_id, approver_id=person,
                            approver_name=self.nodes.get(person, {}).get("name", person),
                            role=role.removeprefix("ROLE:"), scope_id=scope.removeprefix("SCOPE:"),
                            valid_from=lo, valid_to=hi)
        return None
