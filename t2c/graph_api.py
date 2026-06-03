"""Graph API — query interface for the T2C knowledge graph."""
from __future__ import annotations

from typing import Any

import networkx as nx

from t2c.object_store import ObjectStore
from t2c.ontology import EvidenceRef


class GraphAPI:
    def __init__(self, graph: nx.DiGraph, store: ObjectStore) -> None:
        self._graph = graph
        self._store = store

    def find_entities(self, name: str | None = None, kind: str | None = None) -> list[dict]:
        results: list[dict] = []
        for node_id, data in self._graph.nodes(data=True):
            if data.get("type") != "Entity":
                continue
            obj = data.get("data", {})
            if name and obj.get("name") != name:
                continue
            if kind and obj.get("kind") != kind:
                continue
            results.append(obj)
        return results

    def find_events(self, participant: str | None = None, kind: str | None = None) -> list[dict]:
        results: list[dict] = []
        for node_id, data in self._graph.nodes(data=True):
            if data.get("type") != "Event":
                continue
            obj = data.get("data", {})
            if kind and obj.get("kind") != kind:
                continue
            if participant and participant not in obj.get("participants", []):
                continue
            results.append(obj)
        return results

    def find_claims(
        self,
        subject: str | None = None,
        predicate: str | None = None,
        object: str | None = None,
        modality: str | None = None,
    ) -> list[dict]:
        results: list[dict] = []
        for node_id, data in self._graph.nodes(data=True):
            if data.get("type") != "Claim":
                continue
            obj = data.get("data", {})
            if subject and obj.get("subject") != subject:
                continue
            if predicate and obj.get("predicate") != predicate:
                continue
            if object and obj.get("object") != object:
                continue
            if modality and obj.get("modality") != modality:
                continue
            results.append(obj)
        return results

    def find_segments(
        self,
        status: str | None = None,
        has_residual: bool | None = None,
    ) -> list[dict]:
        results: list[dict] = []
        for node_id, data in self._graph.nodes(data=True):
            if data.get("type") != "Segment":
                continue
            if status and data.get("status") != status:
                continue
            seg_id = data.get("data", {}).get("id", node_id)
            residuals = self._store.get_residuals_for_segment(seg_id)
            if has_residual is True and not residuals:
                continue
            if has_residual is False and residuals:
                continue
            results.append(data.get("data", {}))
        return results

    def find_residuals(
        self,
        category: str | None = None,
        importance: str | None = None,
    ) -> list[dict]:
        all_residuals = self._store.query("Residual")
        results: list[dict] = []
        for r in all_residuals:
            if category and r.get("category") != category:
                continue
            if importance and r.get("importance") != importance:
                continue
            results.append(r)
        return results

    def get_object(self, object_id: str) -> dict | None:
        data = self._graph.nodes.get(object_id)
        if data is None:
            return None
        return data.get("data")

    def get_evidence(self, object_id: str) -> list[dict]:
        evidence: list[dict] = []
        obj = self.get_object(object_id)
        if obj is None:
            return evidence
        for ref in obj.get("evidence_refs", []):
            evidence.append(ref)
        return evidence

    def get_segment_coverage(self, segment_id: str) -> str:
        data = self._graph.nodes.get(segment_id)
        if data is None:
            return "uncovered"
        return data.get("status", "uncovered")

    def trace_neighbors(self, object_id: str, depth: int = 1) -> dict:
        result: dict = {"node": self.get_object(object_id), "neighbors": []}
        if result["node"] is None:
            return result

        visited = {object_id}
        current_level = {object_id}

        for _ in range(depth):
            next_level: set[str] = set()
            for nid in current_level:
                for successor in self._graph.successors(nid):
                    if successor not in visited:
                        visited.add(successor)
                        next_level.add(successor)
                        edge_data = self._graph.edges[nid, successor]
                        result["neighbors"].append({
                            "id": successor,
                            "edge_type": edge_data.get("type"),
                            "data": self.get_object(successor),
                        })
                for predecessor in self._graph.predecessors(nid):
                    if predecessor not in visited:
                        visited.add(predecessor)
                        next_level.add(predecessor)
                        edge_data = self._graph.edges[predecessor, nid]
                        result["neighbors"].append({
                            "id": predecessor,
                            "edge_type": edge_data.get("type"),
                            "data": self.get_object(predecessor),
                        })
            current_level = next_level

        return result