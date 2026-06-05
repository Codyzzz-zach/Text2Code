"""Graph Builder — construct derived navigation graph from validated objects."""
from __future__ import annotations

from t2c.object_store import ObjectStore
from t2c.ontology import Claim, Entity, Event, Relation


class GraphBuilder:
    """Build a navigation graph from validated ObjectStore contents.

    Graph is a derived index — never an evidence source.
    """

    def __init__(self, store: ObjectStore) -> None:
        self._store = store

    def build_graph(self) -> dict:
        """Build adjacency graph from stored objects."""
        nodes: dict[str, dict] = {}
        edges: list[dict] = []

        # Add entity nodes
        for entity in self._store.query("Entity"):
            nodes[entity.id] = {
                "type": "Entity",
                "label": entity.name,
                "kind": entity.kind,
            }

        # Add event nodes and participation edges
        for event in self._store.query("Event"):
            nodes[event.id] = {
                "type": "Event",
                "label": event.name,
                "kind": event.kind,
            }
            for participant_id in event.participants:
                edges.append({
                    "source": participant_id,
                    "target": event.id,
                    "type": "participates_in",
                    "edge_class": "navigation",
                })

        # Add claim nodes
        for claim in self._store.query("Claim"):
            nodes[claim.id] = {
                "type": "Claim",
                "label": f"{claim.subject} {claim.predicate} {claim.object}",
                "modality": claim.modality,
                "polarity": claim.polarity,
            }

        # Add relation edges — only safe ones are "fact" class
        for rel in self._store.query("Relation"):
            claim = self._store.load("Claim", rel.claim_id) if rel.claim_id else None
            edge_class = self._classify_relation(rel, claim)

            edges.append({
                "source": rel.subject,
                "target": rel.object,
                "type": rel.predicate,
                "claim_id": rel.claim_id,
                "edge_class": edge_class,
                "modality": claim.modality if claim else None,
                "polarity": claim.polarity if claim else None,
            })

        return {"nodes": nodes, "edges": edges}

    def _classify_relation(self, rel: Relation, claim: Claim | None) -> str:
        """Classify a relation edge as 'fact' or 'claim_index'.

        Only asserted, positive claims with matching subject/object
        produce fact-like edges. Everything else is a claim_index.
        """
        if claim is None:
            return "claim_index"

        if claim.modality != "asserted":
            return "claim_index"

        if claim.polarity != "positive":
            return "claim_index"

        # Verify subject/object alignment
        if claim.subject != rel.subject or claim.object != rel.object:
            return "claim_index"

        # Must have evidence
        has_evidence = (
            bool(claim.evidence_refs)
            or bool(claim.source_segment_ids)
        )
        if not has_evidence:
            return "claim_index"

        return "fact"
