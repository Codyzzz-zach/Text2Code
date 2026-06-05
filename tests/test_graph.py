"""Tests for t2c/graph_builder.py and t2c/graph_api.py — derived navigation graph."""
import hashlib

import pytest

from t2c.graph_api import GraphAPI
from t2c.graph_builder import GraphBuilder
from t2c.object_store import ObjectStore
from t2c.ontology import Claim, Entity, Relation, Segment, Event, Residual


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture
def populated_store():
    """Create a store with sample entities, claims, and relations."""
    store = ObjectStore()

    # Segments
    store.save(Segment(id="s1", doc_id="d1", block_index=0, segment_type="sentence",
                        start_offset=0, end_offset=10, text_slice="Hello world",
                        hash=_sha256("Hello world")))
    store.save(Segment(id="s2", doc_id="d1", block_index=0, segment_type="sentence",
                        start_offset=10, end_offset=20, text_slice="Goodbye world",
                        hash=_sha256("Goodbye world")))

    # Entities
    store.save(Entity(id="e1", name="Alice", kind="person", source_segment_ids=["s1"]))
    store.save(Entity(id="e2", name="Bob", kind="person", source_segment_ids=["s2"]))

    # Claim (asserted + positive → safe for fact edge)
    store.save(Claim(
        id="c1", subject="e1", predicate="knows", object="e2",
        modality="asserted", polarity="positive", confidence=1.0,
        source_segment_ids=["s1"],
    ))

    # Relation with safe claim
    store.save(Relation(
        id="r1", subject="e1", predicate="knows", object="e2", claim_id="c1",
    ))

    # Claim (reported → unsafe for fact edge)
    store.save(Claim(
        id="c2", subject="e1", predicate="rumored_about", object="e2",
        modality="reported", polarity="positive", confidence=0.5,
        source_segment_ids=["s2"],
    ))

    # Relation with unsafe claim
    store.save(Relation(
        id="r2", subject="e1", predicate="rumored_about", object="e2", claim_id="c2",
    ))

    yield store
    store.close()


class TestGraphBuilder:
    def test_build_graph_contains_nodes(self, populated_store):
        builder = GraphBuilder(populated_store)
        graph = builder.build_graph()
        assert "e1" in graph["nodes"]
        assert "e2" in graph["nodes"]
        assert graph["nodes"]["e1"]["label"] == "Alice"

    def test_build_graph_contains_edges(self, populated_store):
        builder = GraphBuilder(populated_store)
        graph = builder.build_graph()
        assert len(graph["edges"]) >= 2

    def test_fact_edge_for_asserted_positive(self, populated_store):
        builder = GraphBuilder(populated_store)
        graph = builder.build_graph()
        fact_edges = [e for e in graph["edges"] if e.get("edge_class") == "fact"]
        assert len(fact_edges) >= 1
        assert fact_edges[0]["type"] == "knows"

    def test_claim_index_for_reported(self, populated_store):
        builder = GraphBuilder(populated_store)
        graph = builder.build_graph()
        claim_idx_edges = [e for e in graph["edges"] if e.get("edge_class") == "claim_index"]
        assert len(claim_idx_edges) >= 1


class TestGraphAPI:
    def test_get_node(self, populated_store):
        api = GraphAPI(populated_store)
        node = api.get_node("e1")
        assert node is not None
        assert node["label"] == "Alice"

    def test_get_neighbors(self, populated_store):
        api = GraphAPI(populated_store)
        neighbors = api.get_neighbors("e1")
        assert len(neighbors) >= 1

    def test_get_evidence_refs(self, populated_store):
        api = GraphAPI(populated_store)
        refs = api.get_evidence_refs("e1")
        assert isinstance(refs, list)

    def test_get_answer_context(self, populated_store):
        api = GraphAPI(populated_store)
        ctx = api.get_answer_context("e1")
        assert ctx["object_id"] == "e1"
        assert ctx["node"] is not None
        assert isinstance(ctx["evidence_refs"], list)
