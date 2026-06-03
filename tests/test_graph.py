"""Tests for t2c/graph_builder.py and t2c/graph_api.py."""
import pytest

import networkx as nx

from t2c.graph_api import GraphAPI
from t2c.graph_builder import GraphBuilder
from t2c.object_store import ObjectStore
from t2c.ontology import (
    Claim, Document, Entity, Event, IgnoreSegment,
    Relation, Residual, Segment,
)


@pytest.fixture
def populated_store():
    store = ObjectStore()

    # Document
    doc = Document(
        id="doc1", source_path="test.txt",
        raw_text_hash="sha256:abc", total_length=100,
        block_count=1, created_at="2026-05-27T10:00:00Z",
    )
    store.save(doc)

    # Segments
    for i in range(3):
        seg = Segment(
            id=f"doc1_seg_{i:04d}", doc_id="doc1",
            block_index=0, segment_type="sentence",
            start_offset=i * 30, end_offset=(i + 1) * 30,
            text_slice="text", hash="sha256:abc",
        )
        store.save(seg)

    # Entities
    alice = Entity(id="doc1_ent_0001", name="Alice", kind="person",
                   source_segment_ids=["doc1_seg_0000"])
    bob = Entity(id="doc1_ent_0002", name="Bob", kind="person",
                 source_segment_ids=["doc1_seg_0001"])
    acme = Entity(id="doc1_ent_0003", name="Acme", kind="org")
    store.save(alice)
    store.save(bob)
    store.save(acme)

    # Event
    meeting = Event(
        id="doc1_evt_0001", name="Meeting", kind="occurrence",
        participants=["doc1_ent_0001", "doc1_ent_0002"],
        source_segment_ids=["doc1_seg_0000"],
    )
    store.save(meeting)

    # Claims
    claim1 = Claim(
        id="doc1_clm_0001", subject="doc1_ent_0001",
        predicate="works_for", object="doc1_ent_0003",
        modality="asserted", polarity="positive",
        source_segment_ids=["doc1_seg_0000"],
    )
    store.save(claim1)

    # Relation
    rel1 = Relation(
        id="doc1_rel_0001", subject="doc1_ent_0001",
        predicate="works_for", object="doc1_ent_0003",
        claim_id="doc1_clm_0001",
    )
    store.save(rel1)

    # Residual on one segment
    res = Residual(
        id="doc1_res_0001", segment_id="doc1_seg_0001",
        category="stylistic", importance="medium",
        reason="tone nuance",
    )
    store.save(res)

    return store


@pytest.fixture
def graph(populated_store):
    builder = GraphBuilder(populated_store)
    return builder.build_graph("doc1")


@pytest.fixture
def api(graph, populated_store):
    return GraphAPI(graph, populated_store)


class TestGraphBuilder:
    def test_nodes_include_entities(self, graph):
        entity_nodes = [n for n, d in graph.nodes(data=True) if d.get("type") == "Entity"]
        assert len(entity_nodes) == 3

    def test_nodes_include_events(self, graph):
        event_nodes = [n for n, d in graph.nodes(data=True) if d.get("type") == "Event"]
        assert len(event_nodes) == 1

    def test_nodes_include_claims(self, graph):
        claim_nodes = [n for n, d in graph.nodes(data=True) if d.get("type") == "Claim"]
        assert len(claim_nodes) == 1

    def test_nodes_include_segments(self, graph):
        seg_nodes = [n for n, d in graph.nodes(data=True) if d.get("type") == "Segment"]
        assert len(seg_nodes) == 3

    def test_relation_edge(self, graph):
        assert graph.has_edge("doc1_ent_0001", "doc1_ent_0003")
        edge_data = graph.edges["doc1_ent_0001", "doc1_ent_0003"]
        assert edge_data["type"] == "relation"
        assert edge_data["predicate"] == "works_for"

    def test_participant_edge(self, graph):
        assert graph.has_edge("doc1_ent_0001", "doc1_evt_0001")
        assert graph.has_edge("doc1_ent_0002", "doc1_evt_0001")

    def test_evidence_edge_claim_to_segment(self, graph):
        assert graph.has_edge("doc1_clm_0001", "doc1_seg_0000")

    def test_evidence_edge_entity_to_segment(self, graph):
        assert graph.has_edge("doc1_ent_0001", "doc1_seg_0000")

    def test_segment_coverage_status(self, graph):
        seg0_status = graph.nodes["doc1_seg_0000"].get("status")
        assert seg0_status == "covered"


class TestGraphAPIFindEntities:
    def test_find_all_entities(self, api):
        results = api.find_entities()
        assert len(results) == 3

    def test_find_by_kind(self, api):
        results = api.find_entities(kind="person")
        assert len(results) == 2

    def test_find_by_name(self, api):
        results = api.find_entities(name="Alice")
        assert len(results) == 1
        assert results[0]["name"] == "Alice"

    def test_find_by_kind_and_name(self, api):
        results = api.find_entities(name="Alice", kind="person")
        assert len(results) == 1


class TestGraphAPIFindEvents:
    def test_find_all_events(self, api):
        results = api.find_events()
        assert len(results) == 1

    def test_find_by_kind(self, api):
        results = api.find_events(kind="occurrence")
        assert len(results) == 1

    def test_find_by_participant(self, api):
        results = api.find_events(participant="doc1_ent_0001")
        assert len(results) == 1


class TestGraphAPIFindClaims:
    def test_find_all_claims(self, api):
        results = api.find_claims()
        assert len(results) == 1

    def test_find_by_modality(self, api):
        results = api.find_claims(modality="asserted")
        assert len(results) == 1

    def test_find_by_modality_no_match(self, api):
        results = api.find_claims(modality="uncertain")
        assert len(results) == 0


class TestGraphAPIFindSegments:
    def test_find_all_segments(self, api):
        results = api.find_segments()
        assert len(results) == 3

    def test_find_by_status_covered(self, api):
        results = api.find_segments(status="covered")
        assert len(results) == 1

    def test_find_by_status_partial(self, api):
        results = api.find_segments(status="partial")
        assert len(results) == 1


class TestGraphAPIFindResiduals:
    def test_find_all_residuals(self, api):
        results = api.find_residuals()
        assert len(results) == 1

    def test_find_by_category(self, api):
        results = api.find_residuals(category="stylistic")
        assert len(results) == 1


class TestGraphAPIGetObject:
    def test_get_existing_object(self, api):
        obj = api.get_object("doc1_ent_0001")
        assert obj is not None
        assert obj["name"] == "Alice"

    def test_get_nonexistent(self, api):
        assert api.get_object("nonexistent") is None


class TestGraphAPITraceNeighbors:
    def test_trace_depth_1(self, api):
        result = api.trace_neighbors("doc1_ent_0001", depth=1)
        assert result["node"]["name"] == "Alice"
        neighbor_ids = [n["id"] for n in result["neighbors"]]
        # Should include: works_for relation target (Acme),
        # evidence segment, claim, event participant edge back
        assert "doc1_ent_0003" in neighbor_ids

    def test_trace_nonexistent(self, api):
        result = api.trace_neighbors("nonexistent")
        assert result["node"] is None


class TestGraphAPISegmentCoverage:
    def test_covered_segment(self, api):
        assert api.get_segment_coverage("doc1_seg_0000") == "covered"

    def test_partial_segment(self, api):
        assert api.get_segment_coverage("doc1_seg_0001") == "partial"

    def test_uncovered_segment(self, api):
        assert api.get_segment_coverage("doc1_seg_0002") == "uncovered"