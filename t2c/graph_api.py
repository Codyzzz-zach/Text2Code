"""Graph API — query the derived navigation graph."""
from __future__ import annotations

from t2c.graph_builder import GraphBuilder
from t2c.object_store import ObjectStore


class GraphAPI:
    """Read-only query API over the derived navigation graph.

    Graph results are NOT evidence — they must route back to code/raw.
    """

    def __init__(self, store: ObjectStore) -> None:
        self._store = store
        self._graph: dict | None = None

    def _ensure_graph(self) -> dict:
        if self._graph is None:
            builder = GraphBuilder(self._store)
            self._graph = builder.build_graph()
        return self._graph

    def get_node(self, node_id: str) -> dict | None:
        graph = self._ensure_graph()
        return graph["nodes"].get(node_id)

    def get_neighbors(self, node_id: str) -> list[dict]:
        """Get all edges connected to a node."""
        graph = self._ensure_graph()
        results = []
        for edge in graph["edges"]:
            if edge["source"] == node_id or edge["target"] == node_id:
                results.append(edge)
        return results

    def get_relations(self, entity_id: str, *, fact_only: bool = False) -> list[dict]:
        """Get relation edges for an entity."""
        graph = self._ensure_graph()
        results = []
        for edge in graph["edges"]:
            if edge["source"] != entity_id:
                continue
            if edge["type"] != edge.get("predicate", edge.get("type")):
                continue
            if fact_only and edge.get("edge_class") != "fact":
                continue
            results.append(edge)
        return results

    def get_evidence_refs(self, object_id: str) -> list[dict]:
        """Get evidence refs for any stored object by its ID."""
        from t2c.ontology import ONTOLOGY_CLASSES
        for type_name, cls in ONTOLOGY_CLASSES.items():
            obj = self._store.load(type_name, object_id)
            if obj is not None:
                refs = getattr(obj, "evidence_refs", None)
                if refs:
                    return [r.model_dump() if hasattr(r, "model_dump") else r for r in refs]
                seg_ids = getattr(obj, "source_segment_ids", None)
                if seg_ids:
                    return [{"segment_id": sid, "type": "source_segment"} for sid in seg_ids]
                return []
        return []

    def get_answer_context(self, object_id: str) -> dict:
        """Get full context for an answer: code object + raw quote + coverage + residual."""
        node = self.get_node(object_id)
        evidence = self.get_evidence_refs(object_id)

        # Try to load the raw object
        raw_obj = None
        from t2c.ontology import ONTOLOGY_CLASSES
        for type_name, cls in ONTOLOGY_CLASSES.items():
            loaded = self._store.load(type_name, object_id)
            if loaded is not None:
                raw_obj = loaded.model_dump()
                break

        # Get raw quotes from evidence refs
        raw_quotes: list[dict] = []
        for ref in evidence:
            seg_id = ref.get("segment_id")
            if not seg_id:
                continue
            seg = self._store.load("Segment", seg_id)
            if seg is None:
                continue
            start = ref.get("start")
            end = ref.get("end")
            if start is not None and end is not None:
                raw_quotes.append({
                    "segment_id": seg_id,
                    "quote": seg.text_slice[start:end],
                    "start": start,
                    "end": end,
                })
            else:
                raw_quotes.append({
                    "segment_id": seg_id,
                    "full_text": seg.text_slice,
                })

        return {
            "object_id": object_id,
            "node": node,
            "raw_object": raw_obj,
            "evidence_refs": evidence,
            "raw_quotes": raw_quotes,
        }

    def invalidate_cache(self) -> None:
        self._graph = None
