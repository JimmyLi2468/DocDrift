"""Tiny labelled property graph - the Neo4j Community stand-in.

Only two query shapes are needed by the pipeline (neighbours by relation, and a
shortest authorisation path), which is what `GraphStore` exposes.
"""
from __future__ import annotations

from collections import deque


class MemoryGraphStore:
    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.out: dict[str, list[tuple[str, str]]] = {}

    def add_node(self, node_id: str, label: str, **props) -> None:
        self.nodes[node_id] = {"label": label, **props}
        self.out.setdefault(node_id, [])

    def add_edge(self, src: str, rel: str, dst: str) -> None:
        self.out.setdefault(src, []).append((rel, dst))
        self.out.setdefault(dst, [])

    def neighbors(self, node_id: str, rel: str | None = None) -> list[tuple[str, str]]:
        return [(r, d) for r, d in self.out.get(node_id, []) if rel is None or r == rel]

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
            for rel, nxt in self.out.get(node, []):
                if nxt in seen:
                    continue
                seen.add(nxt)
                q.append((nxt, trail + [f"-[{rel}]->", nxt]))
        return []
