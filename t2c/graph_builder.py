"""Graph Builder — construct networkx DiGraph from validated objects."""
from __future__ import annotations

import networkx as nx

from t2c.object_store import ObjectStore


class GraphBuilder:
    def __init__(self, store: ObjectStore) -> None:
        self._store = store

    def build_graph(self, doc_id: str) -> nx.DiGraph:
        G = nx.DiGraph()

        # -- Nodes: Document, Block, Segment, Entity, Event, Claim, Residual --

        doc = self._store.get("Document", doc_id)
        if doc:
            G.add_node(doc_id, type="Document", data=doc)

        blocks = self._store.query("Block", doc_id=doc_id)
        for blk in blocks:
            G.add_node(blk["id"], type="Block", data=blk)
            G.add_edge(doc_id, blk["id"], type="contains")

        segments = self._store.get_segments_by_doc(doc_id)
        for seg in segments:
            status = self._segment_status(seg["id"])
            G.add_node(seg["id"], type="Segment", data=seg, status=status)

        # Block → Segment edges
        for seg in segments:
            blk_id = f"{doc_id}_blk_{seg['block_index']:04d}"
            if G.has_node(blk_id):
                G.add_edge(blk_id, seg["id"], type="contains")

        entities = self._store.query("Entity")
        for ent in entities:
            G.add_node(ent["id"], type="Entity", data=ent)

        events = self._store.query("Event")
        for evt in events:
            G.add_node(evt["id"], type="Event", data=evt)

        claims = self._store.query("Claim")
        for clm in claims:
            G.add_node(clm["id"], type="Claim", data=clm)

        residuals = self._store.query("Residual")
        for res in residuals:
            G.add_node(res["id"], type="Residual", data=res)

        # -- Edges --

        # Relation: subject → object
        relations = self._store.query("Relation")
        for rel in relations:
            G.add_edge(
                rel["subject"], rel["object"],
                type="relation", predicate=rel["predicate"],
                claim_id=rel["claim_id"], data=rel,
            )

        # Entity → Event (participates_in)
        for evt in events:
            for participant_id in evt.get("participants", []):
                G.add_edge(
                    participant_id, evt["id"],
                    type="participates_in", data={},
                )

        # Entity → Segment (evidence)
        for ent in entities:
            for seg_id in ent.get("source_segment_ids", []):
                G.add_edge(
                    ent["id"], seg_id,
                    type="evidence", data={},
                )

        # Event → Segment (evidence)
        for evt in events:
            for seg_id in evt.get("source_segment_ids", []):
                G.add_edge(
                    evt["id"], seg_id,
                    type="evidence", data={},
                )

        # Claim → Segment (evidence)
        for clm in claims:
            for seg_id in clm.get("source_segment_ids", []):
                G.add_edge(
                    clm["id"], seg_id,
                    type="evidence", data={},
                )

        # Segment → Residual
        for res in residuals:
            seg_id = res.get("segment_id")
            if seg_id and G.has_node(seg_id):
                G.add_edge(seg_id, res["id"], type="has_residual", data={})

        return G

    def _segment_status(self, segment_id: str) -> str:
        has_semantic = bool(self._store.get_semantic_objects_for_segment(segment_id))
        residuals = self._store.get_residuals_for_segment(segment_id)
        has_residual = bool(residuals)
        is_ignored = bool(self._store.query("IgnoreSegment", segment_id=segment_id))

        if is_ignored:
            return "ignored"
        if has_semantic and not has_residual:
            return "covered"
        if has_semantic and has_residual:
            return "partial"
        if not has_semantic and has_residual:
            return "raw_only"
        return "uncovered"